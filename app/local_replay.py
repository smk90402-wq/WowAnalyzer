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


def _flags_int(value: Any) -> int:
    """전투로그 flags 필드('0x10a48') → int. 실패 시 0."""
    try:
        return int(str(value), 16)
    except (TypeError, ValueError):
        return 0


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


# ═══════════════════════════════════════════════════════════════════════════
# 맵 리플레이 프레임 — GET /api/replay/{replay_id}/frames 백엔드
# (REPLAY3D_PLAN.md MVP: 아카이브 로그 + 바이트오프셋 seek + 0.5초 다운샘플)
# ═══════════════════════════════════════════════════════════════════════════

ARCHIVE_DIR_NAME = "warcraftlogsarchive"
FRAME_STEP = 0.5          # 다운샘플 그리드 (초)
NPC_MAX = 8               # 보스 외 npc 는 샘플 많은 순 상위 N 만
NPC_MIN_SAMPLES = 10      # 이보다 샘플 적은 npc 는 제외
CASTS_UNIT_CAP = 2000     # casts: 유닛당 시전 상한 (초과 시 앞부분 버림)

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
BOSS_EVENT_TOTAL_CAP = 300    # 풀당 전체 캡
BOSS_EVENT_SPELL_CAP = 20     # 스펠별 캡 (초과 시 균등 샘플)
BOSS_HIT_MAX_APPLIED = 15     # 플레이어 디버프: 풀당 적용 횟수 이 이하만 (스팸 컷)

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


