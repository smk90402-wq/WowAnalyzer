"""Build a static, sanitized replay snapshot for public distribution.

The exporter deliberately consumes the existing ``local_replay`` API payloads
instead of copying CCTV JSON or combat logs.  Public output contains only
derived replay data.  Original video object keys are written to a separate
private map for a Worker to resolve behind anonymous ``videos/<id>`` routes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app import local_replay


SCHEMA_VERSION = 1

_PLAYER_GUID_RE = re.compile(r"Player-\d+-[A-Za-z0-9-]+")
_SAFE_PUBLIC_ID_RE = re.compile(r"^[a-f0-9]{24}$")
_SAFE_VIDEO_KEY_RE = re.compile(r"^cctv/[^/\\]+\.mp4$", re.IGNORECASE)
_LOCAL_PATH_RE = re.compile(
    r"(?i)(?:[a-z]:[\\/]|\\\\|/(?:users|home|tmp|var|program files)/)"
)
_FORBIDDEN_TEXT_RE = re.compile(
    r"(?i)(?:[a-z][a-z0-9+.-]*://|(?:^|[^a-z0-9])r2:|"
    r"rclone(?:\.conf)?|wowcombatlog|access[_ -]?key|secret[_ -]?key)"
)
_DROP_KEYS = frozenset({
    "file",
    "player_guid",
    "realm",
    "server",
    "region",
    "guild",
    "account",
    "email",
    "report_code",
    "report_url",
    "fight_url",
    "url",
    "log_file",
    "json_file",
    "video_file",
    "start_line",
    "end_line",
    "start_off",
    "end_off",
})
_DROP_CONTAINERS = frozenset({"sources"})


class PublicReplayExportError(RuntimeError):
    """Raised before replacing the previous public snapshot."""


@dataclass(frozen=True)
class PublicReplayExportResult:
    output_dir: Path
    private_video_map: Path | None
    replays: int
    videos: int
    terrain: int


class _Aliases:
    """Per-replay aliases that keep cross-payload player references stable."""

    def __init__(self) -> None:
        self.guid_to_id: dict[str, str] = {}
        self.name_to_ids: dict[str, set[str]] = {}
        self.name_alias_candidates: dict[str, set[str]] = {}
        self.realm_values: set[str] = set()
        self._used_ids: set[str] = set()
        self._next_id = 1

    def add(
        self,
        *,
        guid: Any = "",
        name: Any = "",
        preferred_id: Any = "",
        realm: Any = "",
    ) -> str:
        guid_s = str(guid or "")
        name_s = str(name or "").strip()
        preferred = str(preferred_id or "")
        realm_s = str(realm or "").strip()
        if realm_s:
            self.realm_values.add(realm_s)

        existing = self.guid_to_id.get(guid_s) if guid_s else None
        full_name = self._full_name(name_s, realm_s)
        if not existing and re.fullmatch(r"p[1-9]\d*", preferred):
            # frames의 기존 synthetic ID가 이름보다 강한 identity다. realm 없는
            # 동명이 같은 name으로 들어와도 p1/p2를 합치지 않는다.
            existing = preferred
        if not existing and full_name:
            ids = self.name_to_ids.get(full_name) or set()
            if len(ids) == 1:
                existing = next(iter(ids))

        unit_id = self._claim_id(existing or preferred)
        alias = f"Player {int(unit_id[1:])}"
        if guid_s:
            self.guid_to_id[guid_s] = unit_id
        if full_name:
            self.name_to_ids.setdefault(full_name, set()).add(unit_id)
            self.name_alias_candidates.setdefault(full_name, set()).add(alias)
        if name_s:
            self.name_alias_candidates.setdefault(name_s, set()).add(alias)
            base = name_s.split("-", 1)[0]
            if len(base) >= 2:
                self.name_alias_candidates.setdefault(base, set()).add(alias)
        return unit_id

    def _claim_id(self, preferred: str) -> str:
        if re.fullmatch(r"p[1-9]\d*", preferred):
            unit_id = preferred
        else:
            while f"p{self._next_id}" in self._used_ids:
                self._next_id += 1
            unit_id = f"p{self._next_id}"
            self._next_id += 1
        self._used_ids.add(unit_id)
        return unit_id

    @staticmethod
    def _full_name(name: str, realm: str) -> str:
        if not name:
            return ""
        if realm and "-" not in name:
            return f"{name}-{realm}"
        return name

    def text_replacements(self) -> dict[str, str]:
        """Known full names stay specific; ambiguous realm-less names do not."""
        return {
            name: next(iter(candidates)) if len(candidates) == 1 else "Player"
            for name, candidates in self.name_alias_candidates.items()
        }


VideoKeyResolver = Callable[[str, dict[str, Any]], str | None]
TerrainLoader = Callable[[str], dict[str, Any] | None]


def export_public_replays(
    output_dir: str | Path,
    *,
    private_video_map: str | Path | None = None,
    limit: int = 80,
    include_terrain: bool = True,
    generated_at: datetime | None = None,
    video_key_resolver: VideoKeyResolver | None = None,
    terrain_loader: TerrainLoader | None = None,
    available_video_keys: set[str] | None = None,
) -> PublicReplayExportResult:
    """Generate and atomically publish a sanitized static replay tree.

    ``private_video_map`` must be outside ``output_dir``.  It maps anonymous
    public replay ids to original R2 keys and must never be uploaded under the
    public prefix.
    """
    destination = _validate_output_dir(Path(output_dir))
    private_map_path = (
        _validate_private_map_path(Path(private_video_map), destination)
        if private_video_map is not None else None
    )
    if limit < 1:
        raise ValueError("limit must be at least 1")
    normalized_available_video_keys: set[str] | None = None
    if available_video_keys is not None:
        if not available_video_keys:
            raise PublicReplayExportError("available video allowlist is empty")
        normalized_available_video_keys = {
            _normalize_video_object_key(key)
            for key in available_video_keys
        }

    stamp = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    generated_text = stamp.isoformat(timespec="seconds").replace("+00:00", "Z")
    using_default_video_resolver = video_key_resolver is None
    resolver = video_key_resolver or _default_video_object_key
    load_terrain = terrain_loader or _default_terrain

    destination.parent.mkdir(parents=True, exist_ok=True)
    stage: Path | None = Path(tempfile.mkdtemp(
        prefix=f".{destination.name}.staging-",
        dir=destination.parent,
    ))
    private_stage: Path | None = None
    try:
        manifest_rows: list[dict[str, Any]] = []
        video_map: dict[str, str] = {}
        terrain_count = 0
        seen_public_ids: set[str] = set()

        listing = local_replay.list_replays(limit=None)
        source_rows = listing.get("rows") or []
        if not isinstance(source_rows, list):
            raise PublicReplayExportError("local replay list rows must be a list")

        for source_row in source_rows:
            if len(manifest_rows) >= limit:
                break
            if not isinstance(source_row, dict):
                raise PublicReplayExportError("local replay row must be an object")
            source_id = str(source_row.get("id") or "").strip()
            if not source_id:
                raise PublicReplayExportError("local replay row has no id")
            public_id = _public_id(source_id)

            object_key: str | None = None
            if private_map_path is not None:
                if using_default_video_resolver:
                    try:
                        object_key = resolver(source_id, source_row)
                    except local_replay.ReplayError:
                        continue
                else:
                    object_key = resolver(source_id, source_row)
                if object_key:
                    object_key = _normalize_video_object_key(object_key)
                if (
                    normalized_available_video_keys is not None
                    and object_key not in normalized_available_video_keys
                ):
                    continue

            try:
                detail = local_replay.replay_detail(source_id)
                frames = local_replay.replay_frames(source_id)
            except local_replay.ReplayError:
                continue

            if public_id in seen_public_ids:
                raise PublicReplayExportError(
                    f"duplicate public replay id: {public_id}"
                )
            seen_public_ids.add(public_id)
            aliases = _build_aliases(source_row, detail, frames)

            if object_key:
                video_map[public_id] = object_key

            replacements = {source_id: public_id}
            safe_row = _sanitize(source_row, aliases, replacements)
            safe_detail = _sanitize(detail, aliases, replacements)
            safe_frames = _sanitize(frames, aliases, replacements)
            if not isinstance(safe_row, dict):
                raise PublicReplayExportError("sanitized replay row is not an object")
            if not isinstance(safe_detail, dict) or not isinstance(safe_frames, dict):
                raise PublicReplayExportError("sanitized replay payload is not an object")

            safe_row["id"] = public_id
            safe_row["video_exists"] = False
            safe_row["video_remote"] = bool(object_key)
            safe_detail["schema_version"] = SCHEMA_VERSION
            safe_detail["video"] = {
                "available": bool(object_key),
                "url": "",
                "remote": bool(object_key),
            }
            safe_frames["schema_version"] = SCHEMA_VERSION

            replay_dir = stage / "replays" / public_id
            replay_dir.mkdir(parents=True, exist_ok=False)
            detail_rel = f"replays/{public_id}/detail.json"
            frames_rel = f"replays/{public_id}/frames.json"
            _write_json(replay_dir / "detail.json", safe_detail)
            _write_json(replay_dir / "frames.json", safe_frames)

            terrain_rel: str | None = None
            if include_terrain:
                try:
                    terrain = load_terrain(source_id)
                except Exception:
                    terrain = None
                if terrain:
                    safe_terrain = _sanitize(terrain, aliases, replacements)
                    if not isinstance(safe_terrain, dict):
                        raise PublicReplayExportError(
                            "sanitized replay terrain is not an object"
                        )
                    safe_terrain["schema_version"] = SCHEMA_VERSION
                    terrain_rel = f"replays/{public_id}/terrain.json"
                    _write_json(replay_dir / "terrain.json", safe_terrain)
                    terrain_count += 1

            safe_row["public_artifacts"] = {
                "detail": detail_rel,
                "frames": frames_rel,
                "terrain": terrain_rel,
                "video": f"videos/{public_id}" if object_key else None,
            }
            _assert_public_payload(safe_row, aliases)
            _assert_public_payload(safe_detail, aliases)
            _assert_public_payload(safe_frames, aliases)
            manifest_rows.append(safe_row)

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_text,
            "rows": manifest_rows,
            "stats": {
                "replays": len(manifest_rows),
                "videos": len(video_map),
                "terrain": terrain_count,
            },
        }
        _assert_public_payload(manifest, None)
        _write_json(stage / "manifest.json", manifest)

        if private_map_path is not None:
            private_map_path.parent.mkdir(parents=True, exist_ok=True)
            fd, private_name = tempfile.mkstemp(
                prefix=f".{private_map_path.name}.staging-",
                dir=private_map_path.parent,
            )
            os.close(fd)
            private_stage = Path(private_name)
            _write_json(private_stage, {
                "schemaVersion": SCHEMA_VERSION,
                "videos": video_map,
            })

        if private_map_path is not None and private_stage is not None:
            os.replace(private_stage, private_map_path)
            private_stage = None
        _publish_tree(stage, destination)
        stage = None

        return PublicReplayExportResult(
            output_dir=destination,
            private_video_map=private_map_path,
            replays=len(manifest_rows),
            videos=len(video_map),
            terrain=terrain_count,
        )
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        if private_stage and private_stage.exists():
            private_stage.unlink(missing_ok=True)


def _build_aliases(
    row: dict[str, Any],
    detail: dict[str, Any],
    frames: dict[str, Any],
) -> _Aliases:
    aliases = _Aliases()
    for unit in (frames.get("meta") or {}).get("units") or []:
        if isinstance(unit, dict) and unit.get("kind") == "player":
            aliases.add(name=unit.get("name"), preferred_id=unit.get("id"))
    for actor in detail.get("actors") or []:
        if not isinstance(actor, dict):
            continue
        guid = str(actor.get("guid") or "")
        if guid.startswith("Player-"):
            aliases.add(
                guid=guid,
                name=actor.get("name"),
                realm=actor.get("realm"),
            )
    for position in detail.get("positions") or []:
        if not isinstance(position, dict):
            continue
        guid = str(position.get("guid") or "")
        if guid.startswith("Player-"):
            aliases.add(guid=guid, name=position.get("name"))
    capture = detail.get("capture") or row
    if isinstance(capture, dict):
        guid = str(capture.get("player_guid") or "")
        name = capture.get("player")
        if guid.startswith("Player-") or name:
            aliases.add(guid=guid, name=name)

    for payload in (row, detail, frames):
        for guid in _find_player_guids(payload):
            aliases.add(guid=guid)
    return aliases


def _find_player_guids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            found.update(_find_player_guids(child))
    elif isinstance(value, (list, tuple, set)):
        for child in value:
            found.update(_find_player_guids(child))
    elif isinstance(value, str):
        found.update(_PLAYER_GUID_RE.findall(value))
    return found


def _sanitize(
    value: Any,
    aliases: _Aliases,
    replacements: dict[str, str],
) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized = key.lower()
            if (
                key.startswith("_")
                or normalized in _DROP_KEYS
                or normalized in _DROP_CONTAINERS
                or normalized.endswith("_path")
                or normalized.endswith("_guid")
                or normalized.endswith("_url")
            ):
                continue
            if normalized == "guid" and isinstance(child, str):
                out[key] = aliases.guid_to_id.get(child, child)
            else:
                out[key] = _sanitize(child, aliases, replacements)
        return out
    if isinstance(value, (list, tuple)):
        return [_sanitize(child, aliases, replacements) for child in value]
    if isinstance(value, set):
        return sorted(_sanitize(child, aliases, replacements) for child in value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        raise PublicReplayExportError("filesystem path reached public payload")
    if not isinstance(value, str):
        return value

    text = value
    for old, new in replacements.items():
        text = text.replace(old, new)
    for guid, unit_id in aliases.guid_to_id.items():
        text = text.replace(guid, unit_id)
    for name, alias in sorted(
        aliases.text_replacements().items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        text = text.replace(name, alias)
    for realm in sorted(aliases.realm_values, key=len, reverse=True):
        text = text.replace(realm, "Realm")
    return text


def _assert_public_payload(value: Any, aliases: _Aliases | None) -> None:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if _PLAYER_GUID_RE.search(text):
        raise PublicReplayExportError("player GUID remained in public payload")
    if _LOCAL_PATH_RE.search(text) or _FORBIDDEN_TEXT_RE.search(text):
        raise PublicReplayExportError("private path, URL, or credential marker remained")
    if aliases is None:
        return
    for original in (*aliases.name_alias_candidates.keys(), *aliases.realm_values):
        if len(original) >= 2 and original in text:
            raise PublicReplayExportError(
                "player name or realm remained in public payload"
            )


def _public_id(source_id: str) -> str:
    digest = hashlib.sha256(f"wowanalyzer-public-v1:{source_id}".encode()).hexdigest()
    public_id = digest[:24]
    if not _SAFE_PUBLIC_ID_RE.fullmatch(public_id):
        raise PublicReplayExportError("failed to build a URL-safe replay id")
    return public_id


def _default_video_object_key(
    source_id: str,
    row: dict[str, Any],
) -> str | None:
    if not (row.get("video_exists") or row.get("video_remote")):
        return None
    cap = local_replay._find_capture(source_id)
    local_video = cap.get("_video_path")
    if isinstance(local_video, Path) and local_video.exists():
        return f"cctv/{local_video.name}"
    json_path = cap.get("_json_path")
    if isinstance(json_path, Path):
        remote_name = local_replay._remote_video_name(json_path)
        if remote_name:
            return f"cctv/{remote_name}"
    return None


def _normalize_video_object_key(value: str) -> str:
    key = str(value).replace("\\", "/").strip("/")
    if (
        not _SAFE_VIDEO_KEY_RE.fullmatch(key)
        or ".." in key.split("/")
        or ":" in key
        or _FORBIDDEN_TEXT_RE.search(key)
    ):
        raise PublicReplayExportError("unsafe video object key")
    return key


def _default_terrain(source_id: str) -> dict[str, Any] | None:
    from app import replay_terrain

    request = local_replay.replay_terrain_request(source_id)
    return replay_terrain.terrain_grid(request["instance_id"], request["bbox"])


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def _validate_output_dir(path: Path) -> Path:
    destination = path.expanduser().resolve()
    if (
        destination == Path(destination.anchor)
        or destination == Path.cwd().resolve()
        or destination == Path.home().resolve()
        or (destination / ".git").exists()
    ):
        raise PublicReplayExportError("refusing unsafe public output directory")
    if destination.exists() and not destination.is_dir():
        raise PublicReplayExportError("public output exists and is not a directory")
    return destination


def _validate_private_map_path(path: Path, destination: Path) -> Path:
    private_path = path.expanduser().resolve()
    if private_path == destination or destination in private_path.parents:
        raise PublicReplayExportError(
            "private video map must be outside the public output directory"
        )
    if private_path.exists() and not private_path.is_file():
        raise PublicReplayExportError("private video map exists and is not a file")
    return private_path


def _publish_tree(stage: Path, destination: Path) -> None:
    backup = destination.parent / f".{destination.name}.backup-{uuid.uuid4().hex}"
    had_previous = destination.exists()
    if had_previous:
        os.replace(destination, backup)
    try:
        os.replace(stage, destination)
    except Exception:
        if had_previous and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)
