"""Prefetch deeper BM trinket-analysis data from Warcraft Logs v2.

This script intentionally reuses the existing V2Data cache/client instead of
creating a second WCL client. It fills:
- data/v2_cache_player_fight.json for BM top-N gear/stats.
- data/v2_cache_damage.json for BM top-M full-fight DamageDone ability tables.
- data/bm_trinket_deep_cache.json for target breakdowns and short damage
  windows around Algeth'ar Puzzle Box / Bestial Wrath timing.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

from wcl_v2_data import V2Data

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path("data")
RANKINGS = DATA / "rankings_zone46_mythic_dps_top100.csv"
OUT = DATA / "bm_trinket_deep_cache.json"

BOX_ITEM = 193701
ALN_GAZE = 249343
PLUME_MASTERY = 249806
PLUME_CRIT = 260235

BOX_SPELL = 383781
BESTIAL_WRATH = 19574

Q_DAMAGE_TARGET = """
query($code: String!, $start: Float!, $end: Float!, $sid: Int!) {
  reportData {
    report(code: $code) {
      table(
        dataType: DamageDone
        startTime: $start
        endTime: $end
        sourceID: $sid
        hostilityType: Friendlies
        viewBy: Target
      )
    }
  }
}
"""

Q_DAMAGE_ABILITY_WINDOW = """
query($code: String!, $start: Float!, $end: Float!, $sid: Int!) {
  reportData {
    report(code: $code) {
      table(
        dataType: DamageDone
        startTime: $start
        endTime: $end
        sourceID: $sid
        hostilityType: Friendlies
        viewBy: Ability
      )
    }
  }
}
"""

Q_DAMAGE_TARGET_WINDOW = """
query($code: String!, $start: Float!, $end: Float!, $sid: Int!) {
  reportData {
    report(code: $code) {
      table(
        dataType: DamageDone
        startTime: $start
        endTime: $end
        sourceID: $sid
        hostilityType: Friendlies
        viewBy: Target
      )
    }
  }
}
"""


def load_json(path: Path, default: Any) -> Any:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def compact_entries(table_payload: Any, limit: int = 80) -> list[dict[str, Any]]:
    inner = table_payload.get("data") if isinstance(table_payload, dict) and "data" in table_payload else table_payload
    entries = inner.get("entries") if isinstance(inner, dict) else None
    if not isinstance(entries, list):
        return []
    out: list[dict[str, Any]] = []
    for e in entries[:limit]:
        if not isinstance(e, dict):
            continue
        out.append({
            "guid": e.get("guid") or e.get("id"),
            "name": e.get("name") or "",
            "total": e.get("total") or 0,
            "type": e.get("type") or "",
            "icon": e.get("icon") or "",
        })
    return out


def query_table(v2: V2Data, query: str, rid: str, start: float, end: float, sid: int) -> list[dict[str, Any]]:
    data = v2.cli.query(query, {
        "code": rid,
        "start": float(start),
        "end": float(end),
        "sid": int(sid),
    })
    table = (((data or {}).get("reportData") or {}).get("report") or {}).get("table") or {}
    return compact_entries(table)


def read_rankings() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with RANKINGS.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("class") != "Hunter" or row.get("spec") != "Beast Mastery":
                continue
            row["rank"] = int(row["rank"])
            row["encounter_id"] = int(row["encounter_id"])
            row["fight_id"] = int(row["fight_id"])
            row["dps"] = float(row["dps"])
            row["item_level"] = float(row.get("item_level") or 0)
            row["duration_s"] = float(row.get("duration_ms") or 0) / 1000.0
            rows.append(row)
    rows.sort(key=lambda r: (r["encounter_id"], r["rank"]))
    return rows


def top_by_boss(rows: list[dict[str, Any]], topn: int) -> list[dict[str, Any]]:
    counts: dict[int, int] = {}
    out: list[dict[str, Any]] = []
    for row in rows:
        enc = int(row["encounter_id"])
        counts[enc] = counts.get(enc, 0) + 1
        if counts[enc] <= topn:
            out.append(row)
    return out


def fight_window(v2: V2Data, rid: str, fid: int) -> tuple[float, float] | None:
    meta = v2.report_meta(rid) or {}
    for f in meta.get("fights") or []:
        if f.get("id") == fid:
            return float(f["startTime"]), float(f["endTime"])
    return None


def trinket_ids(pfight: dict[str, Any]) -> list[int]:
    return [
        int(g["id"])
        for g in (pfight.get("gear") or [])
        if isinstance(g, dict) and g.get("slot") in (12, 13) and isinstance(g.get("id"), int)
    ]


def trinket_combo(ids: list[int]) -> str:
    s = set(ids)
    if ALN_GAZE in s and BOX_ITEM in s:
        return "ALN_BOX"
    if ALN_GAZE in s and PLUME_MASTERY in s:
        return "ALN_MASTERY_PLUME"
    if ALN_GAZE in s and PLUME_CRIT in s:
        return "ALN_CRIT_PLUME"
    if BOX_ITEM in s:
        return "BOX_OTHER"
    if ALN_GAZE in s:
        return "ALN_OTHER"
    return "OTHER"


def event_times(v2: V2Data, rid: str, fid: int, char: str, start: float) -> tuple[list[float], list[float]]:
    ev = v2.events_for(rid, fid, char) or {}
    casts = ev.get("casts") or []
    boxes = sorted((c[0] - start) / 1000.0 for c in casts
                   if isinstance(c, list) and len(c) >= 3 and c[1] == BOX_SPELL and c[2] == "cast")
    bws = sorted((c[0] - start) / 1000.0 for c in casts
                 if isinstance(c, list) and len(c) >= 3 and c[1] == BESTIAL_WRATH and c[2] == "cast")
    return boxes, bws


def add_window(cache_row: dict[str, Any], key: str, event_s: float, fight_start: float,
               fight_end: float, window_ms: int, v2: V2Data, rid: str, sid: int) -> bool:
    windows = cache_row.setdefault("windows", {})
    if key in windows:
        return False
    start = fight_start + event_s * 1000.0
    end = min(start + window_ms, fight_end)
    if end <= start:
        windows[key] = {"start_s": round(event_s, 3), "duration_s": 0, "ability": [], "target": []}
        return True
    ability = query_table(v2, Q_DAMAGE_ABILITY_WINDOW, rid, start, end, sid)
    target = query_table(v2, Q_DAMAGE_TARGET_WINDOW, rid, start, end, sid)
    windows[key] = {
        "start_s": round(event_s, 3),
        "duration_s": round((end - start) / 1000.0, 3),
        "ability": ability[:40],
        "target": target[:40],
    }
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--player-topn", type=int, default=100)
    ap.add_argument("--deep-topn", type=int, default=25)
    ap.add_argument("--window-sec", type=float, default=20.0)
    ap.add_argument("--no-windows", action="store_true")
    ap.add_argument("--max-box-windows", type=int, default=2)
    ap.add_argument("--max-bw-windows", type=int, default=2)
    ap.add_argument("--max-live-player", type=int, default=10000)
    ap.add_argument("--max-live-deep", type=int, default=10000)
    ap.add_argument("--flush-every", type=int, default=25)
    args = ap.parse_args()

    v2 = V2Data(data_dir=DATA)
    rows = read_rankings()
    player_rows = top_by_boss(rows, args.player_topn)
    deep_rows = top_by_boss(rows, args.deep_topn)
    deep_keys = {
        f"{r['report_id']}:{r['fight_id']}:{r['character']}"
        for r in deep_rows
    }
    cache = load_json(OUT, {"_meta": {}, "rows": {}})
    cache["_meta"] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": str(RANKINGS),
        "player_topn": args.player_topn,
        "deep_topn": args.deep_topn,
        "window_sec": args.window_sec,
        "windows_enabled": not args.no_windows,
        "max_box_windows": args.max_box_windows,
        "max_bw_windows": args.max_bw_windows,
        "notes": [
            "full_ability uses existing v2_cache_damage.json via V2Data.damage_table",
            "full_target and windows are stored in this file",
            "window keys are box_N or bw_N and cover window_sec seconds after the event",
        ],
    }
    cache.setdefault("rows", {})

    print("rate start:", v2.cli.points_left())
    live_player = live_deep = 0
    touched = 0
    failures = 0
    window_ms = int(args.window_sec * 1000)

    for idx, row in enumerate(player_rows, 1):
        rid = row["report_id"]
        fid = int(row["fight_id"])
        char = row["character"]
        key = f"{rid}:{fid}:{char}"

        try:
            if key not in v2.pfight:
                if live_player >= args.max_live_player:
                    continue
                live_player += 1
            pfight = v2.player_fight(rid, fid, char)
        except Exception as exc:
            failures += 1
            print(f"player fail {key}: {exc}", flush=True)
            continue
        if not isinstance(pfight, dict):
            failures += 1
            continue

        if key not in deep_keys:
            if idx % args.flush_every == 0:
                v2.flush()
            continue

        try:
            if live_deep >= args.max_live_deep and key not in cache["rows"]:
                continue
            window = fight_window(v2, rid, fid)
            sid = pfight.get("sourceID")
            if not window or not isinstance(sid, int):
                continue
            fight_start, fight_end = window
            ids = trinket_ids(pfight)
            cache_row = cache["rows"].setdefault(key, {
                "report_id": rid,
                "fight_id": fid,
                "character": char,
                "source_id": sid,
                "encounter_id": row["encounter_id"],
                "encounter_name": row["encounter_name"],
                "rank": row["rank"],
                "dps": row["dps"],
                "item_level": row["item_level"],
                "duration_s": row["duration_s"],
            })
            cache_row.update({
                "trinkets": ids,
                "combo": trinket_combo(ids),
                "stats": pfight.get("stats") or {},
            })
            if "full_ability" not in cache_row:
                live_deep += 1
                cache_row["full_ability"] = v2.damage_table(rid, fid, char) or []
            if "full_target" not in cache_row:
                live_deep += 1
                cache_row["full_target"] = query_table(v2, Q_DAMAGE_TARGET, rid, fight_start, fight_end, sid)

            boxes, bws = event_times(v2, rid, fid, char, fight_start)
            cache_row["box_times_s"] = [round(x, 3) for x in boxes]
            cache_row["bw_times_s"] = [round(x, 3) for x in bws]
            if not args.no_windows:
                for n, t in enumerate(boxes[:max(0, args.max_box_windows)], 1):
                    live_deep += 1 if add_window(cache_row, f"box_{n}", t, fight_start, fight_end, window_ms, v2, rid, sid) else 0
                for n, t in enumerate(bws[:max(0, args.max_bw_windows)], 1):
                    live_deep += 1 if add_window(cache_row, f"bw_{n}", t, fight_start, fight_end, window_ms, v2, rid, sid) else 0
            touched += 1
        except Exception as exc:
            failures += 1
            print(f"deep fail {key}: {exc}", flush=True)

        if idx % args.flush_every == 0:
            v2.flush()
            save_json(OUT, cache)
            print(f"progress {idx}/{len(player_rows)} live_player={live_player} live_deep={live_deep} rows={len(cache['rows'])} failures={failures}", flush=True)

    v2.flush()
    save_json(OUT, cache)
    print(f"done player_rows={len(player_rows)} deep_rows={len(deep_rows)} deep_cached={len(cache['rows'])} touched={touched} failures={failures}")
    print("rate end:", v2.cli.points_left())


if __name__ == "__main__":
    main()