def _candidate_logs(cap_start: datetime, log_dir: Path = DEFAULT_LOG_DIR) -> list[Path]:
    """캡처 시각을 포함할 수 있는 로그 파일들 (현재 + 아카이브).

    파일명 시각 <= 캡처 시각 <= mtime 인 파일만 후보 — 1GB 아카이브 전수
    인덱싱을 피하는 1차 필터. 시작 시각이 캡처에 가장 가까운 파일부터 시도.
    """
    cands: list[tuple[datetime, Path]] = []
    dirs = [log_dir, log_dir / ARCHIVE_DIR_NAME]
    for d in dirs:
        if not d.exists():
            continue
        for p in d.glob("*WoWCombatLog-*.txt"):
            file_start = _filename_log_start(p)
            if not file_start:
                continue
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            if file_start - timedelta(minutes=2) <= cap_start <= mtime + timedelta(minutes=2):
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
            "instance_id": _to_int(row[5]),  # Map.db2 ID — 지형(replay_terrain) 체인 시작점
            "start_off": line_off,
            "_start_dt": ts,
        }
    if row[0] == "ENCOUNTER_END" and len(row) >= 7:
        if current and current.get("encounter_id") == _to_int(row[1]):
            current.update({
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


def _encounter_offsets_active(path: Path) -> tuple[dict[str, Any], ...]:
    """활성 로그: 마지막 스캔 지점부터 이어 스캔 (파일이 줄어들면 처음부터)."""
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


def _find_frames_encounter(cap: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """캡처 ↔ 로그 전투 매칭 (encounterID 일치 + 시작 시각 8초 이내)."""
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
    # 시전 성공: guid → [(t, 스킬이름), ...] (다운샘플 없음 — 유닛 선별은 호출부에서)
    casts: dict[str, list[tuple[float, str]]] = {}
    # 보스 기믹 후보: (t, event, spell_id, spell, src_guid, src_name, dest_guid, dest_name)
    boss_raw: list[tuple[float, str, int, str, str, str, str, str]] = []

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

            if (event in ("SPELL_CAST_START", "SPELL_CAST_SUCCESS", "SPELL_AURA_APPLIED")
                    and len(row) > 10
                    and str(row[1]).startswith(("Creature-", "Vehicle-"))
                    and _flags_int(row[3]) & _HOSTILE_FLAG):
                # 적대 소스만 — 흑마 임프 같은 아군 소환수의 시전 스팸 제외
                if event != "SPELL_AURA_APPLIED" or (
                        len(row) > 12 and row[12] == "DEBUFF"
                        and str(row[5]).startswith("Player-")):
                    boss_raw.append((
                        round(max(t, 0.0), 2), event,
                        _to_int(row[9]), _clean_name(row[10]),
                        row[1], _clean_name(row[2]),
                        str(row[5]) if len(row) > 5 else "",
                        _clean_name(row[6]) if len(row) > 6 else "",
                    ))

            adv = _adv_position_any(row)
            if not adv:
                continue
            guid, x, y, ui_map, facing, hp = adv
            samples.setdefault(guid, []).append((t, x, y, facing, hp))
            map_counts[ui_map] += 1
            name = _actor_name(row, guid)
            if name:
                names.setdefault(guid, name)

    return {"samples": samples, "names": names, "specs": specs,
            "deaths": deaths, "map_counts": map_counts, "boss_raw": boss_raw,
            "casts": casts}


def _boss_tokens(encounter_name: str) -> set[str]:
    return {tok for tok in (encounter_name or "").split() if len(tok) >= 2}


def _classify_units(
    samples: dict[str, list],
    names: dict[str, str],
    specs: dict[str, int],
    encounter_name: str,
) -> list[dict[str, Any]]:
    """유닛 선별: 플레이어 전부 + 보스(이름 매칭) + 상위 N npc."""
    tokens = _boss_tokens(encounter_name)
    units: list[dict[str, Any]] = []
    npcs: list[tuple[int, dict[str, Any]]] = []
    for guid, pts in samples.items():
        name = names.get(guid, "")
        if guid.startswith("Player-"):
            units.append({"guid": guid, "name": name,
                          "cls": _SPEC_CLASS.get(specs.get(guid, 0)),
                          "kind": "player"})
        elif name and (name == encounter_name or any(tok in name for tok in tokens)):
            units.append({"guid": guid, "name": name, "cls": None, "kind": "boss"})
        elif len(pts) >= NPC_MIN_SAMPLES:
            npcs.append((len(pts), {"guid": guid, "name": name, "cls": None, "kind": "npc"}))
    npcs.sort(key=lambda t: t[0], reverse=True)
    units.extend(u for _, u in npcs[:NPC_MAX])
    return units


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


def _select_boss_events(
    boss_raw: list[tuple[float, str, int, str, str, str, str, str]],
    boss_guids: set[str],
    guid_to_id: dict[str, str],
    priority_ids: frozenset[int],
) -> list[dict[str, Any]]:
    """보스 기믹 노이즈 컷 (플랜: 시전바 캐스트 전부 + 저빈도 즉시기/디버프 + priority).

    - SPELL_CAST_START: 캐스트바 스킬 → 전부 채택 (kind=cast)
    - SPELL_CAST_SUCCESS: CAST_START 있는 스펠은 중복이라 제외,
      나머지는 풀당 횟수 <= 15 또는 priority 만 (kind=cast)
    - SPELL_AURA_APPLIED(DEBUFF→Player): 풀당 적용 <= 15 또는 priority (kind=hit)
    - 스펠별 캡 20 (초과 시 균등 샘플), 전체 캡 300 (priority > 보스 소스 우선)
    """
    castbar_ids = {sid for _, ev, sid, *_ in boss_raw if ev == "SPELL_CAST_START"}
    counts: Counter = Counter((ev, sid) for _, ev, sid, *_ in boss_raw)

    picked: list[dict[str, Any]] = []
    for t, ev, sid, spell, src_guid, src_name, dest_guid, dest_name in boss_raw:
        prio = sid in priority_ids
        if ev == "SPELL_CAST_START":
            kind = "cast"
        elif ev == "SPELL_CAST_SUCCESS":
            if sid in castbar_ids:
                continue  # CAST_START 로 이미 잡힘 (완료 시점 중복)
            if counts[(ev, sid)] > BOSS_HIT_MAX_APPLIED and not prio:
                continue  # 틱뎀·평타류 스팸
            kind = "cast"
        else:
            if counts[(ev, sid)] > BOSS_HIT_MAX_APPLIED and not prio:
                continue
            kind = "hit"
        item: dict[str, Any] = {
            "t": t, "spell_id": sid, "spell": spell,
            "kind": kind, "src_name": src_name,
        }
        if prio:
            item["priority"] = True
        if src_guid in boss_guids:
            item["_boss_src"] = True
        dest_id = guid_to_id.get(dest_guid)
        if dest_id:
            item["dest_id"] = dest_id
        if dest_name:
            item["dest_name"] = dest_name
        picked.append(item)

    # 스펠별 캡 — 초과분은 시간축 균등 샘플 (앞쪽 쏠림 방지)
    by_spell: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for item in picked:
        by_spell.setdefault((item["kind"], item["spell_id"]), []).append(item)
    capped: list[dict[str, Any]] = []
    for items in by_spell.values():
        if len(items) > BOSS_EVENT_SPELL_CAP:
            step = len(items) / BOSS_EVENT_SPELL_CAP
            items = [items[int(i * step)] for i in range(BOSS_EVENT_SPELL_CAP)]
        capped.extend(items)

    # 전체 캡 — priority > 보스 소스 > 시간 순으로 남김
    if len(capped) > BOSS_EVENT_TOTAL_CAP:
        capped.sort(key=lambda x: (not x.get("priority"), not x.get("_boss_src"), x["t"]))
        capped = capped[:BOSS_EVENT_TOTAL_CAP]
    for item in capped:
        item.pop("_boss_src", None)
    capped.sort(key=lambda x: x["t"])
    return capped


def replay_frames(replay_id: str) -> dict[str, Any]:
    """GET /api/replay/{id}/frames 응답 본체 (API 계약 고정 포맷)."""
    from app import replay_map  # 순환 import 방지 겸 지연 로드

    cap = _find_capture(replay_id)
    log_path, enc = _find_frames_encounter(cap)
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
                            enc.get("encounter") or "")

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
    casts_out: dict[str, list[list[Any]]] = {}
    for guid, items in (parsed.get("casts") or {}).items():
        uid = guid_to_id.get(guid)
        if not uid:
            continue
        if len(items) > CASTS_UNIT_CAP:
            items = items[-CASTS_UNIT_CAP:]
        casts_out[uid] = [[t, spell] for t, spell in items]

    # 죽음 마커 — 추적 중인 유닛만
    deaths = [{"t": t, "id": guid_to_id[g]} for t, g in parsed["deaths"] if g in guid_to_id]

    # 보스 기믹 이벤트 (누가 대상인지) — viserio priority 목록은 있으면 보강
    priority_ids = _boss_priority_map().get(
        _to_int(enc.get("encounter_id")) or _to_int(cap.get("encounter_id")),
        frozenset())
    boss_guids = {u["guid"] for u in units if u["kind"] == "boss"}
    boss_events = _select_boss_events(
        parsed.get("boss_raw") or [], boss_guids, guid_to_id, priority_ids)

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
        except Exception as exc:
            # 오프라인/미지원 맵 폴백: 좌표 bounds 를 1000px 캔버스에 맞춤
            map_out = _fallback_map(dominant_map, player_world, str(exc))

    return {
        "meta": {
            "encounter": enc.get("encounter") or (cap.get("encounter") or ""),
            "instance_id": _to_int(enc.get("instance_id")),
            "duration_s": round(float(duration_s), 3),
            "video_offset_s": video_offset_s,
            "map": map_out,
            "units": [
                {"id": guid_to_id[u["guid"]], "name": u["name"],
                 "cls": u["cls"], "kind": u["kind"]}
                for u in units
            ],
            "deaths": deaths,
        },
        "frames": frames,
        "boss_events": boss_events,
        "casts": casts_out,
    }


def replay_terrain_request(replay_id: str) -> dict[str, Any]:
    """GET /api/replay/{id}/terrain 입력 — instance_id + 플레이어 좌표 bbox.

    frames 와 같은 로그 구간·같은 좌표 소스(플레이어 고급좌표, t>=0)를 쓰므로
    지형 그리드의 bbox 기준이 frames 응답과 자연히 일치한다.
    """
    cap = _find_capture(replay_id)
    log_path, enc = _find_frames_encounter(cap)
    instance_id = _to_int(enc.get("instance_id"))
    if not instance_id:
        raise ReplayError("ENCOUNTER_START 에 instanceID 없음 — 지형 조회 불가")
    start_dt = enc["_start_dt"]
    end_dt = enc.get("_end_dt") or (start_dt + timedelta(seconds=(cap.get("duration") or 0) + 5))
    parsed = _stream_frames_window(
        log_path, enc["start_off"], enc.get("end_off") or 0, start_dt, end_dt)
    xs: list[float] = []
    ys: list[float] = []
    for guid, pts in parsed["samples"].items():
        if not guid.startswith("Player-"):
            continue
        for t, x, y, _facing, _hp in pts:
            if t < 0:
                continue
            xs.append(x)
            ys.append(y)
    if not xs:
        raise ReplayError("플레이어 좌표 없음 — 고급 전투 기록(advanced logging) 필요")
    return {
        "instance_id": instance_id,
        "bbox": (min(xs), max(xs), min(ys), max(ys)),
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
