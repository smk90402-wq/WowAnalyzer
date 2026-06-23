from __future__ import annotations

import csv
import hashlib
import json
import os
import re
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


def latest_log_path(log_dir: Path = DEFAULT_LOG_DIR) -> Path | None:
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


def _capture_id(path: Path, data: dict[str, Any]) -> str:
    raw = str(data.get("uniqueHash") or "").strip()
    path_hash = hashlib.sha1(str(path).encode("utf-8", errors="ignore")).hexdigest()[:12]
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


def _load_captures(cctv_dir: Path = DEFAULT_CCTV_DIR, limit: int = 80) -> list[dict[str, Any]]:
    if not cctv_dir.exists():
        return []
    paths = sorted(
        cctv_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime_ns,
        reverse=True,
    )[:max(1, limit)]
    out: list[dict[str, Any]] = []
    for path in paths:
        try:
            data = _read_cctv_json(path)
        except ReplayError:
            continue
        video = path.with_suffix(".mp4")
        start_dt = _json_start_local(path, data)
        deaths = data.get("deaths") or []
        combatants = data.get("combatants") or []
        player = data.get("player") or {}
        out.append({
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
            "video_size_mb": round(video.stat().st_size / 1024 / 1024, 1) if video.exists() else 0,
            "_json_path": path,
            "_video_path": video,
            "_start_dt": start_dt,
            "_raw": data,
        })
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
    encounters = encounter_index(log_path) if log_path else []
    rows = []
    for cap in _load_captures(limit=limit):
        match = _match_capture(cap, encounters)
        row = _public_capture(cap)
        row["log_match"] = _public_encounter(match)
        rows.append(row)
    return {
        "sources": {
            "log_dir": str(DEFAULT_LOG_DIR),
            "cctv_dir": str(DEFAULT_CCTV_DIR),
            "log_file": str(log_path) if log_path else "",
            "encounters": len(encounters),
        },
        "rows": rows,
    }


def _find_capture(replay_id: str) -> dict[str, Any]:
    for cap in _load_captures(limit=400):
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
        "sources": {
            "log_file": str(log_path) if log_path else "",
            "json_file": str(cap.get("_json_path")),
            "video_file": str(cap.get("_video_path")) if cap.get("video_exists") else "",
        },
        "video": {
            "available": bool(cap.get("video_exists")),
            "url": f"/api/local-replay/video/{replay_id}" if cap.get("video_exists") else "",
        },
    }


def replay_video_path(replay_id: str) -> Path:
    cap = _find_capture(replay_id)
    video = cap.get("_video_path")
    if not isinstance(video, Path) or not video.exists():
        raise ReplayError(f"video not found: {replay_id}")
    return video
