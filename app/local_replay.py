from __future__ import annotations

import bisect
import csv
import hashlib
import json
import logging
import os
import re
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any


KST = timezone(timedelta(hours=9))
DEFAULT_LOG_DIR = Path(os.environ.get(
    "WOW_LOG_DIR",
    r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs",
))
DEFAULT_CCTV_DIR = Path(os.environ.get("WARCRAFTCCTV_DIR", r"E:\cctv"))
LURA_SYNC_NAME = "lura_trials_20260719_sync.json"

# 함수 안 지연 임포트만 있으면 PyInstaller 번들 누락 위험 — 최상위에서 명시 임포트
from app import cctv_sync as _cctv_sync  # noqa: E402
from app import replay_mechanics


def cctv_dir() -> Path:
    """캡처 폴더 해석: 설정/기본 경로 → 바탕화면 cctvlog → R2 미러 순.

    바탕화면 cctvlog: E:\\cctv 없는 PC(RTV 등)에서 영상+json+전투로그를 한 폴더에
    몰아넣는 간이 루트 — 로컬 파일이 있으면 스트리밍 대신 그걸 쓴다.
    """
    if DEFAULT_CCTV_DIR.exists():
        return DEFAULT_CCTV_DIR
    desk = Path.home() / "Desktop" / "cctvlog"
    if desk.exists():
        return desk
    from app import cctv_sync
    return cctv_sync.ensure_mirror()


def wow_log_dir() -> Path:
    """전투로그 폴더 해석: WoW 설치 경로가 있으면 그대로, 없으면 R2 미러 폴백."""
    if DEFAULT_LOG_DIR.exists():
        return DEFAULT_LOG_DIR
    from app import cctv_sync
    return cctv_sync.mirror_log_dir()

_LOG_LINE_RE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\.\d+)\s{2}(.*)$"
)


class ReplayError(RuntimeError):
    pass


def _parse_log_ts(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%m/%d/%Y %H:%M:%S.%f")
    except ValueError:
        return None


def _csv_row(rest: str) -> list[str]:
    try:
        return next(csv.reader([rest]))
    except Exception:
        return []


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, "", "nil"):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "nil"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_name(name: Any) -> str:
    if name in (None, "", "nil"):
        return ""
    return str(name).strip('"')


def _flags_int(value: Any) -> int:
    """전투로그 flags 필드('0x10a48') → int. 실패 시 0."""
    try:
        return int(str(value), 16)
    except (TypeError, ValueError):
        return 0


def latest_log_path(log_dir: Path | None = None) -> Path | None:
    log_dir = log_dir or wow_log_dir()
    if not log_dir.exists():
        return None
    logs = list(log_dir.glob("WoWCombatLog-*.txt"))
    if not logs:
        return None
    return max(logs, key=lambda p: p.stat().st_mtime_ns)


def _file_sig(path: Path) -> tuple[str, int, int]:
    st = path.stat()
    return str(path), st.st_mtime_ns, st.st_size


def _read_cctv_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    last_error: Exception | None = None
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return json.loads(raw.decode(enc))
        except Exception as exc:
            last_error = exc
    raise ReplayError(f"CCTV JSON parse failed: {path.name}: {last_error}")


def _video_for_json(path: Path) -> Path:
    """캡처 json 의 영상 파일. 정확 일치 우선, 없으면 'stem*.mp4' 글롭
    (OBS 재녹화 등으로 '-003' 접미사가 붙는 실사례 — 가장 큰 파일 채택)."""
    exact = path.with_suffix(".mp4")
    if exact.exists():
        return exact
    # glob 금지 — 캡처 파일명의 "[M]" 이 문자 클래스로 해석돼 매칭이 깨짐
    try:
        cands = sorted((p for p in path.parent.iterdir()
                        if p.suffix.lower() == ".mp4" and p.name.startswith(path.stem)),
                       key=lambda p: p.stat().st_size, reverse=True)
    except OSError:
        cands = []
    return cands[0] if cands else exact


def _remote_video_name(path: Path) -> str | None:
    """로컬에 영상이 없을 때 R2 쪽 영상 파일명 (프리사인 스트리밍용)."""
    from app import cctv_sync
    stem = path.stem
    for name in cctv_sync.remote_files():
        if name.endswith(".mp4") and name.startswith(stem):
            return name
    return None


def _capture_id(path: Path, data: dict[str, Any]) -> str:
    # 파일명 기반 — 절대경로를 쓰면 exe(data 정션)/개발/미러/PC마다 id가 달라져
    # 목록·상세 간 불일치("replay not found")가 났다. 같은 캡처=같은 id가 정답.
    raw = str(data.get("uniqueHash") or "").strip()
    path_hash = hashlib.sha1(path.name.encode("utf-8", errors="ignore")).hexdigest()[:12]
    if raw:
        return f"{raw[:8]}-{path_hash}"
    return path_hash


def _filename_start(path: Path) -> datetime | None:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2}) (\d{2})-(\d{2})-(\d{2})", path.name)
    if not m:
        return None
    y, mo, d, h, mi, s = map(int, m.groups())
    return datetime(y, mo, d, h, mi, s)


def _json_start_local(path: Path, data: dict[str, Any]) -> datetime | None:
    start_ms = _to_int(data.get("start"), 0)
    if start_ms:
        return datetime.fromtimestamp(start_ms / 1000, KST).replace(tzinfo=None)
    return _filename_start(path)


def _public_capture(cap: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in cap.items() if not k.startswith("_")}


def _lura_sync_path() -> Path:
    from app import replay_map
    return replay_map.DATA_DIR / LURA_SYNC_NAME


def _analysis_flags(pull: dict[str, Any], best_fight_id: int) -> list[dict[str, str]]:
    fight_id = _to_int(pull.get("fight_id"))
    terminate = pull.get("terminate") or {}
    clusters = pull.get("death_clusters") or []

    def cause_count(cluster: dict[str, Any], name: str) -> int:
        return sum(
            _to_int(row.get("deaths"))
            for row in cluster.get("causes") or []
            if row.get("name") == name
        )

    if fight_id == best_fight_id:
        return [{"key": "best", "label": "★ 최고 진행", "severity": "best"}]
    if _to_int(terminate.get("completed")) >= 5:
        return [{"key": "interrupt", "label": "차단 붕괴", "severity": "danger"}]
    if _to_int(pull.get("last_phase")) >= 3 and any(
        float(cluster.get("start_t") or 0) >= 330 and _to_int(cluster.get("events")) >= 5
        for cluster in clusters
    ):
        return [{"key": "p3_transition", "label": "P3 전환 붕괴", "severity": "danger"}]
    if any(cause_count(cluster, "Radiance") >= 8 for cluster in clusters):
        return [{"key": "radiance", "label": "광휘 연쇄", "severity": "danger"}]
    if any(cause_count(cluster, "Dissonance") >= 7 for cluster in clusters):
        return [{"key": "dissonance", "label": "불화 동시 피격", "severity": "danger"}]
    if _to_float(pull.get("boss_remaining_pct")) is not None and float(
        pull.get("boss_remaining_pct")
    ) <= 50:
        return [{"key": "deep", "label": "50% 이하", "severity": "info"}]
    return []


def _public_trial(
    pull: dict[str, Any],
    report: dict[str, Any],
    session: dict[str, Any],
    early_cutoff_s: float,
    rank: int,
) -> dict[str, Any]:
    fight_id = _to_int(pull.get("fight_id"))
    best_fight_id = _to_int(session.get("best_fight_id"))
    best_pct = _to_float(session.get("best_boss_remaining_pct"))
    best_duration = next(
        (
            _to_float(row.get("duration_s"))
            for row in session.get("_pulls") or []
            if _to_int(row.get("fight_id")) == best_fight_id
        ),
        None,
    )
    boss_pct = _to_float(pull.get("boss_remaining_pct"))
    duration = _to_float(pull.get("duration_s"))
    terminate = dict(pull.get("terminate") or {})
    terminate["other"] = max(
        0,
        _to_int(terminate.get("begun"))
        - _to_int(terminate.get("interrupted"))
        - _to_int(terminate.get("completed")),
    )
    analysis = {
        "source": str(pull.get("source") or ""),
        "report_code": str(report.get("code") or ""),
        "report_url": str(report.get("url") or ""),
        "fight_id": fight_id,
        "fight_url": str(pull.get("wcl_url") or ""),
        "pull": _to_int(pull.get("pull")),
        "start_kst": str(pull.get("start_kst") or ""),
        "duration_s": duration or 0.0,
        "duration_delta_ms": pull.get("duration_delta_ms"),
        "boss_remaining_pct": boss_pct,
        "last_phase": _to_int(pull.get("last_phase")),
        "phase": f"P{_to_int(pull.get('last_phase'))}",
        "kill": bool(pull.get("kill")),
        "progress_rank": rank,
        "deaths": _to_int(pull.get("deaths")),
        "unique_dead_players": _to_int(pull.get("unique_dead_players")),
        "repeat_deaths": _to_int(pull.get("repeat_deaths")),
        "early_deaths": _to_int(pull.get("early_deaths")),
        "early_cutoff_seconds": early_cutoff_s,
        "first_death": pull.get("first_death"),
        "death_clusters": pull.get("death_clusters") or [],
        "final_wipe_causes": pull.get("final_wipe_causes") or [],
        "terminate": terminate,
        "bloodlust_casts": _to_int(pull.get("bloodlust_casts")),
        "session_bloodlust_casts": _to_int(session.get("bloodlust_casts")),
        "item_level": _to_float(pull.get("item_level")) or 0.0,
        "raid_wall_dps": _to_float(pull.get("raid_wall_dps")) or 0.0,
        "raid_wall_hps": _to_float(pull.get("raid_wall_hps")) or 0.0,
        "best_fight_id": best_fight_id,
        "best_boss_remaining_pct": best_pct,
        "compare_best": {
            "boss_remaining_delta_pp": (
                round(boss_pct - best_pct, 2)
                if boss_pct is not None and best_pct is not None else None
            ),
            "duration_delta_s": (
                round(duration - best_duration, 3)
                if duration is not None and best_duration is not None else None
            ),
        },
        "caveats": [
            "사망 원인은 직접 결정타이며 근본 원인과 다를 수 있습니다.",
            f"조기 사망은 종료 {early_cutoff_s:g}초 이전이라는 임의 분석 기준입니다.",
            "마지막 8초 결정타는 붕괴 시작 원인을 뜻하지 않습니다.",
        ],
    }
    analysis["flags"] = _analysis_flags({**pull, "fight_id": fight_id}, best_fight_id)
    return analysis


def _empty_lura_sync_index() -> dict[str, Any]:
    return {
        "by_replay_id": {},
        "local_trials": [],
        "wcl_only": [],
        "artifact_ids": set(),
        "session": {},
        "report": {},
    }


@lru_cache(maxsize=4)
def _lura_sync_cached(path_str: str, mtime_ns: int, size: int) -> dict[str, Any]:
    del mtime_ns, size
    try:
        data = json.loads(Path(path_str).read_text(encoding="utf-8"))
    except Exception:
        return _empty_lura_sync_index()
    pulls = [row for row in data.get("pulls") or [] if isinstance(row, dict)]
    report = dict(data.get("report") or {})
    session = dict(data.get("session") or {})
    session["_pulls"] = pulls
    cutoff = _to_float(
        (data.get("death_patterns") or {}).get("early_cutoff_seconds_before_end")
    ) or 8.0
    ranked = sorted(
        pulls,
        key=lambda row: (
            _to_float(row.get("boss_remaining_pct"))
            if _to_float(row.get("boss_remaining_pct")) is not None else 101.0,
            -(_to_float(row.get("duration_s")) or 0.0),
        ),
    )
    ranks = {_to_int(row.get("fight_id")): i for i, row in enumerate(ranked, 1)}
    public = [
        _public_trial(row, report, session, cutoff, ranks[_to_int(row.get("fight_id"))])
        for row in pulls
    ]
    by_replay_id = {
        str(row.get("local_replay_id")): analysis
        for row, analysis in zip(pulls, public)
        if row.get("local_replay_id")
    }
    artifacts = {
        str(row.get("replay_id"))
        for row in (data.get("local") or {}).get("instant_artifacts") or []
        if row.get("replay_id")
    }
    session.pop("_pulls", None)
    return {
        "by_replay_id": by_replay_id,
        "local_trials": [
            row for row in public if row.get("source") == "local+wcl"
        ],
        "wcl_only": [row for row in public if row.get("source") == "wcl-only"],
        "artifact_ids": artifacts,
        "session": session,
        "report": report,
    }


def _lura_sync_index() -> dict[str, Any]:
    path = _lura_sync_path()
    try:
        return _lura_sync_cached(*_file_sig(path))
    except OSError:
        return _empty_lura_sync_index()


