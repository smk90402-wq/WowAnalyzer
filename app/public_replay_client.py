"""Public, read-only replay feed client.

Release builds must never contain R2 credentials.  An administrator publishes
curated artifacts behind an HTTPS endpoint (normally a Cloudflare Worker), and
this module merges those artifacts with any replay data available locally.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import requests


log = logging.getLogger("app.public_replay")

SCHEMA_VERSION = 1
DEFAULT_TTL_S = 300
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_REDIRECTS = 5
CACHE_FORMAT_VERSION = 1
BASE_URL_ENV = "WOWANALYZER_PUBLIC_REPLAY_BASE_URL"
MANIFEST_URL_ENV = "WOWANALYZER_PUBLIC_REPLAY_MANIFEST_URL"
CACHE_DIR_ENV = "WOWANALYZER_PUBLIC_REPLAY_CACHE_DIR"
CONFIG_NAME = "public_replay.json"
_PUBLIC_ID_RE = re.compile(r"^[a-f0-9]{24}$")
_ARTIFACT_KINDS = frozenset({"detail", "frames", "terrain"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class PublicReplayError(RuntimeError):
    pass


_lock = threading.RLock()
_manifest_cache: tuple[float, str, dict[str, Any]] | None = None
_status: dict[str, Any] = {}


def _runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "data"
    return Path(__file__).resolve().parent.parent / "data"


def _cache_dir() -> Path:
    override = str(os.environ.get(CACHE_DIR_ENV) or "").strip()
    return Path(override) if override else _data_dir() / "public_replay_cache"


def _read_config_file() -> dict[str, Any]:
    candidates = (
        _runtime_dir() / CONFIG_NAME,
        _data_dir() / CONFIG_NAME,
    )
    for path in candidates:
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            log.warning("공개 리플레이 설정 읽기 실패: %s (%s)", path, exc)
            continue
        if isinstance(value, dict):
            return value
    return {}


def _url_origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlparse(value)
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower()
        if not hostname or parsed.username is not None or parsed.password is not None:
            return None
        if scheme == "https":
            default_port = 443
        elif scheme == "http" and hostname in {"127.0.0.1", "localhost", "::1"}:
            default_port = 80
        else:
            return None
        port = parsed.port or default_port
    except (TypeError, ValueError):
        return None
    return scheme, hostname, port


def _is_allowed_url(value: str) -> bool:
    return _url_origin(value) is not None


def config() -> dict[str, str]:
    file_config = _read_config_file()
    base_url = str(
        os.environ.get(BASE_URL_ENV)
        or file_config.get("base_url")
        or ""
    ).strip().rstrip("/")
    manifest_url = str(
        os.environ.get(MANIFEST_URL_ENV)
        or file_config.get("manifest_url")
        or ""
    ).strip()
    if not manifest_url and base_url:
        manifest_url = f"{base_url}/manifest.json"
    if base_url and not _is_allowed_url(base_url):
        log.warning("공개 리플레이 base URL 거부: HTTPS가 아님")
        base_url = ""
    if manifest_url and not _is_allowed_url(manifest_url):
        log.warning("공개 리플레이 manifest URL 거부: HTTPS가 아님")
        manifest_url = ""
    if not base_url and manifest_url:
        parsed = urlparse(manifest_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
    return {"base_url": base_url, "manifest_url": manifest_url}


def configured() -> bool:
    return bool(config().get("manifest_url"))


def release_mode() -> bool:
    """True only for the sanitized public package assembled by build.bat."""
    return (_runtime_dir() / f"{CONFIG_NAME}.example").is_file()


def _cache_scope(cfg: dict[str, str] | None = None) -> str:
    cfg = config() if cfg is None else cfg
    contract = {
        "base_url": str(cfg.get("base_url") or "").rstrip("/"),
        "manifest_url": str(cfg.get("manifest_url") or ""),
        "base_origin": _url_origin(str(cfg.get("base_url") or "")),
        "manifest_origin": _url_origin(str(cfg.get("manifest_url") or "")),
    }
    raw = json.dumps(
        contract,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _require_public_id(value: Any) -> str:
    replay_id = str(value or "").strip()
    if not _PUBLIC_ID_RE.fullmatch(replay_id):
        raise PublicReplayError("공개 리플레이 ID 형식 오류")
    return replay_id


def invalidate() -> None:
    global _manifest_cache, _status
    with _lock:
        _manifest_cache = None
        _status = {}


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(_json_bytes(value))
    tmp.replace(path)


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _download_json(url: str, max_bytes: int) -> dict[str, Any]:
    expected_origin = _url_origin(url)
    if expected_origin is None:
        raise PublicReplayError("공개 서버 URL이 안전하지 않음")

    current_url = url
    response: requests.Response | Any | None = None
    for redirect_count in range(MAX_REDIRECTS + 1):
        try:
            response = requests.get(
                current_url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "WowAnalyzer-PublicReplay/1",
                },
                timeout=(5, 45),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise PublicReplayError(f"공개 서버 요청 실패: {exc}") from exc

        response_url = urljoin(
            current_url,
            str(getattr(response, "url", "") or current_url),
        )
        if _url_origin(response_url) != expected_origin:
            raise PublicReplayError("공개 서버가 다른 origin으로 응답함")

        status_code = getattr(response, "status_code", None)
        if type(status_code) is not int:
            raise PublicReplayError("공개 서버 HTTP 상태 형식 오류")
        if status_code not in _REDIRECT_STATUSES:
            break
        if redirect_count >= MAX_REDIRECTS:
            raise PublicReplayError("공개 서버 redirect 횟수 초과")
        location = str((getattr(response, "headers", {}) or {}).get("Location") or "")
        if not location:
            raise PublicReplayError("공개 서버 redirect 위치 누락")
        next_url = urljoin(response_url, location)
        if _url_origin(next_url) != expected_origin:
            raise PublicReplayError("공개 서버 redirect origin 거부")
        current_url = next_url

    if response is None:
        raise PublicReplayError("공개 서버 응답 없음")
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise PublicReplayError(f"공개 서버 요청 실패: {exc}") from exc

    content = response.content
    if not isinstance(content, (bytes, bytearray)):
        raise PublicReplayError("공개 서버 응답 형식 오류")
    if len(content) > max_bytes:
        raise PublicReplayError(
            f"공개 JSON 크기 초과: {len(content)} > {max_bytes}"
        )
    try:
        value = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicReplayError("공개 서버 JSON 형식 오류") from exc
    if not isinstance(value, dict):
        raise PublicReplayError("공개 서버 JSON 객체가 아님")
    return value


def _validate_artifact_ref(value: Any) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or value != value.strip() or "\\" in value:
        raise PublicReplayError("공개 artifact 경로 형식 오류")
    ref = value
    parsed = urlparse(ref)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise PublicReplayError("공개 artifact 경로는 상대경로여야 함")
    path = PurePosixPath(ref)
    normalized = str(path)
    if path.is_absolute() or ".." in path.parts or normalized != ref:
        raise PublicReplayError("공개 artifact 경로가 안전하지 않음")
    return normalized


def _expected_artifact_ref(replay_id: str, kind: str) -> str:
    if kind in _ARTIFACT_KINDS:
        return f"replays/{replay_id}/{kind}.json"
    if kind == "video":
        return f"videos/{replay_id}"
    raise PublicReplayError(f"지원하지 않는 공개 artifact: {kind}")


def _validate_manifest(value: dict[str, Any]) -> dict[str, Any]:
    schema_version = value.get("schema_version")
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        raise PublicReplayError(
            f"지원하지 않는 공개 manifest schema: {schema_version}"
        )
    generated_at = value.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise PublicReplayError("공개 manifest generated_at 형식 오류")
    rows = value.get("rows")
    if not isinstance(rows, list):
        raise PublicReplayError("공개 manifest rows 누락")
    stats = value.get("stats")
    if not isinstance(stats, dict):
        raise PublicReplayError("공개 manifest stats 형식 오류")
    for name in ("replays", "videos", "terrain"):
        count = stats.get(name)
        if type(count) is not int or count < 0:
            raise PublicReplayError(f"공개 manifest stats.{name} 형식 오류")

    seen: set[str] = set()
    clean_rows: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise PublicReplayError(f"공개 manifest row[{index}] 형식 오류")
        replay_id = _require_public_id(raw.get("id"))
        if replay_id in seen:
            raise PublicReplayError(f"공개 manifest ID 중복: {replay_id}")
        artifacts = raw.get("public_artifacts")
        if not isinstance(artifacts, dict):
            raise PublicReplayError(f"공개 manifest artifact 형식 오류: {replay_id}")
        capabilities = raw.get("capabilities", {})
        if not isinstance(capabilities, dict):
            raise PublicReplayError(f"공개 manifest capabilities 형식 오류: {replay_id}")

        clean_artifacts: dict[str, str] = {}
        for name in ("detail", "frames", "terrain", "video"):
            ref = _validate_artifact_ref(artifacts.get(name))
            expected = _expected_artifact_ref(replay_id, name)
            if name in {"detail", "frames"}:
                if ref != expected:
                    raise PublicReplayError(
                        f"공개 manifest {name} 경로 계약 오류: {replay_id}"
                    )
            elif ref and ref != expected:
                raise PublicReplayError(
                    f"공개 manifest {name} 경로 계약 오류: {replay_id}"
                )
            clean_artifacts[name] = ref

        row = copy.deepcopy(raw)
        row["id"] = replay_id
        row["public_artifacts"] = clean_artifacts
        clean_rows.append(row)
        seen.add(replay_id)

    if stats.get("replays") != len(clean_rows):
        raise PublicReplayError("공개 manifest replay 통계 불일치")
    out = copy.deepcopy(value)
    out["rows"] = clean_rows
    return out


def _scope_cache_dir(scope: str) -> Path:
    return _cache_dir() / "scopes" / scope


def _manifest_cache_path(scope: str) -> Path:
    return _scope_cache_dir(scope) / "manifest.json"


def _manifest_cache_record(
    cfg: dict[str, str],
    scope: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    return {
        "cache_version": CACHE_FORMAT_VERSION,
        "scope": scope,
        "base_url": cfg.get("base_url") or "",
        "manifest_url": cfg.get("manifest_url") or "",
        "manifest": value,
    }


def _read_cached_manifest(
    cfg: dict[str, str],
    scope: str,
) -> dict[str, Any] | None:
    record = _read_json_file(_manifest_cache_path(scope))
    if record is None:
        return None
    if (
        record.get("cache_version") != CACHE_FORMAT_VERSION
        or record.get("scope") != scope
        or record.get("base_url") != (cfg.get("base_url") or "")
        or record.get("manifest_url") != (cfg.get("manifest_url") or "")
        or not isinstance(record.get("manifest"), dict)
    ):
        return None
    return _validate_manifest(record["manifest"])


def _set_status(**values: Any) -> None:
    global _status
    cfg = config()
    base = {
        "configured": bool(cfg.get("manifest_url")),
        "available": False,
        "stale": False,
        "source": "disabled" if not cfg.get("manifest_url") else "none",
        "base_url": cfg.get("base_url") or "",
        "manifest_url": cfg.get("manifest_url") or "",
        "replays": 0,
        "error": "",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(values)
    _status = base


def manifest(force: bool = False) -> dict[str, Any] | None:
    global _manifest_cache
    cfg = config()
    manifest_url = cfg.get("manifest_url") or ""
    if not manifest_url:
        with _lock:
            _set_status()
        return None
    scope = _cache_scope(cfg)
    now = time.monotonic()
    with _lock:
        if (
            not force
            and _manifest_cache is not None
            and _manifest_cache[1] == scope
            and now - _manifest_cache[0] < DEFAULT_TTL_S
        ):
            return _manifest_cache[2]

    remote_error = ""
    try:
        value = _validate_manifest(
            _download_json(manifest_url, MAX_MANIFEST_BYTES)
        )
        try:
            _write_json_atomic(
                _manifest_cache_path(scope),
                _manifest_cache_record(cfg, scope, value),
            )
        except OSError as exc:
            log.warning("공개 리플레이 manifest 캐시 쓰기 실패: %s", exc)
        with _lock:
            _manifest_cache = (now, scope, value)
            _set_status(
                available=True,
                source="remote",
                replays=len(value["rows"]),
            )
        return value
    except (OSError, PublicReplayError) as exc:
        remote_error = str(exc)
        log.warning("공개 리플레이 manifest 갱신 실패: %s", exc)

    try:
        value = _read_cached_manifest(cfg, scope)
    except PublicReplayError:
        value = None
    if value is not None:
        with _lock:
            _manifest_cache = (now, scope, value)
            _set_status(
                available=True,
                stale=True,
                source="cache",
                replays=len(value["rows"]),
                error=remote_error,
            )
        return value

    with _lock:
        _set_status(error=remote_error)
    return None


def status() -> dict[str, Any]:
    with _lock:
        if not _status:
            _set_status()
        return copy.deepcopy(_status)


def _public_row(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PublicReplayError("공개 manifest row 형식 오류")
    row = copy.deepcopy(raw)
    artifacts = row.get("public_artifacts")
    if not isinstance(artifacts, dict):
        raise PublicReplayError("공개 manifest artifact 형식 오류")
    has_frames = bool(artifacts.get("frames"))
    has_terrain = bool(artifacts.get("terrain"))
    has_video = bool(artifacts.get("video"))
    raw_capabilities = row.get("capabilities", {})
    if not isinstance(raw_capabilities, dict):
        raise PublicReplayError("공개 manifest capabilities 형식 오류")
    capabilities = dict(raw_capabilities)
    capabilities.update({
        "frames": has_frames,
        "terrain": has_terrain,
        "video": has_video,
        "analysis": bool(artifacts.get("detail") or row.get("analysis")),
    })
    row.update({
        "public_remote": True,
        "video_exists": False,
        "video_remote": has_video,
        "capabilities": capabilities,
    })
    return row


def rows(force: bool = False) -> list[dict[str, Any]]:
    value = manifest(force=force)
    if value is None:
        return []
    return [_public_row(row) for row in value["rows"]]


def merge_listing(
    local_listing: dict[str, Any],
    limit: int = 80,
    force: bool = False,
) -> dict[str, Any]:
    local_rows = [
        copy.deepcopy(row)
        for row in (local_listing.get("rows") or [])
        if isinstance(row, dict)
    ]
    merged: dict[str, dict[str, Any]] = {}
    for row in local_rows:
        replay_id = str(row.get("id") or "")
        if replay_id:
            merged[replay_id] = row
    for row in rows(force=force):
        replay_id = str(row.get("id") or "")
        if replay_id and replay_id not in merged:
            merged[replay_id] = row
    merged_rows = sorted(
        merged.values(),
        key=lambda row: str(row.get("start_local") or ""),
        reverse=True,
    )[:max(1, int(limit or 1))]
    result = copy.deepcopy(local_listing)
    result["rows"] = merged_rows
    sources = dict(result.get("sources") or {})
    remote_status = status()
    sources["public_remote"] = remote_status
    sources["public_replays"] = sum(
        1 for row in merged_rows if row.get("public_remote")
    )
    result["sources"] = sources
    return result


def _manifest_row(replay_id: str) -> dict[str, Any] | None:
    replay_id = _require_public_id(replay_id)
    value = manifest()
    if value is None:
        return None
    return next(
        (row for row in value["rows"] if str(row.get("id") or "") == replay_id),
        None,
    )


def has_replay(replay_id: str) -> bool:
    try:
        return _manifest_row(replay_id) is not None
    except PublicReplayError:
        return False


def _artifact_contract(replay_id: str, kind: str) -> tuple[str, str, str]:
    replay_id = _require_public_id(replay_id)
    if kind not in _ARTIFACT_KINDS and kind != "video":
        raise PublicReplayError(f"지원하지 않는 공개 artifact: {kind}")

    cfg = config()
    base_url = cfg.get("base_url") or ""
    if not base_url:
        raise PublicReplayError("공개 리플레이 base URL 없음")
    scope = _cache_scope(cfg)

    row = _manifest_row(replay_id)
    if row is None:
        raise PublicReplayError(f"공개 리플레이 없음: {replay_id}")
    artifacts = row.get("public_artifacts")
    if not isinstance(artifacts, dict):
        raise PublicReplayError("공개 manifest artifact 형식 오류")
    ref = _validate_artifact_ref(artifacts.get(kind))
    if not ref:
        raise PublicReplayError(f"공개 {kind} 자료 없음: {replay_id}")
    if ref != _expected_artifact_ref(replay_id, kind):
        raise PublicReplayError(f"공개 {kind} 경로 계약 오류: {replay_id}")

    # 환경변수가 manifest 조회 도중 바뀌어도 서로 다른 endpoint 계약을 섞지 않는다.
    if _cache_scope(config()) != scope:
        raise PublicReplayError("공개 리플레이 endpoint가 변경됨")
    url = urljoin(f"{base_url}/", quote(ref, safe="/"))
    return url, scope, ref


def _artifact_url(replay_id: str, kind: str) -> str:
    return _artifact_contract(replay_id, kind)[0]


def _artifact_cache_path(
    scope: str,
    replay_id: str,
    kind: str,
    ref: str,
) -> Path:
    ref_hash = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:16]
    return (
        _scope_cache_dir(scope)
        / "replays"
        / replay_id
        / f"{kind}-{ref_hash}.json"
    )


def _artifact_cache_record(
    scope: str,
    replay_id: str,
    kind: str,
    ref: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    return {
        "cache_version": CACHE_FORMAT_VERSION,
        "scope": scope,
        "replay_id": replay_id,
        "kind": kind,
        "ref": ref,
        "artifact": value,
    }


def _validate_artifact_payload(
    value: dict[str, Any],
    kind: str,
) -> dict[str, Any]:
    schema_version = value.get("schema_version")
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        raise PublicReplayError(
            f"지원하지 않는 공개 {kind} schema: {schema_version}"
        )
    return value


def _read_cached_artifact(
    path: Path,
    scope: str,
    replay_id: str,
    kind: str,
    ref: str,
) -> dict[str, Any] | None:
    record = _read_json_file(path)
    if record is None or (
        record.get("cache_version") != CACHE_FORMAT_VERSION
        or record.get("scope") != scope
        or record.get("replay_id") != replay_id
        or record.get("kind") != kind
        or record.get("ref") != ref
        or not isinstance(record.get("artifact"), dict)
    ):
        return None
    return _validate_artifact_payload(record["artifact"], kind)


def artifact(replay_id: str, kind: str) -> dict[str, Any]:
    replay_id = _require_public_id(replay_id)
    if kind not in _ARTIFACT_KINDS:
        raise PublicReplayError(f"지원하지 않는 공개 artifact: {kind}")

    # manifest membership/ref 확인은 fallback 블록 밖에서 한다. 목록에서 삭제된
    # replay나 artifact는 과거 디스크 캐시가 있어도 절대 되살리지 않는다.
    url, scope, ref = _artifact_contract(replay_id, kind)
    cache_path = _artifact_cache_path(scope, replay_id, kind, ref)
    try:
        value = _validate_artifact_payload(
            _download_json(url, MAX_ARTIFACT_BYTES),
            kind,
        )
        try:
            _write_json_atomic(
                cache_path,
                _artifact_cache_record(
                    scope,
                    replay_id,
                    kind,
                    ref,
                    value,
                ),
            )
        except OSError as exc:
            log.warning("공개 %s 캐시 쓰기 실패: %s", kind, exc)
        return value
    except PublicReplayError as exc:
        # 실패 사이 manifest 삭제/ref 변경/base URL 변경이 있었다면 fallback 금지.
        try:
            current_url, current_scope, current_ref = _artifact_contract(
                replay_id,
                kind,
            )
        except PublicReplayError as current_error:
            raise current_error from exc
        if (current_url, current_scope, current_ref) != (url, scope, ref):
            raise PublicReplayError("공개 artifact 계약이 변경됨") from exc

        try:
            cached = _read_cached_artifact(
                cache_path,
                scope,
                replay_id,
                kind,
                ref,
            )
        except PublicReplayError:
            cached = None
        if cached is None:
            raise PublicReplayError(str(exc)) from exc
        log.warning(
            "공개 %s 갱신 실패, 캐시 사용: %s (%s)",
            kind,
            replay_id,
            exc,
        )
        return cached


def detail(replay_id: str) -> dict[str, Any]:
    replay_id = _require_public_id(replay_id)
    value = artifact(replay_id, "detail")
    row = _manifest_row(replay_id)
    if row is None:
        raise PublicReplayError(f"공개 리플레이 없음: {replay_id}")
    artifacts = row.get("public_artifacts")
    if not isinstance(artifacts, dict):
        raise PublicReplayError("공개 manifest artifact 형식 오류")
    out = copy.deepcopy(value)
    out["video"] = {
        "available": bool(artifacts.get("video")),
        "url": (
            f"/api/local-replay/video-remote/{quote(replay_id, safe='')}"
            if artifacts.get("video")
            else ""
        ),
        "remote": bool(artifacts.get("video")),
    }
    sources = out.get("sources", {})
    if not isinstance(sources, dict):
        raise PublicReplayError("공개 detail sources 형식 오류")
    out["sources"] = {"public_remote": True}
    return out


def frames(replay_id: str) -> dict[str, Any]:
    return artifact(replay_id, "frames")


def terrain(replay_id: str) -> dict[str, Any]:
    return artifact(replay_id, "terrain")


def video_url(replay_id: str) -> str:
    return _artifact_url(replay_id, "video")