def _analysis_start_local(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _enrich_trial_cap(cap: dict[str, Any]) -> dict[str, Any]:
    index = _lura_sync_index()
    analysis = index["by_replay_id"].get(str(cap.get("id") or ""))
    if analysis is None and _to_int(cap.get("encounter_id")) == 3183:
        cap_start = cap.get("_start_dt")
        cap_duration = _to_float(cap.get("duration"))
        if isinstance(cap_start, datetime) and cap_duration is not None:
            for candidate in index["local_trials"]:
                candidate_start = _analysis_start_local(candidate.get("start_kst") or "")
                if candidate_start is None:
                    continue
                if (
                    abs((candidate_start - cap_start).total_seconds()) <= 0.5
                    and abs((_to_float(candidate.get("duration_s")) or 0) - cap_duration)
                    <= 0.25
                ):
                    analysis = candidate
                    break
    if analysis is None:
        return cap
    out = dict(cap)
    out["analysis"] = analysis
    out["boss_percent"] = analysis.get("boss_remaining_pct")
    out["deaths"] = analysis.get("deaths")
    out["analysis_only"] = False
    out["capabilities"] = {
        "frames": True,
        "terrain": True,
        "video": bool(out.get("video_exists") or out.get("video_remote")),
        "analysis": True,
    }
    return out


def _wcl_only_cap(analysis: dict[str, Any]) -> dict[str, Any]:
    report_code = str(analysis.get("report_code") or "")
    fight_id = _to_int(analysis.get("fight_id"))
    start_dt = _analysis_start_local(str(analysis.get("start_kst") or ""))
    return {
        "id": f"wcl-{report_code}-{fight_id}",
        "file": "",
        "encounter_id": 3183,
        "encounter": "한밤의 도래",
        "difficulty": "신화",
        "difficulty_id": 16,
        "duration": _to_float(analysis.get("duration_s")) or 0.0,
        "result": bool(analysis.get("kill")),
        "boss_percent": analysis.get("boss_remaining_pct"),
        "player": "Warcraft Logs 분석 전용",
        "player_guid": "",
        "deaths": _to_int(analysis.get("deaths")),
        "combatants": 20,
        "start": None,
        "start_local": start_dt.strftime("%Y-%m-%d %H:%M:%S") if start_dt else "",
        "video_exists": False,
        "video_remote": False,
        "video_size_mb": 0,
        "log_only": False,
        "analysis_only": True,
        "wcl_only": True,
        "analysis": analysis,
        "capabilities": {
            "frames": False,
            "terrain": False,
            "video": False,
            "analysis": True,
        },
        "_start_dt": start_dt,
        "_raw": {},
    }


def _wcl_only_caps(index: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    index = index or _lura_sync_index()
    return [_wcl_only_cap(row) for row in index.get("wcl_only") or []]


def _find_wcl_only_cap(replay_id: str) -> dict[str, Any] | None:
    return next(
        (cap for cap in _wcl_only_caps() if cap.get("id") == replay_id),
        None,
    )


def _load_captures(cctv_dir_arg: Path | None = None, limit: int = 80) -> list[dict[str, Any]]:
    cctv_dir_arg = cctv_dir_arg or cctv_dir()
    if not cctv_dir_arg.exists():
        return []
    paths = sorted(
        cctv_dir_arg.glob("*.json"),
        key=lambda p: p.stat().st_mtime_ns,
        reverse=True,
    )[:max(1, limit)]
    out: list[dict[str, Any]] = []
    for path in paths:
        try:
            data = _read_cctv_json(path)
        except ReplayError:
            continue
        video = _video_for_json(path)
        start_dt = _json_start_local(path, data)
        deaths = data.get("deaths") or []
        combatants = data.get("combatants") or []
        player = data.get("player") or {}
        out.append(_enrich_trial_cap({
            "id": _capture_id(path, data),
            "file": path.name,
            "encounter_id": _to_int(data.get("encounterID")),
            "encounter": _clean_name(data.get("encounterName")) or path.stem,
            "difficulty": _clean_name(data.get("difficulty")),
            "difficulty_id": _to_int(data.get("difficultyID")),
            "duration": _to_int(data.get("duration")),
            "result": bool(data.get("result")),
            "boss_percent": data.get("bossPercent"),
            "player": _clean_name(player.get("_name")),
            "player_guid": _clean_name(player.get("_GUID")),
            "deaths": len(deaths),
            "combatants": len(combatants),
            "start": _to_int(data.get("start"), 0) or None,
            "start_local": start_dt.strftime("%Y-%m-%d %H:%M:%S") if start_dt else "",
            "video_exists": video.exists(),
            "video_remote": (not video.exists()) and bool(_remote_video_name(path)),
            "video_size_mb": round(video.stat().st_size / 1024 / 1024, 1) if video.exists() else 0,
            "_json_path": path,
            "_video_path": video,
            "_start_dt": start_dt,
            "_raw": data,
        }))
    return out


@lru_cache(maxsize=4)
def _encounter_index_cached(path_str: str, mtime_ns: int, size: int) -> list[dict[str, Any]]:
    del mtime_ns, size
    path = Path(path_str)
    encounters: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        for line_no, line in enumerate(fh, 1):
            if "ENCOUNTER_" not in line:
                continue
            m = _LOG_LINE_RE.match(line.rstrip("\r\n"))
            if not m:
                continue
            ts = _parse_log_ts(m.group(1))
            row = _csv_row(m.group(2))
            if not ts or not row:
                continue
            event = row[0]
            if event == "ENCOUNTER_START" and len(row) >= 6:
                current = {
                    "encounter_id": _to_int(row[1]),
                    "encounter": _clean_name(row[2]),
                    "difficulty_id": _to_int(row[3]),
                    "group_size": _to_int(row[4]),
                    "zone_id": _to_int(row[5]),
                    "start_local": ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                    "start_line": line_no,
                    "_start_dt": ts,
                }
            elif event == "ENCOUNTER_END" and len(row) >= 7:
                if current and current.get("encounter_id") == _to_int(row[1]):
                    current.update({
                        "success": bool(_to_int(row[5])),
                        "duration_ms": _to_int(row[6]),
                        "duration": round(_to_int(row[6]) / 1000, 3),
                        "end_local": ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "end_line": line_no,
                        "_end_dt": ts,
                    })
                    encounters.append(current)
                    current = None
                else:
                    encounters.append({
                        "encounter_id": _to_int(row[1]),
                        "encounter": _clean_name(row[2]),
                        "difficulty_id": _to_int(row[3]),
                        "group_size": _to_int(row[4]),
                        "success": bool(_to_int(row[5])),
                        "duration_ms": _to_int(row[6]),
                        "duration": round(_to_int(row[6]) / 1000, 3),
                        "end_local": ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "end_line": line_no,
                        "_end_dt": ts,
                    })
    return encounters


def encounter_index(log_path: Path | None = None) -> list[dict[str, Any]]:
    path = log_path or latest_log_path()
    if not path or not path.exists():
        return []
    return _encounter_index_cached(*_file_sig(path))


def _public_encounter(enc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not enc:
        return None
    return {k: v for k, v in enc.items() if not k.startswith("_")}


def _match_capture(cap: dict[str, Any], encounters: list[dict[str, Any]]) -> dict[str, Any] | None:
    start = cap.get("_start_dt")
    if not start:
        return None
    cap_eid = cap.get("encounter_id")
    best: tuple[float, dict[str, Any]] | None = None
    for enc in encounters:
        enc_start = enc.get("_start_dt")
        if not enc_start:
            continue
        if cap_eid and enc.get("encounter_id") != cap_eid:
            continue
        delta = abs((enc_start - start).total_seconds())
        if best is None or delta < best[0]:
            best = (delta, enc)
    if best and best[0] <= 8:
        matched = dict(best[1])
        matched["match_delta_sec"] = round(best[0], 3)
        return matched
    return None


def list_replays(limit: int = 80) -> dict[str, Any]:
    log_path = latest_log_path()
    sync_index = _lura_sync_index()
    artifact_ids = sync_index.get("artifact_ids") or set()
    captures = _load_captures(limit=limit)
    # R2 미러 병합 — 로컬 캡처 폴더가 있어도 다른 PC가 올린 원격 캡처를 함께 노출.
    # ensure_mirror() 가 json(소형)만 동기화하고 전투로그는 백그라운드로 내려받는다.
    from app import cctv_sync
    if cctv_sync.available():
        local_root = cctv_dir()
        mirror_root = cctv_sync.ensure_mirror()
        if mirror_root != local_root:
            seen_files = {str(cap.get("file") or "") for cap in captures}
            for cap in _load_captures(mirror_root, limit=limit):
                if str(cap.get("file") or "") not in seen_files:
                    captures.append(cap)
            captures.sort(key=lambda c: c.get("_start_dt") or datetime.min, reverse=True)
            captures = captures[:max(1, limit)]
    log_paths = _standalone_log_paths()
    log_caps = _load_log_replay_caps(limit=max(limit, 1), paths=log_paths)
    try:
        encounters = list(_encounter_offsets(log_path)) if log_path else []
    except OSError:
        encounters = []
    rows = []
    for cap in captures:
        if cap.get("id") in artifact_ids:
            continue
        match = _match_capture(cap, encounters)
        row = _public_capture(cap)
        row["log_match"] = _public_encounter(match)
        rows.append(row)

    # CCTV 없이 전투로그만 받은 경우도 각 ENCOUNTER를 독립 리플레이로 노출한다.
    # 아카이브는 수십 GB일 수 있어 목록용으로 전수 스캔하지 않고,
    # 현재 Logs/및 간이 가져오기 폴더의 직접 로그만 대상으로 한다.
    for log_cap in log_caps:
        if log_cap.get("id") in artifact_ids:
            continue
        if any(_same_encounter(cap, log_cap) for cap in captures):
            continue
        row = _public_capture(log_cap)
        row["log_match"] = _public_encounter(log_cap.get("_log_encounter"))
        rows.append(row)

    rows.sort(key=lambda row: str(row.get("start_local") or ""), reverse=True)
    rows = rows[:max(1, limit)]
    coordinates_hidden = len(sync_index.get("wcl_only") or [])
    return {
        "sources": {
            "log_dir": str(wow_log_dir()),
            "cctv_dir": str(cctv_dir()),
            "log_file": str(log_path) if log_path else "",
            "log_files": len(log_paths),
            "encounters": len(log_caps),
            "log_only": sum(1 for row in rows if row.get("log_only")),
            "analysis_enriched": sum(1 for row in rows if row.get("analysis")),
            "analysis_replay": sum(
                1 for row in rows if row.get("analysis") and not row.get("analysis_only")
            ),
            # 좌표 없는 WCL-only 풀은 동기화 통계에는 남기되 리플레이 목록에는 노출하지 않는다.
            "wcl_only": coordinates_hidden,
            "coordinates_hidden": coordinates_hidden,
            "artifacts_hidden": len(artifact_ids),
            "wcl_session": sync_index.get("session") or {},
        },
        "rows": rows,
    }


def _find_capture(replay_id: str) -> dict[str, Any]:
    # log-/wcl- 네임스페이스는 id 접두사로 즉시 분기 — CCTV json 수백 개를 읽지 않는다.
    if replay_id.startswith("log-"):
        log_cap = _find_log_replay_cap(replay_id)
        if log_cap:
            return log_cap
        raise ReplayError(f"replay not found: {replay_id}")
    if replay_id.startswith("wcl-"):
        wcl_cap = _find_wcl_only_cap(replay_id)
        if wcl_cap:
            return wcl_cap
        raise ReplayError(f"replay not found: {replay_id}")
    for cap in _load_captures(limit=400):
        if cap.get("id") == replay_id:
            return cap
    # 로컬에 없으면 R2 미러 캡처(다른 PC가 올린 json)에서 탐색
    from app import cctv_sync
    if cctv_sync.available():
        mirror_root = cctv_sync.ensure_mirror()
        if mirror_root != cctv_dir():
            for cap in _load_captures(mirror_root, limit=400):
                if cap.get("id") == replay_id:
                    return cap
    raise ReplayError(f"replay not found: {replay_id}")


def _actor_name(row: list[str], guid: str) -> str:
    if len(row) > 2 and guid == row[1]:
        return _clean_name(row[2])
    if len(row) > 6 and guid == row[5]:
        return _clean_name(row[6])
    return ""


def _advanced_position(row: list[str]) -> dict[str, Any] | None:
    if len(row) < 31:
        return None
    guid = row[12]
    x = _to_float(row[26])
    y = _to_float(row[27])
    if not guid or guid == "0000000000000000" or x is None or y is None:
        return None
    return {
        "guid": guid,
        "name": _actor_name(row, guid),
        "x": x,
        "y": y,
        "map": _to_int(row[28]),
        "facing": _to_float(row[29]),
        "level": _to_int(row[30]),
    }


def _base_event(row: list[str], ts: datetime, video_start: datetime) -> dict[str, Any]:
    event = row[0]
    t = round((ts - video_start).total_seconds(), 3)
    item: dict[str, Any] = {
        "t": t,
        "event": event,
        "source": _clean_name(row[2]) if len(row) > 2 else "",
        "target": _clean_name(row[6]) if len(row) > 6 else "",
    }
    if len(row) > 10:
        item.update({
            "spell_id": _to_int(row[9]),
            "spell": _clean_name(row[10]),
        })
    return item


def _add_actor(actors: dict[str, dict[str, Any]], guid: str, name: str) -> None:
    if not guid or guid == "0000000000000000":
        return
    if guid not in actors:
        actors[guid] = {"guid": guid, "name": name}
    elif name and not actors[guid].get("name"):
        actors[guid]["name"] = name


def _parse_log_window(
    log_path: Path,
    start_dt: datetime,
    end_dt: datetime,
    video_start: datetime,
    actors: dict[str, dict[str, Any]],
    start_line: int | None = None,
    end_line: int | None = None,
    max_events: int = 3000,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    counts = {"casts": 0, "debuffs": 0, "damage": 0, "deaths": 0, "positions": 0, "skipped": 0}
    last_pos: dict[str, float] = {}
    damage_threshold = 250_000

    with log_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        for line_no, line in enumerate(fh, 1):
            if start_line and line_no < start_line:
                continue
            if end_line and line_no > end_line:
                break
            m = _LOG_LINE_RE.match(line.rstrip("\r\n"))
            if not m:
                continue
            ts = _parse_log_ts(m.group(1))
            if not ts:
                continue
            if ts < start_dt:
                continue
            if ts > end_dt:
                break

            row = _csv_row(m.group(2))
            if not row:
                continue
            event = row[0]
            if len(row) > 2:
                _add_actor(actors, row[1], _clean_name(row[2]))
            if len(row) > 6:
                _add_actor(actors, row[5], _clean_name(row[6]))

            video_t = round((ts - video_start).total_seconds(), 3)
            pos = _advanced_position(row)
            if pos:
                last = last_pos.get(pos["guid"], -9999)
                if video_t - last >= 0.35:
                    pos["t"] = video_t
                    positions.append(pos)
                    counts["positions"] += 1
                    last_pos[pos["guid"]] = video_t
                    if pos["guid"] in actors:
                        actors[pos["guid"]].update({"map": pos["map"], "level": pos["level"]})

            item: dict[str, Any] | None = None
            if event in ("SPELL_CAST_START", "SPELL_CAST_SUCCESS") and len(row) > 10:
                counts["casts"] += 1
                item = _base_event(row, ts, video_start)
                item["kind"] = "cast"
            elif event in ("SPELL_AURA_APPLIED", "SPELL_AURA_REMOVED", "SPELL_AURA_REFRESH") and len(row) > 12:
                if row[12] == "DEBUFF" and len(row) > 5 and str(row[5]).startswith("Player-"):
                    counts["debuffs"] += 1
                    item = _base_event(row, ts, video_start)
                    item["kind"] = "debuff"
                    item["aura"] = row[12]
            elif event in ("SPELL_DAMAGE", "SPELL_PERIODIC_DAMAGE", "RANGE_DAMAGE") and len(row) > 31:
                amount = _to_int(row[31])
                if amount >= damage_threshold and len(row) > 5 and str(row[5]).startswith("Player-"):
                    counts["damage"] += 1
                    item = _base_event(row, ts, video_start)
                    item["kind"] = "damage"
                    item["amount"] = amount
            elif event == "UNIT_DIED" and len(row) > 6 and str(row[5]).startswith("Player-"):
                # 마지막 필드 unconsciousOnDeath=1 → 죽은척(사냥꾼 등), 실제 사망 아님
                if str(row[-1]).strip() != "1":
                    counts["deaths"] += 1
                    item = _base_event(row, ts, video_start)
                    item["kind"] = "death"

            if item:
                if len(events) < max_events:
                    events.append(item)
                else:
                    counts["skipped"] += 1

    return {"events": events, "positions": positions, "counts": counts}


def _replay_positions(positions: list[dict[str, Any]], encounter_name: str) -> list[dict[str, Any]]:
    if not positions:
        return []
    dominant = Counter(p.get("map") for p in positions if p.get("map")).most_common(1)
    dominant_map = dominant[0][0] if dominant else None
    boss_token = (encounter_name or "").split()[-1].strip()
    filtered = []
    for pos in positions:
        guid = str(pos.get("guid") or "")
        name = str(pos.get("name") or "")
        if dominant_map and pos.get("map") != dominant_map:
            continue
        if guid.startswith("Player-") or (boss_token and boss_token in name):
            filtered.append(pos)
    return filtered


def _bounds(positions: list[dict[str, Any]]) -> dict[str, float] | None:
    if not positions:
        return None
    xs = [p["x"] for p in positions]
    ys = [p["y"] for p in positions]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    pad = max(max(max_x - min_x, max_y - min_y) * 0.08, 8)
    return {
        "min_x": round(min_x - pad, 2),
        "max_x": round(max_x + pad, 2),
        "min_y": round(min_y - pad, 2),
        "max_y": round(max_y + pad, 2),
    }


def replay_detail(replay_id: str) -> dict[str, Any]:
    cap = _find_capture(replay_id)
    if cap.get("analysis_only"):
        return _analysis_only_replay_detail(cap)
    if cap.get("log_only"):
        log_path, match = _find_frames_encounter(cap)
        return _log_only_replay_detail(cap, log_path, match)
    else:
        log_path = latest_log_path()
        encounters = encounter_index(log_path) if log_path else []
        match = _match_capture(cap, encounters)
    actors: dict[str, dict[str, Any]] = {}
    raw = cap.get("_raw") or {}
    for unit in raw.get("combatants") or []:
        guid = _clean_name(unit.get("_GUID"))
        _add_actor(actors, guid, _clean_name(unit.get("_name")))
        if guid:
            actors[guid].update({
                "spec_id": _to_int(unit.get("_specID")),
                "team_id": _to_int(unit.get("_teamID")),
                "realm": _clean_name(unit.get("_realm")),
            })

    video_start = cap.get("_start_dt")
    if not video_start:
        raise ReplayError("capture start time missing")

    if match and match.get("_start_dt"):
        start_dt = match["_start_dt"]
        end_dt = match.get("_end_dt") or (start_dt + timedelta(seconds=cap.get("duration") or 0))
    else:
        start_dt = video_start
        end_dt = video_start + timedelta(seconds=(cap.get("duration") or 0) + 5)

    parsed = {"events": [], "positions": [], "counts": {}}
    if log_path and log_path.exists():
        parsed = _parse_log_window(
            log_path,
            start_dt,
            end_dt,
            video_start,
            actors,
            start_line=_to_int(match.get("start_line")) if match else None,
            end_line=_to_int(match.get("end_line")) if match else None,
        )

    death_events = []
    for death in raw.get("deaths") or []:
        t = _to_float(death.get("timestamp"))
        if t is None:
            continue
        death_events.append({
            "t": round(t, 3),
            "kind": "death",
            "event": "CCTV_DEATH",
            "source": "",
            "target": _clean_name(death.get("name")),
            "spell": "death",
            "friendly": bool(death.get("friendly")),
            "spec_id": _to_int(death.get("specId")),
        })

    events = parsed["events"] + death_events
    events.sort(key=lambda item: item.get("t", 0))

    duration = max(
        cap.get("duration") or 0,
        round((end_dt - video_start).total_seconds(), 3),
        max((e.get("t", 0) for e in events), default=0),
    )
    public_cap = _public_capture(cap)
    public_cap["log_match"] = _public_encounter(match)
    replay_positions = _replay_positions(parsed["positions"], public_cap.get("encounter") or "")
    visible_guids = {p.get("guid") for p in replay_positions}
    visible_actors = [
        actor for actor in actors.values()
        if str(actor.get("guid") or "").startswith("Player-") or actor.get("guid") in visible_guids
    ]
    parsed["counts"]["positions"] = len(replay_positions)

    return {
        "capture": public_cap,
        "encounter": _public_encounter(match),
        "duration": round(duration, 3),
        "events": events,
        "positions": replay_positions,
        "bounds": _bounds(replay_positions),
        "actors": visible_actors,
        "counts": parsed["counts"],
        "analysis": cap.get("analysis"),
        "sources": {
            "log_file": str(log_path) if log_path else "",
            "json_file": str(cap.get("_json_path") or ""),
            "video_file": str(cap.get("_video_path")) if cap.get("video_exists") else "",
        },
        "video": {
            "available": bool(cap.get("video_exists")) or bool(cap.get("video_remote")),
            "url": (f"/api/local-replay/video/{replay_id}" if cap.get("video_exists")
                    else (f"/api/local-replay/video-remote/{replay_id}" if cap.get("video_remote") else "")),
            "remote": bool(cap.get("video_remote")) and not cap.get("video_exists"),
        },
    }


def replay_video_remote_url(replay_id: str) -> str:
    """로컬에 영상이 없는 캡처의 R2 presigned 스트리밍 URL."""
    cap = _find_capture(replay_id)
    json_path = cap.get("_json_path")
    if not isinstance(json_path, Path):
        raise ReplayError(f"capture json not found: {replay_id}")
    name = _remote_video_name(json_path)
    if not name:
        raise ReplayError(f"remote video not found: {replay_id}")
    from app import cctv_sync
    url = cctv_sync.presign(name)
    if not url:
        raise ReplayError("presign 실패 — rclone 설정 확인")
    return url


def replay_video_path(replay_id: str) -> Path:
    cap = _find_capture(replay_id)
    video = cap.get("_video_path")
    if not isinstance(video, Path) or not video.exists():
        raise ReplayError(f"video not found: {replay_id}")
    return video


# ═══════════════════════════════════════════════════════════════════════════
# 맵 리플레이 프레임 — GET /api/replay/{replay_id}/frames 백엔드
# (REPLAY3D_PLAN.md MVP: 아카이브 로그 + 바이트오프셋 seek + 0.5초 다운샘플)
# ═══════════════════════════════════════════════════════════════════════════

ARCHIVE_DIR_NAME = "warcraftlogsarchive"
FRAME_STEP = 0.5          # 다운샘플 그리드 (초)
NPC_MAX = 40              # 보스 외 npc(적대 Creature/Vehicle)는 샘플 많은 순 상위 N 만
NPC_MIN_SAMPLES = 10      # 이보다 샘플 적은 npc 는 제외
CASTS_UNIT_CAP = 2000     # casts: 유닛당 시전 상한 (초과 시 앞부분 버림)
CASTS_NPC_CAP = 200       # casts: 쫄몹(npc)은 낮은 상한 — 페이로드 억제

# 플레이어 이벤트 (frames 응답 player_events)
PLAYER_EVENT_TOTAL_CAP = 5000   # 총 상한 — 초과 시 쿨다운 폴백류부터 컷
_FALLBACK_CD_MIN = 180.0        # 분류표 밖 스킬: 쿨다운 >= 이 값이면 offensive 폴백
_BLOODLUST_IDS = frozenset({
    2825, 32182,                # 피의 욕망 / 영웅심 (주술사)
    80353,                      # 시간 왜곡 (마법사)
    264667, 272678,             # 원초적 분노 (사냥꾼 펫 — 시전자가 Pet- guid)
    390386,                     # 위상의 격노 (기원사)
    466904,                     # 쇠황조롱이의 울음 (사냥꾼)
    178207, 230935, 256740, 309658, 444257,  # 북(드럼) 계열
})
# 전투부활 — 분류표에 없고 쿨다운이 길어 offensive 폴백에 걸리므로 별도 kind
_BREZ_IDS = frozenset({
    20484,   # 소생 (드루이드)
    61999,   # 아군 되살리기 (죽음의 기사)
    391054,  # 중재 (성기사)
    20707,   # 영혼석 되살리기 (흑마법사)
    212048,  # 조상의 시야 (주술사)
})
# player_spell_types.json 타입 → player_events kind. 여기 없는 타입(CC/Utility/
# Minor DPS CD 등)은 제외하되 '분류표에 있음'으로 취급해 쿨다운 폴백도 막는다.
_SPELL_TYPE_KIND = {
    "Potions": "potion",
    "Healthpots": "healthpot",
    "DPS CD": "offensive",
    "Defensives": "defensive",
    "Immunities": "defensive",
    "Externals": "defensive",
    "Raid DR": "defensive",
    "Utility": "utility",     # 유닛 패널 색상 분류용 (피드 기본 OFF)
}

# 고급 파라미터가 붙는 이벤트 (플랜 §2-2). SWING 계열은 spell prefix 3필드가
# 없어서 고급 블록 시작 인덱스가 12 가 아니라 9 — 좌표 인덱스도 3 앞당겨짐.
_ADV_SPELL_EVENTS = {
    "SPELL_CAST_SUCCESS", "SPELL_DAMAGE", "SPELL_PERIODIC_DAMAGE",
    "SPELL_HEAL", "SPELL_PERIODIC_HEAL", "SPELL_ENERGIZE",
    "SPELL_PERIODIC_ENERGIZE", "RANGE_DAMAGE", "SPELL_DRAIN", "SPELL_LEECH",
    "DAMAGE_SPLIT", "DAMAGE_SHIELD",
}
_ADV_SWING_EVENTS = {"SWING_DAMAGE", "SWING_DAMAGE_LANDED"}

# 보스 기믹 이벤트 (frames 응답 boss_events)
_HOSTILE_FLAG = 0x40          # sourceFlags REACTION_HOSTILE — 아군 소환수 제외 핵심
BOSS_EVENT_TOTAL_CAP = 600    # 풀당 전체 캡
BOSS_EVENT_MIN_KEEP = 12      # 전체 캡 컷 시 스펠별 최소 보장 — 후반부 저빈도
                              # 기믹(P3 한밤 등)이 고빈도 스펠에 밀려 전멸하는 것 방지
BOSS_EVENT_SPELL_CAP = 20     # 캐스트류 스펠별 캡 (초과 시 균등 샘플)
BOSS_EVENT_HIT_CAP = 120      # 디버프(hit) 스펠별 캡 — 20이면 뒤쪽 웨이브가 통째로
                              # 샘플에서 탈락해 '나중에 걸린 사람 하이라이트 안 됨' 버그
BOSS_HIT_MAX_APPLIED = 15     # 플레이어 디버프: 풀당 웨이브 수 이 이하만 (스팸 컷)
BOSS_HIT_WAVE_GAP_S = 3.0     # 디버프 '같은 웨이브' 판정 간격 (다중 대상 동시 적용 묶음)

# 르우라 집중 관찰 구간. 일부 실제 피해 child ID는 공용 기믹 카탈로그의
# canonical ID에 아직 연결되지 않아, 리플레이 피격 링에서도 빠지지 않게 보강한다.
_LURA_REVIEW_TRACKED_IDS = frozenset({
    1249582, 1249584, 1249585, 1249609, 1255743,
    1263514,   # 한밤 — P3 보호 범위 밖 중첩 디버프 (WCL 사망 원인 Midnight)
    1279512, 1279581, 1281123, 1281178, 1281184, 1281473,
    1282043, 1282469, 1282470, 1284528, 1285510, 1285708,
})
_LURA_CRYSTAL_NAME = "여명의 수정"

# specID → 클래스 토큰 (COMBATANT_INFO 에서 플레이어 직업색 얻기용)
_SPEC_CLASS = {
    62: "mage", 63: "mage", 64: "mage",
    65: "paladin", 66: "paladin", 70: "paladin",
    71: "warrior", 72: "warrior", 73: "warrior",
    102: "druid", 103: "druid", 104: "druid", 105: "druid",
    250: "deathknight", 251: "deathknight", 252: "deathknight",
    253: "hunter", 254: "hunter", 255: "hunter",
    256: "priest", 257: "priest", 258: "priest",
    259: "rogue", 260: "rogue", 261: "rogue",
    262: "shaman", 263: "shaman", 264: "shaman",
    265: "warlock", 266: "warlock", 267: "warlock",
    268: "monk", 269: "monk", 270: "monk",
    577: "demonhunter", 581: "demonhunter",
    1467: "evoker", 1468: "evoker", 1473: "evoker",
}

_SPEC_ROLE = {
    65: "healer", 66: "tank", 70: "damage",
    71: "damage", 72: "damage", 73: "tank",
    250: "tank", 251: "damage", 252: "damage",
    253: "damage", 254: "damage", 255: "damage",
    256: "healer", 257: "healer", 258: "damage",
    259: "damage", 260: "damage", 261: "damage",
    62: "damage", 63: "damage", 64: "damage",
    102: "damage", 103: "damage", 104: "tank", 105: "healer",
    268: "tank", 269: "damage", 270: "healer",
    577: "damage", 581: "tank",
    265: "damage", 266: "damage", 267: "damage",
    262: "damage", 263: "damage", 264: "healer",
    1467: "damage", 1468: "healer", 1473: "damage", 1480: "damage",
}


def _adv_position_any(row: list[str]) -> tuple[str, float, float, int, float | None, int | None] | None:
    """이벤트 종류별 고급 좌표 추출 → (guid, x, y, uiMapID, facing, hp%).

    기존 _advanced_position() 은 인덱스 26 고정이라 SWING 좌표를 버렸음 —
    여기서는 이벤트에 따라 오프셋을 맞춰 밀도를 살린다.
    hp% 는 같은 고급 블록의 currentHP/maxHP(off+2, off+3) → 0~100 정수,
    못 구하면 None.
    """
    event = row[0]
    if event in _ADV_SWING_EVENTS:
        off = 9        # 고급 블록 시작 (spell prefix 없음)
    elif event in _ADV_SPELL_EVENTS:
        off = 12
    else:
        return None
    if len(row) <= off + 17:
        return None
    guid = row[off]
    if not guid or guid == "0000000000000000" or "-" not in guid:
        return None
    x = _to_float(row[off + 14])
    y = _to_float(row[off + 15])
    if x is None or y is None:
        return None
    cur_hp = _to_float(row[off + 2])
    max_hp = _to_float(row[off + 3])
    hp: int | None = None
    if cur_hp is not None and max_hp is not None and max_hp > 0:
        hp = max(0, min(100, round(cur_hp / max_hp * 100)))
    return guid, x, y, _to_int(row[off + 16]), _to_float(row[off + 17]), hp


def _combatant_spec(row: list[str]) -> tuple[str, int] | None:
    """COMBATANT_INFO → (guid, specID). specID 는 탤런트 배열 '[( ' 직전 필드."""
    if len(row) < 4 or not str(row[1]).startswith("Player-"):
        return None
    for i, field in enumerate(row):
        if isinstance(field, str) and field.startswith("["):
            spec = _to_int(row[i - 1]) if i >= 1 else 0
            return row[1], spec
    return None


def _filename_log_start(path: Path) -> datetime | None:
    """WoWCombatLog-MMDDYY_HHMMSS.txt 파일명에서 로그 시작 시각."""
    m = re.search(r"WoWCombatLog-(\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", path.name)
    if not m:
        return None
    mo, d, y, h, mi, s = map(int, m.groups())
    try:
        return datetime(2000 + y, mo, d, h, mi, s)
    except ValueError:
        return None


def _candidate_logs(cap_start: datetime, log_dir: Path | None = None) -> list[Path]:
    """캡처 시각을 포함할 수 있는 로그 파일들 (현재 + 아카이브 + R2 미러).

    파일명 시각 <= 캡처 시각 <= mtime 인 파일만 후보 — 1GB 아카이브 전수
    인덱싱을 피하는 1차 필터. 시작 시각이 캡처에 가장 가까운 파일부터 시도.
    """
    log_dir = log_dir or wow_log_dir()
    cands: list[tuple[datetime, Path]] = []
    dirs = [log_dir, log_dir / ARCHIVE_DIR_NAME]
    # 로컬 WoW Logs 에 해당 판 로그가 없어도 R2 미러(cctv_sync)가 받아둔 로그를 후보에 포함
    from app import cctv_sync
    if cctv_sync.mirror_log_dir() != log_dir:
        dirs.append(cctv_sync.mirror_log_dir())
    # 캡처 폴더(cctvlog 간이 루트)에 로그를 같이 두는 경우도 후보에 포함
    cdir = cctv_dir()
    if cdir not in dirs:
        dirs.append(cdir)
    for d in dirs:
        if not d.exists():
            continue
        for p in d.glob("*WoWCombatLog-*.txt"):
            file_start = _filename_log_start(p)
            if not file_start:
                continue
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            # 복사/R2 동기화된 파일은 mtime 이 '기록 종료 시각'이라는 가정이 깨짐
            # (mtime < 파일 시작 시각인 경우) — 그때는 상한을 24시간으로 완화.
            end_guess = mtime if mtime >= file_start else file_start + timedelta(hours=24)
            if file_start - timedelta(minutes=2) <= cap_start <= end_guess + timedelta(minutes=2):
                cands.append((file_start, p))
    cands.sort(key=lambda t: t[0], reverse=True)
    return [p for _, p in cands]


def _apply_encounter_line(
    raw: bytes,
    line_off: int,
    line_end: int,
    encounters: list[dict[str, Any]],
    current: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """한 줄에서 ENCOUNTER_START/END 를 파싱해 encounters 갱신, 새 current 반환."""
    if b"ENCOUNTER_" not in raw:
        return current
    # utf-8-sig: 파일 첫 줄 BOM 제거용
    m = _LOG_LINE_RE.match(raw.decode("utf-8-sig", errors="replace").rstrip("\r\n"))
    if not m:
        return current
    ts = _parse_log_ts(m.group(1))
    row = _csv_row(m.group(2))
    if not ts or not row:
        return current
    if row[0] == "ENCOUNTER_START" and len(row) >= 6:
        return {
            "encounter_id": _to_int(row[1]),
            "encounter": _clean_name(row[2]),
            "difficulty_id": _to_int(row[3]),
            "group_size": _to_int(row[4]),
            "instance_id": _to_int(row[5]),  # Map.db2 ID — 지형(replay_terrain) 체인 시작점
            "start_off": line_off,
            "_start_dt": ts,
        }
    if row[0] == "ENCOUNTER_END" and len(row) >= 7:
        if current and current.get("encounter_id") == _to_int(row[1]):
            current.update({
                "success": bool(_to_int(row[5])),
                "duration_s": round(_to_int(row[6]) / 1000, 3),
                "end_off": line_end,   # END 줄 끝까지 포함
                "_end_dt": ts,
            })
            encounters.append(current)
        return None
    return current


@lru_cache(maxsize=8)
def _encounter_offsets_cached(path_str: str, mtime_ns: int, size: int) -> tuple[dict[str, Any], ...]:
    """아카이브(불변) 로그: ENCOUNTER_START/END 만 바이트 오프셋과 함께 전체 스캔.

    바이너리 모드 줄 순회 + 'ENCOUNTER_' 프리필터라 1.2GB 아카이브도 수 초.
    이후 프레임 추출은 start_off 로 fh.seek() — 파일 앞부분을 다시 안 읽음.
    """
    del mtime_ns, size
    path = Path(path_str)
    encounters: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    offset = 0
    with path.open("rb") as fh:
        for raw in fh:
            line_off = offset
            offset += len(raw)
            current = _apply_encounter_line(raw, line_off, offset, encounters, current)
    return tuple(encounters)


# 활성 로그(계속 자라는 파일) 증분 인덱스: path → 스캔 상태.
# lru 캐시는 (path,mtime,size) 키라 파일이 자라는 동안 매번 전체 재스캔이라
# 여기선 마지막 오프셋부터 이어서 읽는다.
_ACTIVE_ENC_INDEX: dict[str, dict[str, Any]] = {}
_ACTIVE_ENC_LOCK = threading.RLock()


def _encounter_offsets_active(path: Path) -> tuple[dict[str, Any], ...]:
    """활성 로그: 마지막 스캔 지점부터 이어 스캔 (파일이 줄어들면 처음부터)."""
    with _ACTIVE_ENC_LOCK:
        key = str(path)
        size = path.stat().st_size
        state = _ACTIVE_ENC_INDEX.get(key)
        if state is None or size < state["scanned_size"]:
            # 처음 보는 파일이거나 파일이 줄어듦(교체/롤오버) → 리셋
            state = {"scanned_size": 0, "encounters": [], "current": None}
            _ACTIVE_ENC_INDEX[key] = state
        if size > state["scanned_size"]:
            encounters = state["encounters"]
            current = state["current"]
            offset = state["scanned_size"]
            with path.open("rb") as fh:
                fh.seek(offset)
                for raw in fh:
                    if not raw.endswith(b"\n"):
                        break  # 쓰다 만 마지막 줄 — 다음 요청 때 이어서 읽음
                    line_off = offset
                    offset += len(raw)
                    current = _apply_encounter_line(raw, line_off, offset, encounters, current)
            state["scanned_size"] = offset
            state["current"] = current
        return tuple(state["encounters"])


def _encounter_offsets(path: Path) -> tuple[dict[str, Any], ...]:
    """아카이브는 불변이라 lru 캐시, 그 외(활성 가능)는 증분 인덱스."""
    if path.parent.name == ARCHIVE_DIR_NAME:
        return _encounter_offsets_cached(*_file_sig(path))
    return _encounter_offsets_active(path)


_DIFFICULTY_LABELS = {
    1: "일반",
    2: "영웅",
    8: "신화 쐐기",
    14: "일반 공격대",
    15: "영웅 공격대",
    16: "신화 공격대",
    17: "공격대 찾기",
    23: "신화 던전",
}


def _difficulty_label(difficulty_id: int) -> str:
    return _DIFFICULTY_LABELS.get(difficulty_id, f"난이도 {difficulty_id}" if difficulty_id else "")


def _standalone_log_paths(log_dir: Path | None = None) -> list[Path]:
    """CCTV 없이 목록화할 직접 전투로그.

    일반 WoW Logs 폴더와 간이 가져오기/R2 미러 루트를 본다.
    warcraftlogsarchive는 수십 GB일 수 있으므로 목록 전수 스캔에서 제외한다.
    기존 CCTV 캡처의 아카이브 매칭은 _candidate_logs() 경로를 계속 사용한다.
    """
    roots: list[Path] = [log_dir or wow_log_dir(), cctv_dir()]
    from app import cctv_sync
    roots.append(cctv_sync.mirror_log_dir())

    found: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("*WoWCombatLog-*.txt"):
            try:
                key = str(path.resolve()).casefold()
            except OSError:
                key = str(path.absolute()).casefold()
            found.setdefault(key, path)

    def sort_key(path: Path) -> tuple[datetime, int]:
        started = _filename_log_start(path) or datetime.min
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = 0
        return started, mtime

    return sorted(found.values(), key=sort_key, reverse=True)


def _log_path_hash(path: Path) -> str:
    try:
        normalized = str(path.resolve()).casefold()
    except OSError:
        normalized = str(path.absolute()).casefold()
    return hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _log_replay_id(path: Path, enc: dict[str, Any]) -> str:
    return f"log-{_log_path_hash(path)}-{_to_int(enc.get('start_off')):x}"


def _log_replay_cap(path: Path, enc: dict[str, Any]) -> dict[str, Any]:
    start_dt = enc.get("_start_dt")
    duration = round(float(enc.get("duration_s") or 0), 3)
    return _enrich_trial_cap({
        "id": _log_replay_id(path, enc),
        "file": path.name,
        "encounter_id": _to_int(enc.get("encounter_id")),
        "encounter": _clean_name(enc.get("encounter")) or path.stem,
        "difficulty": _difficulty_label(_to_int(enc.get("difficulty_id"))),
        "difficulty_id": _to_int(enc.get("difficulty_id")),
        "duration": duration,
        "result": bool(enc.get("success")),
        "boss_percent": None,
        "player": "전투로그 전용",
        "player_guid": "",
        "deaths": 0,
        "combatants": _to_int(enc.get("group_size")),
        "start": None,
        "start_local": start_dt.strftime("%Y-%m-%d %H:%M:%S") if start_dt else "",
        "video_exists": False,
        "video_remote": False,
        "video_size_mb": 0,
        "log_only": True,
        "_start_dt": start_dt,
        "_log_path": path,
        "_log_encounter": enc,
        "_raw": {},
    })


def _load_log_replay_caps(
    limit: int = 80,
    paths: list[Path] | None = None,
) -> list[dict[str, Any]]:
    caps: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for path in paths if paths is not None else _standalone_log_paths():
        try:
            encounters = _encounter_offsets(path)
        except OSError:
            continue
        for enc in encounters:
            cap = _log_replay_cap(path, enc)
            key = _log_replay_dedupe_key(cap)
            if key in seen:
                continue
            seen.add(key)
            caps.append(cap)
    caps.sort(key=lambda cap: cap.get("_start_dt") or datetime.min, reverse=True)
    return caps[:max(1, limit)]


def _find_log_replay_cap(replay_id: str) -> dict[str, Any] | None:
    match = re.fullmatch(r"log-([0-9a-f]{12})-([0-9a-f]+)", replay_id or "")
    if not match:
        return None
    path_hash, start_hex = match.groups()
    start_off = int(start_hex, 16)
    for path in _standalone_log_paths():
        if _log_path_hash(path) != path_hash:
            continue
        try:
            encounters = _encounter_offsets(path)
        except OSError:
            return None
        for enc in encounters:
            if _to_int(enc.get("start_off")) == start_off:
                return _log_replay_cap(path, enc)
        return None
    return None


def _same_encounter(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_start = left.get("_start_dt")
    right_start = right.get("_start_dt")
    if not isinstance(left_start, datetime) or not isinstance(right_start, datetime):
        return False
    left_id = _to_int(left.get("encounter_id"))
    right_id = _to_int(right.get("encounter_id"))
    return (not left_id or not right_id or left_id == right_id) and abs(
        (left_start - right_start).total_seconds()) <= 8


def _log_replay_dedupe_key(cap: dict[str, Any]) -> tuple[Any, ...]:
    """경로만 다른 동일 로그 복제본 키. 빠른 재풀은 시작 시각이 달라 보존한다."""
    return (
        cap.get("_start_dt"),
        _to_int(cap.get("encounter_id")),
        _to_int(cap.get("difficulty_id")),
        _to_int(cap.get("combatants")),
        round(float(cap.get("duration") or 0), 3),
        bool(cap.get("result")),
    )


def _find_frames_encounter(cap: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """캡처 ↔ 로그 전투 매칭 (encounterID 일치 + 시작 시각 8초 이내)."""
    direct_path = cap.get("_log_path")
    direct_enc = cap.get("_log_encounter")
    if isinstance(direct_path, Path) and isinstance(direct_enc, dict):
        if not direct_path.exists():
            raise ReplayError(f"combat log not found: {direct_path}")
        return direct_path, direct_enc

    cap_start = cap.get("_start_dt")
    if not cap_start:
        raise ReplayError("capture start time missing")
    cap_eid = cap.get("encounter_id")
    for log_path in _candidate_logs(cap_start):
        best: tuple[float, dict[str, Any]] | None = None
        for enc in _encounter_offsets(log_path):
            if cap_eid and enc.get("encounter_id") != cap_eid:
                continue
            delta = abs((enc["_start_dt"] - cap_start).total_seconds())
            if best is None or delta < best[0]:
                best = (delta, enc)
        if best and best[0] <= 8:
            return log_path, best[1]
    raise ReplayError(
        f"log encounter not found for capture (encounterID={cap_eid}, "
        f"start={cap_start}) — 현재/아카이브 로그에 매칭 전투 없음")


def _stream_frames_window(
    log_path: Path,
    start_off: int,
    end_off: int,
    start_dt: datetime,
    end_dt: datetime,
) -> dict[str, Any]:
    """전투 구간만 seek 해서 좌표/이름/스펙/죽음을 스트리밍 수집 (전량 메모리 적재 없음)."""
    samples: dict[str, list[tuple[float, float, float, float | None, int | None]]] = {}
    names: dict[str, str] = {}
    specs: dict[str, int] = {}
    deaths: list[tuple[float, str]] = []
    map_counts: Counter = Counter()
    activity_counts: Counter = Counter()
    # 시전 성공: guid → [(t, 스킬이름), ...] (다운샘플 없음 — 유닛 선별은 호출부에서)
    casts: dict[str, list[tuple[float, str]]] = {}
    # 보스 기믹 후보: (t, event, spell_id, spell, src_guid, src_name, dest_guid, dest_name)
    boss_raw: list[tuple[float, str, int, str, str, str, str, str]] = []
    # 플레이어 디버프 변화: 적용/중첩/갱신/해제를 모두 보존해 지속시간과 중첩을 재구성한다.
    aura_updates: list[tuple[float, str, int, str, str, int]] = []
    # 플레이어 이벤트 후보: (t, kind, src_guid, spell_id, spell, dest_guid, dest_name, 폴백여부)
    player_raw: list[tuple[float, str, str, int, str, str, str, bool]] = []
    spell_kinds = _player_spell_kinds()
    long_cds = _long_cooldown_ids()
    # 적대(REACTION_HOSTILE) 판정된 Creature/Vehicle guid — npc 트랙 선별용
    hostile: set[str] = set()
    boss_track_events = frozenset({
        "SPELL_CAST_START", "SPELL_CAST_SUCCESS", "SPELL_AURA_APPLIED",
        "SPELL_DAMAGE", "SPELL_PERIODIC_DAMAGE", "RANGE_DAMAGE",
        "SPELL_MISSED", "SPELL_ABSORBED", "SPELL_SUMMON",
    })

    with log_path.open("rb") as fh:
        fh.seek(start_off)
        pos = start_off
        for raw in fh:
            line_off = pos
            pos += len(raw)
            if end_off and line_off >= end_off:
                break
            m = _LOG_LINE_RE.match(raw.decode("utf-8-sig", errors="replace").rstrip("\r\n"))
            if not m:
                continue
            ts = _parse_log_ts(m.group(1))
            if not ts:
                continue
            if ts > end_dt:
                break
            row = _csv_row(m.group(2))
            if not row:
                continue
            event = row[0]
            t = (ts - start_dt).total_seconds()

            # 상세 셸은 즉시 반환하므로 하단 요약도 이 스트리밍 1회에서 함께 센다.
            # 기존 CCTV 상세와 같은 기준을 유지한다.
            if event in ("SPELL_CAST_START", "SPELL_CAST_SUCCESS") and len(row) > 10:
                activity_counts["casts"] += 1
            elif (event in ("SPELL_AURA_APPLIED", "SPELL_AURA_REMOVED", "SPELL_AURA_REFRESH")
                  and len(row) > 12 and row[12] == "DEBUFF"
                  and str(row[5]).startswith("Player-")):
                activity_counts["debuffs"] += 1
            elif (event in ("SPELL_DAMAGE", "SPELL_PERIODIC_DAMAGE", "RANGE_DAMAGE")
                  and len(row) > 31 and _to_int(row[31]) >= 250_000
                  and str(row[5]).startswith("Player-")):
                activity_counts["damage"] += 1
            elif (event == "UNIT_DIED" and len(row) > 6
                  and str(row[5]).startswith("Player-")
                  and str(row[-1]).strip() != "1"):
                activity_counts["deaths"] += 1

            if event == "COMBATANT_INFO":
                got = _combatant_spec(row)
                if got:
                    specs[got[0]] = got[1]
                continue
            if event == "UNIT_DIED" and len(row) > 6:
                # 마지막 필드 unconsciousOnDeath=1 → 죽은척(사냥꾼 등), 실제 사망 아님
                if str(row[-1]).strip() == "1":
                    continue
                guid = row[5]
                if guid and guid != "0000000000000000":
                    deaths.append((round(max(t, 0.0), 2), guid))
                    if _clean_name(row[6]):
                        names.setdefault(guid, _clean_name(row[6]))
                continue

            if (event == "SPELL_CAST_SUCCESS" and len(row) > 10
                    and str(row[1]).startswith(("Player-", "Creature-", "Vehicle-"))):
                # 유닛별 시전 타임라인 — meta.units 에 오를 수 있는 guid 만 수집,
                # 최종 필터(펫 등 제외)는 replay_frames 에서 unit id 매핑으로.
                spell_name = _clean_name(row[10])
                if spell_name:
                    casts.setdefault(row[1], []).append(
                        (round(max(t, 0.0), 2), spell_name))
                if str(row[1]).startswith("Player-"):
                    # 플레이어 이벤트 후보 (블러드/물약/오펜시브/생존기)
                    sid = _to_int(row[9])
                    kind, fb = _player_event_kind(sid, spell_name, spell_kinds, long_cds)
                    if kind:
                        player_raw.append((
                            round(max(t, 0.0), 2), kind, row[1], sid, spell_name,
                            str(row[5]) if len(row) > 5 else "",
                            _clean_name(row[6]) if len(row) > 6 else "",
                            fb,
                        ))
            elif (event == "SPELL_AURA_APPLIED" and len(row) > 10
                    and _to_int(row[9]) in _BLOODLUST_IDS
                    and str(row[1]).startswith(("Player-", "Pet-"))):
                # CAST_SUCCESS 없는 로그 대비. 진짜 블러드는 다수 대상에 동시
                # 적용 — 자기 자신만 깜빡이는 동명 오라(기원사 등)와 구분하려고
                # 대상 guid 를 남기고 선별 단계에서 대상 수를 검사한다.
                player_raw.append((
                    round(max(t, 0.0), 2), "bloodlust_aura", row[1],
                    _to_int(row[9]), _clean_name(row[10]),
                    str(row[5]) if len(row) > 5 else "",
                    _clean_name(row[6]) if len(row) > 6 else "", False))

            if (event in boss_track_events
                    and len(row) > 10
                    and str(row[1]).startswith(("Creature-", "Vehicle-"))
                    and _flags_int(row[3]) & _HOSTILE_FLAG):
                # 적대 소스만 — 흑마 임프 같은 아군 소환수의 시전 스팸 제외
                is_cast = event in ("SPELL_CAST_START", "SPELL_CAST_SUCCESS", "SPELL_SUMMON")
                is_debuff = (event == "SPELL_AURA_APPLIED" and len(row) > 12
                              and row[12] == "DEBUFF"
                              and str(row[5]).startswith("Player-"))
                is_impact = (event in ("SPELL_DAMAGE", "SPELL_PERIODIC_DAMAGE", "RANGE_DAMAGE",
                                       "SPELL_MISSED", "SPELL_ABSORBED")
                             and str(row[5]).startswith("Player-"))
                if is_cast or is_debuff or is_impact:
                    boss_raw.append((
                        round(max(t, 0.0), 2), event,
                        _to_int(row[9]), _clean_name(row[10]),
                        row[1], _clean_name(row[2]),
                        str(row[5]) if len(row) > 5 else "",
                        _clean_name(row[6]) if len(row) > 6 else "",
                    ))
            if (event in ("SPELL_AURA_APPLIED", "SPELL_AURA_APPLIED_DOSE",
                          "SPELL_AURA_REFRESH", "SPELL_AURA_REMOVED_DOSE",
                          "SPELL_AURA_REMOVED", "SPELL_AURA_BROKEN",
                          "SPELL_AURA_BROKEN_SPELL") and len(row) > 12
                    and row[12] == "DEBUFF" and str(row[5]).startswith("Player-")):
                # 소스 flags 는 안 봄 — 시전자가 죽은 뒤 해제되는 오라도 매칭되게.
                # APPLIED 로 수집된 (spell_id, dest) 짝만 실제로 쓰인다.
                stacks = _to_int(row[13]) if len(row) > 13 else 0
                aura_updates.append((
                    round(max(t, 0.0), 2), event, _to_int(row[9]),
                    str(row[5]), str(row[1]), stacks))

            adv = _adv_position_any(row)
            if not adv:
                continue
            guid, x, y, ui_map, facing, hp = adv
            samples.setdefault(guid, []).append((t, x, y, facing, hp))
            map_counts[ui_map] += 1
            name = _actor_name(row, guid)
            if name:
                names.setdefault(guid, name)
            if guid not in hostile and guid.startswith(("Creature-", "Vehicle-")):
                # adv guid 가 소스면 row[3], 대상이면 row[7] 이 해당 유닛 flags
                if guid == row[1] and _flags_int(row[3]) & _HOSTILE_FLAG:
                    hostile.add(guid)
                elif len(row) > 7 and guid == row[5] and _flags_int(row[7]) & _HOSTILE_FLAG:
                    hostile.add(guid)

    return {"samples": samples, "names": names, "specs": specs,
            "deaths": deaths, "map_counts": map_counts, "boss_raw": boss_raw,
            "aura_updates": aura_updates, "casts": casts,
            "player_raw": player_raw, "hostile": hostile,
            "counts": dict(activity_counts)}


def _boss_tokens(encounter_name: str) -> set[str]:
    return {tok for tok in (encounter_name or "").split() if len(tok) >= 2}


# 전투 이름과 보스 유닛 이름이 다른 네임드 — 이름 매칭만으론 보스로 못 잡는 경우.
# (예: 전투 "한밤의 도래"의 보스 유닛은 "르우라")
_ENCOUNTER_BOSS_ALIASES: dict[str, tuple[str, ...]] = {
    "한밤의 도래": ("르우라",),
}


def _classify_units(
    samples: dict[str, list],
    names: dict[str, str],
    specs: dict[str, int],
    encounter_name: str,
    hostile: set[str] | None = None,
) -> list[dict[str, Any]]:
    """유닛 선별: 플레이어 전부 + 보스(이름 매칭) + 적대 npc 상위 N (샘플 순).

    npc 는 적대(REACTION_HOSTILE) Creature/Vehicle 만 — 아군 소환수/펫 제외.
    같은 이름 개체가 여럿이면 이름에 " 1/2/3" 넘버링 (첫 등장 순).
    NPC id 가 아니라 표시 이름으로 묶는다 — 같은 이름이 여러 NPC id 로
    나오는 로그에서 번호가 겹치는 것 방지.
    """
    tokens = _boss_tokens(encounter_name)
    aliases = _ENCOUNTER_BOSS_ALIASES.get((encounter_name or "").strip(), ())
    hostile = hostile or set()
    units: list[dict[str, Any]] = []
    npcs: list[tuple[int, dict[str, Any]]] = []
    for guid, pts in samples.items():
        name = names.get(guid, "")
        if guid.startswith("Player-"):
            units.append({"guid": guid, "name": name,
                          "cls": _SPEC_CLASS.get(specs.get(guid, 0)),
                          "role": _SPEC_ROLE.get(specs.get(guid, 0), "damage"),
                          "kind": "player"})
        elif name and (name == encounter_name or any(tok in name for tok in tokens)
                       or any(al in name for al in aliases)):
            units.append({"guid": guid, "name": name, "cls": None, "kind": "boss"})
        elif (guid in hostile and guid.startswith(("Creature-", "Vehicle-"))
                and len(pts) >= NPC_MIN_SAMPLES):
            npcs.append((len(pts), {"guid": guid, "name": name, "cls": None, "kind": "npc"}))
    npcs.sort(key=lambda t: t[0], reverse=True)
    if not any(u["kind"] == "boss" for u in units) and npcs:
        # 별칭에도 없는 새 전투 폴백: 샘플이 가장 많은 적대 유닛을 보스로 승격
        # (이름표·상시 표시가 통째로 빠지는 것 방지 — 정확한 이름은 별칭에 추가)
        _, top = npcs.pop(0)
        top["kind"] = "boss"
        units.append(top)
    picked = [u for _, u in npcs[:NPC_MAX]]

    for u in picked:
        if not u["name"]:
            u["name"] = "몬스터"   # 이름 없는 npc — 넘버링만 남는 라벨('1') 방지
    by_name: dict[str, list[dict[str, Any]]] = {}
    for u in picked:
        by_name.setdefault(u["name"], []).append(u)
    for group in by_name.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda u: samples[u["guid"]][0][0])  # 첫 샘플 t 순
        for i, u in enumerate(group, 1):
            u["name"] = f"{u['name']} {i}".strip()

    units.extend(picked)
    # (종족 모델은 정지 포즈라 폐기 — 직업색 원통으로 대체. char_race 조회도 중단, 2026-07-11)
    return units


def _analysis_only_replay_detail(cap: dict[str, Any]) -> dict[str, Any]:
    analysis = cap.get("analysis") or {}
    first = analysis.get("first_death") or {}
    events = []
    if first:
        events.append({
            "t": _to_float(first.get("t")) or 0.0,
            "kind": "death",
            "event": "WCL_FIRST_DEATH",
            "source": "",
            "target": str(first.get("player") or ""),
            "spell": str(first.get("cause") or ""),
        })
    return {
        "capture": _public_capture(cap),
        "encounter": None,
        "duration": round(float(cap.get("duration") or 0), 3),
        "events": events,
        "positions": [],
        "bounds": None,
        "actors": [],
        "counts": {"deaths": _to_int(analysis.get("deaths"))},
        "analysis": analysis,
        "analysis_only": True,
        "sources": {
            "log_file": "",
            "json_file": str(_lura_sync_path()),
            "video_file": "",
            "wcl_url": str(analysis.get("fight_url") or ""),
        },
        "video": {"available": False, "url": "", "remote": False},
    }


def _log_only_replay_detail(
    cap: dict[str, Any],
    log_path: Path,
    enc: dict[str, Any],
) -> dict[str, Any]:
    """영상 없는 로그 전용 상세.

    구형 _parse_log_window()는 대용량 파일을 처음부터 읽는다. 여기서는
    즉시 화면을 열 수 있는 계약 셰만 반환하고, 실제 좌표/전투원/기믹은
    전투 바이트 오프셋으로 seek하는 /frames에서 한 번만 구축한다.
    """
    public_cap = _public_capture(cap)
    public_cap["log_match"] = _public_encounter(enc)
    duration = round(float(enc.get("duration_s") or cap.get("duration") or 0), 3)

    return {
        "capture": public_cap,
        "encounter": _public_encounter(enc),
        "duration": duration,
        "events": [],
        "positions": [],
        "bounds": None,
        "actors": [],
        "counts": {},
        "analysis": cap.get("analysis"),
        "sources": {
            "log_file": str(log_path),
            "json_file": "",
            "video_file": "",
        },
        "video": {"available": False, "url": "", "remote": False},
    }


@lru_cache(maxsize=1)
def _boss_priority_map() -> dict[int, frozenset[int]]:
    """data/boss_spell_priority.json → encounterID → 중요 spell_id 집합.

    fetch_boss_spell_priority.py 산출물 (wowutils viserio-cooldowns).
    파일이 없거나 깨져도 기능은 휴리스틱만으로 동작 (빈 dict).
    """
    from app import replay_map
    path = replay_map.DATA_DIR / "boss_spell_priority.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[int, frozenset[int]] = {}
    for key, ids in data.items():
        if key.startswith("_") or not isinstance(ids, list):
            continue
        eid = _to_int(key)
        if eid:
            out[eid] = frozenset(_to_int(i) for i in ids)
    return out


@lru_cache(maxsize=1)
def _player_spell_kinds() -> dict[int, str]:
    """data/player_spell_types.json → spell_id → player_events kind.

    fetch_player_spell_types.py 산출물 (wowutils viserio playerSpellType).
    관심 밖 타입은 빈 문자열로 남겨 '분류표에 있음'(폴백 금지)을 표시.
    파일이 없거나 깨져도 이름/쿨다운 휴리스틱만으로 동작 (빈 dict).
    """
    from app import replay_map
    path = replay_map.DATA_DIR / "player_spell_types.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[int, str] = {}
    for key, val in data.items():
        if key.startswith("_") or not isinstance(val, str):
            continue
        sid = _to_int(key)
        if sid:
            out[sid] = _SPELL_TYPE_KIND.get(val, "")
    return out


@lru_cache(maxsize=1)
def _long_cooldown_ids() -> frozenset[int]:
    """data/spell_cooldowns.json 에서 쿨다운 >= 180초인 spellID 집합 (폴백용)."""
    from app import replay_map
    path = replay_map.DATA_DIR / "spell_cooldowns.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return frozenset()
    out: set[int] = set()
    for key, val in data.items():
        sid = _to_int(key)
        cd = _to_float(val)
        if sid and cd is not None and cd >= _FALLBACK_CD_MIN:
            out.add(sid)
    return frozenset(out)


def _player_event_kind(
    spell_id: int,
    spell_name: str,
    spell_kinds: dict[int, str],
    long_cds: frozenset[int],
) -> tuple[str, bool]:
    """플레이어 SPELL_CAST_SUCCESS → (kind, 쿨다운폴백 여부). 제외면 ("", False).

    우선순위: 블러드류 > 전투부활 > 분류표(player_spell_types) > 물약/치유석 이름 >
    쿨다운 >= 180s 폴백(offensive).
    """
    if spell_id in _BLOODLUST_IDS:
        return "bloodlust", False
    if spell_id in _BREZ_IDS:
        return "battleres", False
    mapped = spell_kinds.get(spell_id)
    if mapped is not None:
        return mapped, False   # ""(관심 밖 타입)이면 제외 + 폴백 금지
    if "치유석" in spell_name:
        return "healthpot", False
    if "물약" in spell_name:
        if "치유" in spell_name or "생명력" in spell_name:
            return "healthpot", False
        return "potion", False
    if spell_id in long_cds:
        return "offensive", True
    return "", False


_LUST_AURA_MIN_TARGETS = 5  # 오라만으로 블러드 인정하는 최소 동시 대상 수


def _select_lust_events(
    lust_raw: list[tuple[float, str, str, int, str, str, str, bool]],
    guid_to_id: dict[str, str],
) -> list[dict[str, Any]]:
    """블러드류 → 시전자 기준 1초 클러스터당 1건.

    - CAST_SUCCESS 가 포함된 클러스터는 무조건 인정.
    - AURA_APPLIED 만 있는 클러스터는 서로 다른 대상 >= 5 일 때만 인정 —
      진짜 블러드는 공대 전체에 동시 적용, 자기 자신만 반복 점멸하는
      동명 오라(위상의 격노 셀프 프록 등)는 컷.
    - 펫 시전(원초적 분노)은 meta.units 에 없어 unit_id "" — 타이밍 마커 용도.
    """
    by_caster: dict[str, list[tuple[float, str, int, str, str]]] = {}
    for t, kind, src_guid, sid, spell, dest_guid, _dest_name, _fb in sorted(lust_raw):
        by_caster.setdefault(src_guid, []).append((t, kind, sid, spell, dest_guid))

    out: list[dict[str, Any]] = []
    for src_guid, rows in by_caster.items():
        cluster: list[tuple[float, str, int, str, str]] = []

        def flush() -> None:
            if not cluster:
                return
            has_cast = any(k == "bloodlust" for _, k, *_ in cluster)
            targets = {d for _, k, _, _, d in cluster if k == "bloodlust_aura" and d}
            if has_cast or len(targets) >= _LUST_AURA_MIN_TARGETS:
                t0, _, sid0, spell0, _ = cluster[0]
                out.append({
                    "t": t0, "unit_id": guid_to_id.get(src_guid, ""),
                    "kind": "bloodlust", "spell": spell0, "spell_id": sid0,
                })

        for row in rows:
            if cluster and row[0] - cluster[-1][0] > 1.0:
                flush()
                cluster = []
            cluster.append(row)
        flush()
    return out


def _select_player_events(
    player_raw: list[tuple[float, str, str, int, str, str, str, bool]],
    guid_to_id: dict[str, str],
) -> list[dict[str, Any]]:
    """player_raw → frames 응답 player_events (t 오름차순).

    - bloodlust: _select_lust_events 로 시전자 기준 dedupe/검증.
    - defensive 외부생존기: 대상이 다른 플레이어면 spell 에 "→대상" 표기.
    - 총 상한 PLAYER_EVENT_TOTAL_CAP: 쿨다운 폴백류부터 잘라내고 로그에 남김.
    """
    events: list[dict[str, Any]] = []
    lust_raw = [r for r in player_raw if r[1] in ("bloodlust", "bloodlust_aura")]
    events.extend(_select_lust_events(lust_raw, guid_to_id))
    for t, kind, src_guid, sid, spell, dest_guid, dest_name, fallback in sorted(player_raw):
        if kind in ("bloodlust", "bloodlust_aura"):
            continue
        uid = guid_to_id.get(src_guid, "")
        if not uid:
            continue  # meta.units 플레이어만 (펫/이탈자 제외)
        if (kind == "defensive" and dest_guid and dest_guid != src_guid
                and dest_guid.startswith("Player-") and dest_name):
            spell = f"{spell}→{dest_name.split('-', 1)[0]}"
        item: dict[str, Any] = {
            "t": t, "unit_id": uid, "kind": kind,
            "spell": spell, "spell_id": sid,
        }
        if fallback:
            item["_fb"] = True
        events.append(item)
    events.sort(key=lambda e: e["t"])

    if len(events) > PLAYER_EVENT_TOTAL_CAP:
        over = len(events) - PLAYER_EVENT_TOTAL_CAP
        kept: list[dict[str, Any]] = []
        cut_fb = 0
        for item in events:
            if cut_fb < over and item.get("_fb"):
                cut_fb += 1
                continue
            kept.append(item)
        cut_tail = len(kept) - PLAYER_EVENT_TOTAL_CAP
        logging.getLogger(__name__).warning(
            "player_events %d > cap %d — 쿨다운 폴백 %d개 컷, 추가 컷 %d개",
            len(events), PLAYER_EVENT_TOTAL_CAP, cut_fb, max(cut_tail, 0))
        events = kept[:PLAYER_EVENT_TOTAL_CAP]
    for item in events:
        item.pop("_fb", None)
    return events


def _select_boss_events(
    boss_raw: list[tuple[float, str, int, str, str, str, str, str]],
    boss_guids: set[str],
    guid_to_id: dict[str, str],
    priority_ids: frozenset[int],
    tracked_ids: frozenset[int] | None = None,
    aura_updates: list[tuple[float, str, int, str, str, int]] | None = None,
    deaths: list[tuple[float, str]] | None = None,
    duration_s: float = 0.0,
    encounter_id: int = 0,
    difficulty_id: int = 0,
    guid_to_role: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Select replay mechanics and join their casts, auras, impacts, and geometry.

    Cast bars remain broadly visible. Damage, absorbs, misses, and summons are
    admitted only when their ID or localized name matches the encounter's
    tracked catalog. Viserio priority remains a separate display/ranking signal.
    Aura dose/refresh/removal events reconstruct duration and stacks without
    becoming separate timeline entries.
    """
    castbar_ids = {sid for _, ev, sid, *_ in boss_raw if ev == "SPELL_CAST_START"}
    counts: Counter = Counter((ev, sid) for _, ev, sid, *_ in boss_raw)
    tracked_ids = tracked_ids or priority_ids
    priority_names = {
        replay_mechanics.normalize_name(spell)
        for _, _, sid, spell, *_ in boss_raw
        if sid in priority_ids and spell
    }
    tracked_names = {
        replay_mechanics.normalize_name(spell)
        for _, _, sid, spell, *_ in boss_raw
        if sid in tracked_ids and spell
    }
    tracked_profiles_by_name: dict[str, dict[str, Any]] = {}
    for _, _, sid, spell, *_ in boss_raw:
        if sid in tracked_ids and spell:
            tracked_profiles_by_name.setdefault(
                replay_mechanics.normalize_name(spell),
                replay_mechanics.mechanic_profile(
                    sid, spell, encounter_id, difficulty_id))
    guid_to_role = guid_to_role or {}

    # 다중 대상 디버프(한 번에 6명 등)는 적용 '횟수'가 대상 수만큼 부풀어 저빈도
    # 필터/캡에 걸림 → AURA_APPLIED 는 3초 군집 = 1웨이브로 세서 판정한다.
    _aura_ts: dict[int, list[float]] = {}
    for t, ev, sid, *_ in boss_raw:
        if ev == "SPELL_AURA_APPLIED":
            _aura_ts.setdefault(sid, []).append(t)
    wave_counts: dict[int, int] = {}
    for sid, ts in _aura_ts.items():
        ts.sort()
        waves = 1
        for a, b in zip(ts, ts[1:]):
            if b - a > BOSS_HIT_WAVE_GAP_S:
                waves += 1
        wave_counts[sid] = waves

    # (spell_id, dest_guid)별 오라 변화와 대상 사망 시각을 시간순으로 준비한다.
    updates_by_key: dict[tuple[int, str], list[tuple[float, str, str, int]]] = {}
    for ut, uevent, sid, dguid, usrc, stacks in aura_updates or []:
        updates_by_key.setdefault((sid, dguid), []).append((ut, uevent, usrc, stacks))
    for updates in updates_by_key.values():
        updates.sort()
    death_by_guid: dict[str, list[float]] = {}
    for dt_, dguid in deaths or []:
        death_by_guid.setdefault(dguid, []).append(dt_)

    picked: list[dict[str, Any]] = []
    for t, ev, sid, spell, src_guid, src_name, dest_guid, dest_name in boss_raw:
        prio = (sid in priority_ids
                or replay_mechanics.normalize_name(spell) in priority_names)
        tracked = (sid in tracked_ids
                   or replay_mechanics.normalize_name(spell) in tracked_names)
        if ev == "SPELL_CAST_START":
            kind = "cast"
        elif ev == "SPELL_CAST_SUCCESS":
            if sid in castbar_ids:
                continue  # CAST_START 로 이미 잡힘 (완료 시점 중복)
            if counts[(ev, sid)] > BOSS_HIT_MAX_APPLIED and not tracked:
                continue  # 틱뎀·평타류 스팸
            kind = "cast"
        elif ev == "SPELL_AURA_APPLIED":
            n = wave_counts.get(sid, counts[(ev, sid)])
            if n > BOSS_HIT_MAX_APPLIED and not tracked:
                continue
            kind = "hit"
        elif ev == "SPELL_SUMMON":
            if not tracked:
                continue
            kind = "summon"
        else:
            if not tracked:
                continue
            kind = "impact"
        item: dict[str, Any] = {
            "t": t, "spell_id": sid, "spell": spell,
            "kind": kind, "src_name": src_name,
        }
        profile = replay_mechanics.mechanic_profile(
            sid, spell, encounter_id, difficulty_id)
        group_profile = tracked_profiles_by_name.get(
            replay_mechanics.normalize_name(spell))
        if group_profile:
            observed_geometry = profile.get("geometry")
            profile = dict(group_profile)
            if observed_geometry:
                profile["geometry"] = observed_geometry
        item["mechanic_key"] = profile["key"]
        item["root_spell_id"] = profile["root_spell_id"]
        if profile.get("types"):
            item["types"] = profile["types"]
        if profile.get("geometry"):
            item["geometry"] = profile["geometry"]
        src_id = guid_to_id.get(src_guid)
        if src_id:
            item["src_id"] = src_id
        if ev == "SPELL_AURA_APPLIED":
            # 오라 구간: 다음 REMOVED > t. 없으면 대상 사망/전투 종료 중 이른 쪽.
            end: float | None = None
            instant = False
            updates = updates_by_key.get((sid, dest_guid)) or []
            removals = [
                (ut, usrc) for ut, uevent, usrc, _ in updates
                if uevent in ("SPELL_AURA_REMOVED", "SPELL_AURA_BROKEN",
                              "SPELL_AURA_BROKEN_SPELL")
            ]
            if removals:
                i = bisect.bisect_right(removals, (t, "￿"))
                if i > 0 and removals[i - 1][0] == t:
                    # 같은 시각(10ms 반올림)에 해제 = 즉시 풀린 오라 — 순간 취급.
                    # 다음 구간의 REMOVED 나 사망/전투끝 폴백에 잘못 붙는 것 방지.
                    instant = True
                else:
                    # 같은 스킬을 여러 몹이 건 경우: 같은 소스의 해제를 우선 짝짓기
                    for rt, rsrc in removals[i:]:
                        if rsrc == src_guid:
                            end = rt
                            break
                    if end is None and i < len(removals):
                        end = removals[i][0]
            if end is None and not instant:
                end = duration_s if duration_s > 0 else None
                for death_t in death_by_guid.get(dest_guid, ()):
                    if death_t >= t:
                        end = death_t if end is None else min(end, death_t)
                        break
            if end is not None and end - t >= 1.0:
                item["end"] = round(end, 2)
            stack_events: list[dict[str, Any]] = []
            max_stacks = 1
            for ut, uevent, usrc, stacks in updates:
                if ut < t or (usrc and usrc != src_guid):
                    continue
                if ut > t and uevent == "SPELL_AURA_APPLIED":
                    break
                if uevent in ("SPELL_AURA_REMOVED", "SPELL_AURA_BROKEN",
                              "SPELL_AURA_BROKEN_SPELL"):
                    break
                if uevent in ("SPELL_AURA_APPLIED_DOSE", "SPELL_AURA_REFRESH",
                              "SPELL_AURA_REMOVED_DOSE"):
                    shown_stacks = stacks or max_stacks
                    max_stacks = max(max_stacks, shown_stacks)
                    stack_events.append({
                        "t": ut, "stacks": shown_stacks,
                        "action": uevent.removeprefix("SPELL_AURA_").lower(),
                    })
            if stack_events:
                item["stack_events"] = stack_events
                item["max_stacks"] = max_stacks
        if prio:
            item["priority"] = True
        if tracked:
            item["_tracked"] = True
        if src_guid in boss_guids:
            item["_boss_src"] = True
        dest_id = guid_to_id.get(dest_guid)
        if dest_id:
            item["dest_id"] = dest_id
        if guid_to_role.get(dest_guid):
            item["dest_role"] = guid_to_role[dest_guid]
        if dest_name:
            item["dest_name"] = dest_name
        picked.append(item)

    # 스펠별 캡 — 초과분은 시간축 균등 샘플 (앞쪽 쏠림 방지).
    # 단 hit(디버프)는 개별 샘플이 웨이브를 반토막 내서 "6명 중 3명만 하이라이트"가
    # 됐던 버그 → 3초 군집(웨이브)을 통째로 유지하고 웨이브 단위로 샘플.
    confidence_rank = {"semantic": 1, "manual": 2, "override": 2, "db2": 3}
    geometry_by_mechanic: dict[str, dict[str, Any]] = {}
    for item in picked:
        geometry = item.get("geometry")
        if not geometry:
            continue
        current = geometry_by_mechanic.get(item["mechanic_key"])
        if (current is None
                or confidence_rank.get(geometry.get("confidence"), 0)
                > confidence_rank.get(current.get("confidence"), 0)):
            geometry_by_mechanic[item["mechanic_key"]] = geometry
    for item in picked:
        geometry = geometry_by_mechanic.get(item["mechanic_key"])
        if geometry:
            item["geometry"] = geometry

    by_spell: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for item in picked:
        by_spell.setdefault((item["kind"], item["spell_id"]), []).append(item)
    capped: list[dict[str, Any]] = []
    for (kind, _sid), items in by_spell.items():
        cap = BOSS_EVENT_HIT_CAP if kind == "hit" else BOSS_EVENT_SPELL_CAP
        if len(items) <= cap:
            capped.extend(items)
            continue
        if kind == "hit":
            waves: list[list[dict[str, Any]]] = [[items[0]]]
            for it in items[1:]:
                if it["t"] - waves[-1][-1]["t"] <= BOSS_HIT_WAVE_GAP_S:
                    waves[-1].append(it)
                else:
                    waves.append([it])
            avg = max(1, round(len(items) / len(waves)))
            target = max(1, cap // avg)
            if len(waves) > target:
                step = len(waves) / target
                waves = [waves[int(i * step)] for i in range(target)]
            capped.extend(it for w in waves for it in w)
        else:
            step = len(items) / BOSS_EVENT_SPELL_CAP
            capped.extend(items[int(i * step)] for i in range(BOSS_EVENT_SPELL_CAP))

    # 전체 캡 — priority > 공식 저널 추적 > 보스 소스 > 시간 순으로 남기되,
    # 스펠별 최소 지분(BOSS_EVENT_MIN_KEEP)을 먼저 보장한다. 순수 시간순 컷은
    # 전투 끝에만 나오는 저빈도 기믹을 통째로 지웠다 (예: P3 한밤 12건 전멸).
    if len(capped) > BOSS_EVENT_TOTAL_CAP:
        capped.sort(key=lambda x: (
            not x.get("priority"), not x.get("_tracked"),
            not x.get("_boss_src"), x["t"]))
        per_spell: dict[tuple[str, int], int] = {}
        guaranteed: list[dict[str, Any]] = []
        rest: list[dict[str, Any]] = []
        for item in capped:
            key = (item["kind"], item["spell_id"])
            if per_spell.get(key, 0) < BOSS_EVENT_MIN_KEEP:
                per_spell[key] = per_spell.get(key, 0) + 1
                guaranteed.append(item)
            else:
                rest.append(item)
        capped = (guaranteed + rest)[:BOSS_EVENT_TOTAL_CAP]
    for item in capped:
        item.pop("_boss_src", None)
        item.pop("_tracked", None)
    capped.sort(key=lambda x: x["t"])
    return capped


def _boss_mechanic_summaries(
    events: list[dict[str, Any]],
    encounter_id: int,
    difficulty_id: int,
) -> list[dict[str, Any]]:
    """Collapse repeated cast/aura/impact events into tooltip-ready mechanics."""
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        key = str(event.get("mechanic_key") or
                  f"spell:{_to_int(event.get('root_spell_id') or event.get('spell_id'))}")
        current = grouped.setdefault(key, {
            "key": key,
            "spell_id": _to_int(event.get("root_spell_id") or event.get("spell_id")),
            "observed_name": str(event.get("spell") or ""),
            "count": 0,
            "kinds": set(),
            "types": list(event.get("types") or []),
            "geometry": event.get("geometry") if isinstance(event.get("geometry"), dict) else None,
            "priority": False,
        })
        current["count"] += 1
        current["kinds"].add(str(event.get("kind") or "cast"))
        current["priority"] = bool(current["priority"] or event.get("priority"))
        if not current.get("geometry") and isinstance(event.get("geometry"), dict):
            current["geometry"] = event["geometry"]

    out: list[dict[str, Any]] = []
    for current in grouped.values():
        tip = replay_mechanics.mechanic_tip(
            current["spell_id"], current["observed_name"], encounter_id)
        current["name"] = str(tip.get("name") or current.get("observed_name") or "")
        current.pop("observed_name", None)
        current["kinds"] = sorted(current["kinds"])
        for field in ("desc", "role_notes", "roles", "guide", "sources",
                      "wowhead_url", "fallback_source_url"):
            value = tip.get(field)
            if value:
                current[field] = value
        current["spell_id"] = _to_int(tip.get("root_spell_id")) or current["spell_id"]
        out.append(current)
    out.sort(key=lambda item: (
        not item.get("priority"), -_to_int(item.get("count")), str(item.get("name") or "")))
    return out


def _lura_formation_snapshot(
    samples: dict[str, list[tuple[float, float, float, float | None, int | None]]],
    names: dict[str, str],
    guid_to_id: dict[str, str],
    t: float,
) -> dict[str, Any]:
    """르우라 산개 시각의 좌표 요약.

    고급 로그 좌표는 비동기 표본이므로 기준 시각보다 미래인 점은 쓰지 않고,
    0.75초 안의 마지막 점만 사용한다. 거리 수치는 후보를 좁히는 용도이며
    공대 배정표가 없는 상태에서 합격/실패를 판정하지 않는다.
    """
    points: list[tuple[str, str, float, float]] = []
    roster = sum(1 for guid in guid_to_id if guid.startswith("Player-"))
    for guid, unit_samples in samples.items():
        uid = guid_to_id.get(guid)
        if not uid or not guid.startswith("Player-") or not unit_samples:
            continue
        times = [row[0] for row in unit_samples]
        index = bisect.bisect_right(times, t) - 1
        if index < 0:
            continue
        sample_t, x, y, _facing, hp = unit_samples[index]
        if t - sample_t > 0.75 or (hp is not None and hp <= 0):
            continue
        points.append((uid, names.get(guid, "") or uid, x, y))

    def percentile(values: list[float], fraction: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        position = (len(ordered) - 1) * fraction
        low = int(position)
        high = min(low + 1, len(ordered) - 1)
        weight = position - low
        return ordered[low] * (1 - weight) + ordered[high] * weight

    xs = sorted(row[2] for row in points)
    ys = sorted(row[3] for row in points)
    center_x = percentile(xs, 0.5)
    center_y = percentile(ys, 0.5)
    radii = [((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
             for _uid, _name, x, y in points]
    pairs: list[dict[str, Any]] = []
    within_3 = 0
    for i, (left_id, left_name, left_x, left_y) in enumerate(points):
        for right_id, right_name, right_x, right_y in points[i + 1:]:
            distance = ((left_x - right_x) ** 2 + (left_y - right_y) ** 2) ** 0.5
            if distance <= 3.0:
                within_3 += 1
            if distance < 5.5:
                pairs.append({
                    "left_id": left_id, "left_name": left_name,
                    "right_id": right_id, "right_name": right_name,
                    "distance_yards": round(distance, 2),
                })
    pairs.sort(key=lambda row: row["distance_yards"])
    return {
        "t": round(t, 2),
        "tracked_players": len(points),
        "roster_players": roster,
        "coverage_ok": len(points) >= 18,
        "near_pairs_3y": within_3,
        "near_pairs_5_5y": len(pairs),
        "closest_pairs": pairs[:6],
        "raid_radius_yards": {
            "r50": round(percentile(radii, 0.5), 1),
            "r90": round(percentile(radii, 0.9), 1),
            "max": round(max(radii), 1) if radii else 0.0,
        },
    }


def _lura_review_focus(
    boss_raw: list[tuple[float, str, int, str, str, str, str, str]],
    aura_updates: list[tuple[float, str, int, str, str, int]],
    casts: dict[str, list[tuple[float, str]]],
    samples: dict[str, list[tuple[float, float, float, float | None, int | None]]],
    names: dict[str, str],
    guid_to_id: dict[str, str],
    duration_s: float,
) -> dict[str, Any]:
    """르우라 네 집중 구간을 전투 시작 기준 북마크로 만든다."""
    raw = sorted(boss_raw, key=lambda row: row[0])

    def distinct_times(rows: list[tuple], gap: float = 0.75) -> list[float]:
        out: list[float] = []
        for row in rows:
            value = float(row[0])
            if not out or value - out[-1] > gap:
                out.append(value)
        return out

    def first_time(
        spell_ids: set[int], events: set[str], after: float = 0.0,
        before: float | None = None,
    ) -> float | None:
        for row in raw:
            if row[0] < after or (before is not None and row[0] > before):
                continue
            if row[2] in spell_ids and row[1] in events:
                return float(row[0])
        return None

    def target_summary(rows: list[tuple]) -> tuple[list[str], list[str]]:
        found: dict[str, str] = {}
        for row in rows:
            guid = str(row[6] or "")
            if not guid.startswith("Player-"):
                continue
            found.setdefault(guid, names.get(guid, "") or str(row[7] or "") or guid)
        guids = sorted(found, key=lambda guid: found[guid])
        return [guid_to_id.get(guid, "") for guid in guids if guid_to_id.get(guid)], [
            found[guid] for guid in guids]

    crystal_ops = sorted(
        (float(t), guid) for guid, unit_casts in casts.items()
        if guid.startswith("Player-")
        for t, spell in unit_casts if spell == _LURA_CRYSTAL_NAME)

    eclipse_start = first_time({1255743}, {"SPELL_CAST_START"})
    p1_cutoff = eclipse_start if eclipse_start is not None else min(duration_s + 1, 230.0)

    p1_windows: list[dict[str, Any]] = []
    symphony_rows = [row for row in raw
                     if row[1] == "SPELL_CAST_START" and row[2] == 1285708
                     and row[0] < p1_cutoff]
    for occurrence, cast_t in enumerate(distinct_times(symphony_rows), 1):
        quasar_rows = [row for row in raw
                       if cast_t + 8.0 <= row[0] <= cast_t + 14.0
                       and row[2] in {1282469, 1282470}
                       and row[1] in {"SPELL_CAST_SUCCESS", "SPELL_AURA_APPLIED",
                                      "SPELL_DAMAGE", "SPELL_MISSED"}]
        mismatch_rows = [row for row in raw
                         if cast_t <= row[0] <= cast_t + 8.0
                         and row[2] in {1249584, 1249585}
                         and row[1] in {"SPELL_DAMAGE", "SPELL_MISSED"}]
        target_ids, target_names = target_summary(quasar_rows)
        mismatch_ids, mismatch_names = target_summary(mismatch_rows)
        expected_t = round(cast_t + 11.55, 2)
        window_complete = duration_s >= expected_t
        segment_specs = [
            ("문양 종료", cast_t + 4.0),
            ("집결", cast_t + 8.0),
            ("레이저", cast_t + 11.55),
        ]
        segments = [
            {"label": label, "t": round(value, 2)}
            for label, value in segment_specs if value <= duration_s
        ]
        if not window_complete:
            segments.append({"label": "전투 종료", "t": round(duration_s, 2)})
        p1_windows.append({
            "occurrence": occurrence,
            "start_t": round(min(duration_s, cast_t + 4.0), 2),
            "seek_t": round(min(duration_s, cast_t + 8.0), 2),
            "anchor_t": round(min(duration_s, expected_t), 2),
            "end_t": round(min(duration_s, cast_t + 14.0), 2),
            "segments": segments,
            "target_unit_ids": target_ids,
            "target_names": target_names,
            "observed": {
                "quasar_hit_players": len(target_names),
                "quasar_targets": target_names,
                "rune_mismatch_players": len(mismatch_names),
                "rune_mismatch_targets": mismatch_names,
                "rune_mismatch_unit_ids": mismatch_ids,
                "window_complete": window_complete,
            },
        })

    def active_starsplinter_intervals(end_t: float) -> dict[str, list[tuple[float, float]]]:
        active: dict[tuple[int, str], float] = {}
        intervals: dict[str, list[tuple[float, float]]] = {}
        applied = {"SPELL_AURA_APPLIED", "SPELL_AURA_APPLIED_DOSE",
                   "SPELL_AURA_REFRESH"}
        removed = {"SPELL_AURA_REMOVED", "SPELL_AURA_BROKEN",
                   "SPELL_AURA_BROKEN_SPELL"}
        for t, event, sid, guid, _source, _stacks in sorted(aura_updates):
            if sid not in {1279512, 1285510} or not guid.startswith("Player-"):
                continue
            key = (sid, guid)
            if event in applied:
                active.setdefault(key, float(t))
            elif event in removed and key in active:
                intervals.setdefault(guid, []).append((active.pop(key), float(t)))
        for (_sid, guid), start in active.items():
            intervals.setdefault(guid, []).append((start, end_t))
        return intervals

    intermission_windows: list[dict[str, Any]] = []
    if eclipse_start is not None:
        into_darkwell = first_time({1282043}, {"SPELL_CAST_START"}, eclipse_start)
        intermission_end = into_darkwell if into_darkwell is not None else duration_s
        pre_ops = [(t, guid) for t, guid in crystal_ops
                   if eclipse_start - 4.0 <= t < eclipse_start]
        phase_ops = [(t, guid) for t, guid in crystal_ops
                     if eclipse_start <= t <= intermission_end]
        intervals = active_starsplinter_intervals(intermission_end)
        simultaneous_ops = [
            (t, guid) for t, guid in phase_ops
            if any(start <= t <= end for start, end in intervals.get(guid, ()))
        ]
        phase_handlers = sorted({guid for _t, guid in phase_ops},
                                key=lambda guid: names.get(guid, guid))
        simultaneous_handlers = sorted({guid for _t, guid in simultaneous_ops},
                                       key=lambda guid: names.get(guid, guid))
        star_rows = [row for row in raw
                     if eclipse_start <= row[0] <= intermission_end
                     and row[2] in {1279512, 1285510}
                     and row[1] == "SPELL_AURA_APPLIED"]
        quasar_rows = [row for row in raw
                       if eclipse_start <= row[0] <= intermission_end
                       and row[2] in {1282469, 1282470}
                       and row[1] in {"SPELL_CAST_SUCCESS", "SPELL_AURA_APPLIED",
                                      "SPELL_DAMAGE", "SPELL_MISSED"}]
        _star_ids, star_names = target_summary(star_rows)
        quasar_ids, quasar_names = target_summary(quasar_rows)
        first_op = phase_ops[0][0] if phase_ops else eclipse_start
        first_simultaneous = simultaneous_ops[0][0] if simultaneous_ops else first_op
        intermission_windows.append({
            "occurrence": 1,
            "start_t": round(max(0.0, eclipse_start - 4.0), 2),
            "seek_t": round(max(0.0, eclipse_start - 4.0), 2),
            "anchor_t": round(first_simultaneous, 2),
            "end_t": round(intermission_end, 2),
            "segments": [
                {"label": "사전 배치", "t": round(max(0.0, eclipse_start - 4.0), 2)},
                {"label": "수정 조작", "t": round(first_op, 2)},
                {"label": "동시 특임", "t": round(first_simultaneous, 2)},
                {"label": "복귀", "t": round(intermission_end, 2)},
            ],
            "target_unit_ids": quasar_ids,
            "target_names": quasar_names,
            "observed": {
                "pre_crystal_operations": len(pre_ops),
                "crystal_operations": len(phase_ops),
                "crystal_handlers": [names.get(guid, guid) for guid in phase_handlers],
                "simultaneous_operations": len(simultaneous_ops),
                "simultaneous_handlers": [names.get(guid, guid)
                                          for guid in simultaneous_handlers],
                "starsplinter_targets": len(star_names),
                "quasar_hit_players": len(quasar_names),
                "quasar_targets": quasar_names,
            },
        })

    p2_windows: list[dict[str, Any]] = []
    galvanize_rows = [row for row in raw
                      if row[1] == "SPELL_CAST_START" and row[2] == 1284528]
    galvanize_times = distinct_times(galvanize_rows)
    for occurrence, start_t in enumerate(galvanize_times, 1):
        next_start = (galvanize_times[occurrence]
                      if occurrence < len(galvanize_times) else start_t + 26.0)
        aura_t = first_time({1281184}, {"SPELL_AURA_APPLIED"},
                            start_t, min(next_start, start_t + 20.0))
        impact_after = aura_t if aura_t is not None else start_t + 10.0
        impact_t = first_time(
            {1281178}, {"SPELL_DAMAGE", "SPELL_MISSED"},
            impact_after, min(next_start, start_t + 20.0))
        if impact_t is None:
            impact_t = start_t + 14.6
        harvest_t = first_time({1282412}, {"SPELL_CAST_START"},
                               impact_t, min(next_start, start_t + 25.0))
        cycle_end = harvest_t if harvest_t is not None else min(next_start, start_t + 18.0)
        cycle_ops = [(t, guid) for t, guid in crystal_ops
                     if start_t <= t <= impact_t + 1.0]
        first_group = [(t, guid) for t, guid in cycle_ops
                       if aura_t is None or t < aura_t]
        second_group = [(t, guid) for t, guid in cycle_ops
                        if aura_t is not None and t >= aura_t]
        handlers = sorted({guid for _t, guid in cycle_ops},
                          key=lambda guid: names.get(guid, guid))
        impact_rows = [row for row in raw
                       if impact_t - 0.2 <= row[0] <= impact_t + 0.8
                       and row[2] == 1281178
                       and row[1] in {"SPELL_DAMAGE", "SPELL_MISSED"}]
        _impact_ids, impact_names = target_summary(impact_rows)
        snapshot = _lura_formation_snapshot(
            samples, names, guid_to_id, max(start_t, impact_t - 0.1))
        first_crystal_t = first_group[0][0] if first_group else start_t + 2.0
        second_crystal_t = second_group[0][0] if second_group else (aura_t or impact_t)
        p2_windows.append({
            "occurrence": occurrence,
            "start_t": round(start_t, 2),
            "seek_t": round(first_crystal_t, 2),
            "anchor_t": round(impact_t, 2),
            "end_t": round(min(duration_s, cycle_end + 3.0), 2),
            "segments": [
                {"label": "1차 수정", "t": round(first_crystal_t, 2)},
                {"label": "산개", "t": round(aura_t or (start_t + 10.6), 2)},
                {"label": "2차 수정", "t": round(second_crystal_t, 2)},
                {"label": "판정", "t": round(impact_t, 2)},
                {"label": "복귀", "t": round(harvest_t or cycle_end, 2)},
            ],
            "target_unit_ids": [],
            "target_names": [],
            "observed": {
                "crystal_operations": len(cycle_ops),
                "first_crystal_operations": len(first_group),
                "second_crystal_operations": len(second_group),
                "crystal_handlers": [names.get(guid, guid) for guid in handlers],
                "criticality_events": len(impact_rows),
                "criticality_players": len(impact_names),
                "formation": snapshot,
            },
        })

    p3_windows: list[dict[str, Any]] = []
    meltdown_start = first_time({1281123}, {"SPELL_CAST_START"})
    if meltdown_start is not None:
        snapshot_times = [
            ("산개 확인", meltdown_start + 4.0),
            ("튕김 직전", meltdown_start + 7.5),
            ("튕김 후", meltdown_start + 9.5),
        ]
        snapshots = [
            {"label": label, **_lura_formation_snapshot(
                samples, names, guid_to_id, min(duration_s, snap_t))}
            for label, snap_t in snapshot_times]
        p3_windows.append({
            "occurrence": 1,
            "start_t": round(meltdown_start, 2),
            "seek_t": round(meltdown_start + 4.0, 2),
            "anchor_t": round(meltdown_start + 7.5, 2),
            "end_t": round(min(duration_s, meltdown_start + 11.0), 2),
            "segments": [
                {"label": label, "t": round(min(duration_s, snap_t), 2)}
                for label, snap_t in snapshot_times
            ],
            "target_unit_ids": [],
            "target_names": [],
            "observed": {"snapshots": snapshots},
        })

    def item(
        key: str, label: str, phase: str, note: str,
        spell_ids: list[int], windows: list[dict[str, Any]], reached_at: float,
    ) -> dict[str, Any]:
        if windows:
            status = "available"
        elif duration_s >= reached_at:
            status = "event_missing"
        else:
            status = "not_reached"
        return {
            "key": key, "label": label, "phase": phase, "status": status,
            "note": note, "mechanic_spell_ids": spell_ids, "windows": windows,
        }

    # 전투로그는 르우라 전 구간을 같은 uiMapID(2534)로 기록한다. 별도 맵을
    # 꾸며내지 않고, 실제 공간 이동을 확정할 수 있는 시전 성공 시각만 분석
    # 레이어 경계로 내려 화면에서 현재 공간을 명시한다.
    darkwell_success = first_time({1282043}, {"SPELL_CAST_SUCCESS"})
    if darkwell_success is None and galvanize_times:
        darkwell_success = galvanize_times[0]
    meltdown_success = first_time({1281123}, {"SPELL_CAST_SUCCESS"})
    spaces: list[dict[str, Any]] = []

    def add_space(key: str, label: str, start_t: float, end_t: float) -> None:
        start_t = max(0.0, min(duration_s, start_t))
        end_t = max(start_t, min(duration_s, end_t))
        if end_t > start_t:
            spaces.append({
                "key": key, "label": label,
                "start_t": round(start_t, 2), "end_t": round(end_t, 2),
            })

    p2_space_start = darkwell_success if darkwell_success is not None else duration_s
    p3_space_start = (
        meltdown_success if meltdown_success is not None else duration_s
    )
    add_space("p1", "P1/사이페 · 태양샘", 0.0, p2_space_start)
    add_space("p2", "P2 · 암흑샘", p2_space_start, p3_space_start)
    add_space("p3", "P3 · 태양샘", p3_space_start, duration_s)

    return {
        "source": "local_log",
        "timebase": "combat_start_seconds",
        "space_note": (
            "원본 로그의 uiMapID는 동일하며 암흑샘 속으로·어둠의 용해 "
            "성공 시각으로 공간 레이어를 구분합니다."),
        "spaces": spaces,
        "distance_note": (
            "5.5m 미만은 좌표상 근접 후보입니다. 배정표와 빔 경로가 없어 "
            "자동으로 오배치·원인을 판정하지 않습니다."),
        "items": [
            item("p1_rune_quasar", "문양 후 집결·레이저", "P1",
                 "문양 종료 뒤 본대 집결선과 Dark Quasar 피격·직전 이동을 확인",
                 [1285708, 1249609, 1249582, 1249584, 1249585, 1282469, 1282470],
                 p1_windows, 47.0),
            item("intermission_crystal", "수정·별빛파열 간섭", "사이페",
                 "수정 조작 담당과 별빛파열 동시 특임의 배치·동선을 확인",
                 [1255743, 1253050, 1279512, 1285510, 1281473, 1282043],
                 intermission_windows, 184.0),
            item("p2_crystal_spread", "수정→산개→복귀", "P2",
                 "수정 1·2차 조작, 임계점 산개, 핵 채취 복귀 순서를 확인",
                 [1284528, 1253050, 1281184, 1281178, 1282412],
                 p2_windows, 238.0),
            item("p3_knockback_spread", "진입 전 튕김 산개", "P3 진입",
                 "어둠의 용해 전후 산개와 튕긴 뒤 양쪽 분리 동선을 확인",
                 [1281123, 1281184, 1281178, 1275057],
                 p3_windows, 333.0),
        ],
    }


# 여명의 수정 보유 마커: '일렁이는 빛'(1253031) — 수정을 든 동안 붙는 자기 디버프.
# 내려놓기(1253050)가 이 오라를 취소하므로 APPLIED→REMOVED 가 곧 보유 구간.
_LURA_CRYSTAL_HOLD_ID = 1253031


def _lura_crystal_holds(
    aura_updates: list[tuple[float, str, int, str, str, int]],
    guid_to_id: dict[str, str],
    duration_s: float,
) -> list[dict[str, Any]]:
    """수정 보유 구간 [{u, s, e}] — 짝 없는 APPLIED 는 전투 끝까지 보유로 본다."""
    open_at: dict[str, float] = {}
    holds: list[dict[str, Any]] = []
    for t, event, sid, dest, _src, _stacks in sorted(aura_updates):
        if sid != _LURA_CRYSTAL_HOLD_ID:
            continue
        uid = guid_to_id.get(dest)
        if not uid:
            continue
        if event == "SPELL_AURA_APPLIED":
            open_at.setdefault(uid, t)
        elif event in ("SPELL_AURA_REMOVED", "SPELL_AURA_BROKEN",
                       "SPELL_AURA_BROKEN_SPELL"):
            start = open_at.pop(uid, None)
            if start is not None:
                holds.append({"u": uid, "s": start, "e": round(t, 2)})
    for uid, start in open_at.items():
        holds.append({"u": uid, "s": start, "e": round(duration_s, 2)})
    holds.sort(key=lambda h: (h["s"], h["u"]))
    return holds


# 르우라 위상(암흑의 룬 1249609) — 룬 위상에 들어간 구간. P1 웨이브·P3 공용.
_LURA_REALM_ID = 1249609


def _aura_windows_for(
    aura_updates: list[tuple[float, str, int, str, str, int]],
    guid_to_id: dict[str, str],
    duration_s: float,
    want_sid: int,
) -> list[dict[str, Any]]:
    """특정 오라의 보유 구간 [{u, s, e}] — APPLIED→REMOVED, 짝 없으면 전투 끝까지."""
    open_at: dict[str, float] = {}
    out: list[dict[str, Any]] = []
    for t, event, sid, dest, _src, _stacks in sorted(aura_updates):
        if sid != want_sid:
            continue
        uid = guid_to_id.get(dest)
        if not uid:
            continue
        if event == "SPELL_AURA_APPLIED":
            open_at.setdefault(uid, t)
        elif event in ("SPELL_AURA_REMOVED", "SPELL_AURA_BROKEN",
                       "SPELL_AURA_BROKEN_SPELL"):
            start = open_at.pop(uid, None)
            if start is not None:
                out.append({"u": uid, "s": start, "e": round(t, 2)})
    for uid, start in open_at.items():
        out.append({"u": uid, "s": start, "e": round(duration_s, 2)})
    out.sort(key=lambda w: (w["s"], w["u"]))
    return out


# frames 결과 메모리 캐시: replay_id → (로그파일 시그니처, payload).
# 로그 파일이 안 바뀌었으면 재파싱 생략 — 리스트에서 판 전환 시 즉시 로드.
_frames_cache: dict[str, tuple[tuple[str, int, int], dict[str, Any]]] = {}
_FRAMES_CACHE_MAX = 6

# 바닥 징표(세계 표식) 이벤트 캐시: 파일 경로 → (시그니처, 이벤트 목록)
_world_marker_cache: dict[str, tuple[tuple[str, int, int], list]] = {}


def _world_marker_events(
    log_path: Path,
) -> list[tuple[datetime, str, int, float, float, int]]:
    """파일 전체에서 WORLD_MARKER_PLACED/REMOVED 만 추출 (청크 스캔, 파일별 캐시).

    바닥징은 풀 시작 전(전투 밖)에 설치되고 제거 전까지 유지되므로
    인카운터 바이트 구간이 아니라 파일 전체를 봐야 한다. 이벤트가 극히
    드물어(파일당 수 개~수백 개) 청크 단위 부분문자열 검사로 걸러낸다.
    반환: (시각, 'placed'|'removed', 인덱스, x, y, 존ID) 시간순.
    REMOVED 는 인덱스만 기록되므로 x/y/존ID 는 0.
    """
    sig = _file_sig(log_path)
    hit = _world_marker_cache.get(str(log_path))
    if hit and hit[0] == sig:
        return hit[1]
    needle = b"WORLD_MARKER"
    events: list[tuple[datetime, str, int, float, float, int]] = []

    def _take(raw: bytes) -> None:
        m = _LOG_LINE_RE.match(raw.decode("utf-8-sig", errors="replace"))
        if not m:
            return
        ts = _parse_log_ts(m.group(1))
        row = _csv_row(m.group(2))
        if not ts or not row:
            return
        if row[0] == "WORLD_MARKER_PLACED" and len(row) >= 5:
            events.append((ts, "placed", _to_int(row[2]),
                           float(row[3]), float(row[4]), _to_int(row[1])))
        elif row[0] == "WORLD_MARKER_REMOVED" and len(row) >= 2:
            events.append((ts, "removed", _to_int(row[1]), 0.0, 0.0, 0))

    tail = b""
    with log_path.open("rb") as fh:
        while True:
            chunk = fh.read(8 * 1024 * 1024)
            if not chunk:
                break
            buf = tail + chunk
            cut = buf.rfind(b"\n")
            if cut < 0:
                tail = buf
                continue
            body, tail = buf[:cut + 1], buf[cut + 1:]
            if needle not in body:
                continue
            for raw in body.splitlines():
                if needle in raw:
                    _take(raw)
    if tail and needle in tail:
        _take(tail)
    _world_marker_cache[str(log_path)] = (sig, events)
    return events


def _world_marker_windows(
    log_path: Path, start_dt: datetime, duration_s: float, instance_id: int,
) -> list[dict[str, Any]]:
    """인카운터 [0, duration] 에 보이는 바닥징 구간 [{i, x, y, s, e}] 재구성.

    설치는 인덱스별 상태로 누적(풀 전 설치 → s=0)하고, 다른 존에서 설치된
    징은 결과에서 제외한다(REMOVED 는 존 정보가 없어 상태 갱신에만 쓴다).
    """
    try:
        wm_events = _world_marker_events(log_path)
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    active: dict[int, tuple[float, float, float, int]] = {}  # idx → (x, y, s, 존)

    def _close(idx: int, end_t: float) -> None:
        prev = active.pop(idx, None)
        if prev is None or end_t <= 0:
            return
        x, y, s, zone = prev
        if not instance_id or not zone or zone == instance_id:
            out.append({"i": idx, "x": round(x, 2), "y": round(y, 2),
                        "s": s, "e": round(min(end_t, duration_s), 1)})

    for ts, kind, idx, x, y, zone in wm_events:
        t = (ts - start_dt).total_seconds()
        if t >= duration_s:
            break
        _close(idx, t)
        if kind == "placed":
            active[idx] = (x, y, round(max(t, 0.0), 1), zone)
    for idx in list(active):
        _close(idx, duration_s)
    out.sort(key=lambda w: (w["s"], w["i"]))
    return out


def replay_frames(replay_id: str) -> dict[str, Any]:
    """GET /api/replay/{id}/frames 응답 본체 (API 계약 고정 포맷)."""
    from app import replay_map  # 순환 import 방지 겸 지연 로드

    cap = _find_capture(replay_id)
    if cap.get("analysis_only"):
        analysis = cap.get("analysis") or {}
        encounter_id = _to_int(cap.get("encounter_id"))
        unavailable_focus: dict[str, Any] | None = None
        if encounter_id == 3183:
            unavailable_focus = _lura_review_focus(
                [], [], {}, {}, {}, {}, float(cap.get("duration") or 0))
            unavailable_focus["source"] = "wcl"
            for focus_item in unavailable_focus["items"]:
                focus_item["status"] = "no_positions"
                focus_item["windows"] = []
        out = {
            "meta": {
                "encounter": cap.get("encounter") or "",
                "encounter_id": encounter_id,
                "difficulty_id": _to_int(cap.get("difficulty_id")),
                "instance_id": 0,
                "duration_s": round(float(cap.get("duration") or 0), 3),
                "video_offset_s": 0.0,
                "map": {},
                "terrain_bbox": [],
                "units": [],
                "deaths": [],
                "frames_available": False,
                "unavailable_reason": "wcl_only",
            },
            "frames": [],
            "boss_events": [],
            "boss_mechanics": [],
            "casts": {},
            "player_events": [],
            "counts": {"deaths": _to_int(analysis.get("deaths"))},
            "analysis": analysis,
        }
        if unavailable_focus:
            out["review_focus"] = unavailable_focus
        return out
    log_path, enc = _find_frames_encounter(cap)
    # 완료된 전투의 [start_off, end_off] 바이트 구간은 활성 로그가 자라도 불변 —
    # 파일 전체 시그니처를 키로 쓰면 라이브 로그에서 매 요청 재파싱이라 구간 키를 쓴다.
    end_off = _to_int(enc.get("end_off"))
    if end_off:
        sig = (str(log_path), _to_int(enc.get("start_off")), end_off)
    else:
        sig = _file_sig(log_path)
    hit = _frames_cache.get(replay_id)
    if hit and hit[0] == sig:
        return hit[1]
    start_dt = enc["_start_dt"]
    end_dt = enc.get("_end_dt") or (start_dt + timedelta(seconds=(cap.get("duration") or 0) + 5))
    duration_s = enc.get("duration_s") or round((end_dt - start_dt).total_seconds(), 3)

    # 시간축 동기화: frames 의 t 는 ENCOUNTER_START 기준, 이벤트/영상은 캡처 시작
    # 기준이라 그 차이(초)를 내려준다. 캡처 시각을 모르면 0.
    cap_start = cap.get("_start_dt")
    video_offset_s = round((start_dt - cap_start).total_seconds(), 3) if cap_start else 0.0

    parsed = _stream_frames_window(
        log_path, enc["start_off"], enc.get("end_off") or 0, start_dt, end_dt)

    # 지배적 uiMapID 하나만 (위상 전투는 추후 맵 전환 지원)
    dominant_map = 0
    if parsed["map_counts"]:
        dominant_map = parsed["map_counts"].most_common(1)[0][0]

    samples = parsed["samples"]
    units = _classify_units(samples, parsed["names"], parsed["specs"],
                            enc.get("encounter") or "",
                            parsed.get("hostile") or set())

    # 짧은 유닛 id 부여 (JSON 용량 절약): p1.. / b1.. / n1..
    prefix_counter = {"player": 0, "boss": 0, "npc": 0}
    guid_to_id: dict[str, str] = {}
    for unit in units:
        prefix_counter[unit["kind"]] += 1
        guid_to_id[unit["guid"]] = f"{unit['kind'][0]}{prefix_counter[unit['kind']]}"

    # 0.5초 그리드 다운샘플 — 버킷마다 유닛별 마지막 샘플 채택
    buckets: dict[int, dict[str, list]] = {}
    player_world: list[tuple[float, float]] = []
    for unit in units:
        uid = guid_to_id[unit["guid"]]
        for t, x, y, facing, hp in samples[unit["guid"]]:
            if t < 0:
                continue
            if unit["kind"] == "player":
                player_world.append((x, y))
            b = int(t // FRAME_STEP)
            buckets.setdefault(b, {})[uid] = [
                round(x, 2), round(y, 2),
                round(facing, 3) if facing is not None else None,
                hp,
            ]
    frames = [{"t": round(b * FRAME_STEP, 1), "p": pts}
              for b, pts in sorted(buckets.items())]

    # 시전 타임라인 — meta.units 에 있는 유닛만 (펫/기타 guid 제외),
    # 유닛당 상한 CASTS_UNIT_CAP 초과 시 앞부분을 버린다.
    # 쫄몹은 낮은 상한 — 40마리까지 포함되면서 페이로드가 수 MB 로 커지는 것 방지
    casts_out: dict[str, list[list[Any]]] = {}
    for guid, items in (parsed.get("casts") or {}).items():
        uid = guid_to_id.get(guid)
        if not uid:
            continue
        cap_n = CASTS_NPC_CAP if uid.startswith("n") else CASTS_UNIT_CAP
        if len(items) > cap_n:
            items = items[-cap_n:]
        casts_out[uid] = [[t, spell] for t, spell in items]

    # 죽음 마커 — 추적 중인 유닛만
    deaths = [{"t": t, "id": guid_to_id[g]} for t, g in parsed["deaths"] if g in guid_to_id]

    # 보스 기믹 이벤트 (누가 대상인지) — viserio priority 목록은 있으면 보강
    encounter_id = (_to_int(enc.get("encounter_id"))
                    or _to_int(cap.get("encounter_id")))
    difficulty_id = (_to_int(enc.get("difficulty_id"))
                     or _to_int(cap.get("difficulty_id")))
    priority_ids = _boss_priority_map().get(encounter_id, frozenset())
    tracked_ids = frozenset(
        set(priority_ids) | set(replay_mechanics.encounter_spell_ids(encounter_id)))
    if encounter_id == 3183:
        tracked_ids = frozenset(set(tracked_ids) | set(_LURA_REVIEW_TRACKED_IDS))
    boss_guids = {u["guid"] for u in units if u["kind"] == "boss"}
    guid_to_role = {u["guid"]: u.get("role", "") for u in units}
    boss_events = _select_boss_events(
        parsed.get("boss_raw") or [], boss_guids, guid_to_id, priority_ids,
        tracked_ids=tracked_ids,
        aura_updates=parsed.get("aura_updates") or [],
        deaths=parsed.get("deaths") or [],
        duration_s=float(duration_s or 0),
        encounter_id=encounter_id, difficulty_id=difficulty_id,
        guid_to_role=guid_to_role)
    boss_mechanics = _boss_mechanic_summaries(
        boss_events, encounter_id, difficulty_id)

    # 플레이어 이벤트 (블러드/물약/치유석/오펜시브/생존기)
    player_events = _select_player_events(
        parsed.get("player_raw") or [], guid_to_id)

    review_focus = None
    crystal_holds: list[dict[str, Any]] = []
    realm_windows: list[dict[str, Any]] = []
    if encounter_id == 3183:
        review_focus = _lura_review_focus(
            parsed.get("boss_raw") or [], parsed.get("aura_updates") or [],
            parsed.get("casts") or {}, samples, parsed.get("names") or {},
            guid_to_id, float(duration_s or 0))
        crystal_holds = _lura_crystal_holds(
            parsed.get("aura_updates") or [], guid_to_id, float(duration_s or 0))
        realm_windows = _aura_windows_for(
            parsed.get("aura_updates") or [], guid_to_id, float(duration_s or 0),
            _LURA_REALM_ID)

    # 맵 메타 + world→px 계수 (플레이어 실좌표로 축 뒤집힘 캘리브레이션)
    calib = player_world[::max(1, len(player_world) // 200)]  # 최대 ~200점만
    if not dominant_map:
        # uiMapID 0 = 좌표에 맵 정보 없음 — wago 조회 자체가 무의미하니 생략
        map_out = _fallback_map(0, player_world, "uiMapID 0 (좌표에 맵 정보 없음)")
    else:
        try:
            mmeta = replay_map.map_meta(dominant_map)
            map_out = {
                "ui_map_id": dominant_map,
                "px_w": mmeta["px_w"],
                "px_h": mmeta["px_h"],
                "world_to_px": replay_map.world_to_px(mmeta, calib),
            }
            # 존 전체 맵에 좌표가 얹힌 경우(전투 방 전용 지도가 없는 인스턴스 —
            # 예: 살라다르 방은 UiMap 2529 존 맵뿐) 픽셀 밀도가 너무 낮아
            # 확대해도 양피지 뭉개짐만 보인다 → 좌표 bounds 폴백이 차라리 읽힌다.
            m = map_out["world_to_px"]
            px_per_yd = (abs(m["a"] * m["e"] - m["b"] * m["d"])) ** 0.5
            if px_per_yd < 1.5:
                map_out = _fallback_map(
                    dominant_map, player_world,
                    f"전용 전투 지도 없음(존 맵 {px_per_yd:.1f}px/yd) — 좌표 기준 표시")
        except Exception as exc:
            # 오프라인/미지원 맵 폴백: 좌표 bounds 를 1000px 캔버스에 맞춤
            map_out = _fallback_map(dominant_map, player_world, str(exc))

    if review_focus and review_focus.get("spaces"):
        map_out["spaces"] = review_focus["spaces"]
        map_out["space_note"] = review_focus.get("space_note") or ""

    out = {
        "meta": {
            "encounter": enc.get("encounter") or (cap.get("encounter") or ""),
            "encounter_id": encounter_id,
            "difficulty_id": difficulty_id,
            "instance_id": _to_int(enc.get("instance_id")),
            "duration_s": round(float(duration_s), 3),
            "video_offset_s": video_offset_s,
            "map": map_out,
            "terrain_bbox": (
                [min(x for x, _ in player_world), max(x for x, _ in player_world),
                 min(y for _, y in player_world), max(y for _, y in player_world)]
                if player_world else []
            ),
            "units": [
                {"id": guid_to_id[u["guid"]], "name": u["name"],
                 "cls": u["cls"], "kind": u["kind"],
                 "role": u.get("role"),
                 "race": u.get("race"), "sex": u.get("sex")}
                for u in units
            ],
            "deaths": deaths,
        },
        "frames": frames,
        "boss_events": boss_events,
        "boss_mechanics": boss_mechanics,
        "casts": casts_out,
        "player_events": player_events,
        "counts": parsed.get("counts") or {},
    }
    if review_focus:
        out["review_focus"] = review_focus
    if crystal_holds:
        out["crystal_holds"] = crystal_holds
    if realm_windows:
        out["realm_windows"] = realm_windows
    # 바닥 징표(세계 표식) — 풀 전 설치 포함, 좌표는 유닛과 같은 월드좌표
    world_markers = _world_marker_windows(
        log_path, start_dt, float(duration_s or 0), _to_int(enc.get("instance_id")))
    if world_markers:
        out["world_markers"] = world_markers
    if len(_frames_cache) >= _FRAMES_CACHE_MAX:
        _frames_cache.pop(next(iter(_frames_cache)))
    _frames_cache[replay_id] = (sig, out)
    return out


def replay_terrain_request(replay_id: str) -> dict[str, Any]:
    """GET /api/replay/{id}/terrain 입력 — instance_id + 플레이어 좌표 bbox.

    frames 와 같은 로그 구간·같은 좌표 소스(플레이어 고급좌표, t>=0)를 쓰므로
    지형 그리드의 bbox 기준이 frames 응답과 자연히 일치한다.
    """
    cap = _find_capture(replay_id)
    if cap.get("analysis_only"):
        raise ReplayError("WCL 분석 전용: 로컬 좌표 없음")

    # UI는 frames 직후 terrain을 요청한다. frames 메모리 캐시에 함께 보관한
    # 플레이어 bbox를 재사용해 같은 대용량 로그 구간을 두 번 읽지 않는다.
    payload = replay_frames(replay_id)
    meta = payload.get("meta") or {}
    instance_id = _to_int(meta.get("instance_id"))
    if not instance_id:
        raise ReplayError("ENCOUNTER_START 에 instanceID 없음 — 지형 조회 불가")
    bbox = meta.get("terrain_bbox") or []
    if len(bbox) != 4:
        raise ReplayError("플레이어 좌표 없음 — 고급 전투 기록(advanced logging) 필요")
    return {
        "instance_id": instance_id,
        "bbox": tuple(float(value) for value in bbox),
    }


def _fallback_map(ui_map_id: int, world_xy: list[tuple[float, float]], reason: str) -> dict[str, Any]:
    """맵 이미지를 못 받았을 때: 데이터 bounds 기반 임시 변환 (빈 배경용)."""
    if not world_xy:
        return {"ui_map_id": ui_map_id, "px_w": 1000, "px_h": 1000,
                "world_to_px": {"a": 0.0, "b": -1.0, "c": 500.0,
                                "d": -1.0, "e": 0.0, "f": 500.0},
                "error": reason}
    xs = [p[0] for p in world_xy]
    ys = [p[1] for p in world_xy]
    pad = 10.0
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    px_w = 1000
    px_h = max(1, round(px_w * (max_x - min_x) / max(max_y - min_y, 1e-6)))
    # +Y=서 → 화면 왼쪽, +X=북 → 화면 위 (스파이크와 동일 방향)
    b = -px_w / (max_y - min_y)
    c = px_w * max_y / (max_y - min_y)
    d = -px_h / (max_x - min_x)
    f = px_h * max_x / (max_x - min_x)
    return {"ui_map_id": ui_map_id, "px_w": px_w, "px_h": px_h,
            "world_to_px": {"a": 0.0, "b": b, "c": c, "d": d, "e": 0.0, "f": f},
            "error": reason}
