"""Fetch all cast events for the top-100 of target DPS specs in zone 46.

Target specs (hard-coded): Demonology Warlock, Balance Druid, Beast Mastery Hunter.

API calls (cached, resumable):
  - /v1/report/fights/{rid}
       -> harvest friendlies map (name -> source_id), once per unique report.
       (cache_fights.json from enrich_pi.py only stored time windows; we keep
        a separate cache_source_ids.json so we don't disturb that file.)
  - /v1/report/events/casts/{rid}?start=&end=&sourceid=
       -> all cast events for one player in one fight, possibly paginated
        via nextPageTimestamp. Once per ranking row.

Outputs:
  - data/cache_source_ids.json : {rid: {char_name: source_id}}
  - data/cache_casts.json      : {"rid:fid:source_id": [[ts, spell_id, type], ...]}
  - data/spell_db_en.json      : {spell_id: {"name": str, "icon": str}}
        accumulated from event responses (English; Korean enrichment is a
        separate step using WoWhead).

A limit can be passed on the command line for smoke-testing:
    python fetch_casts.py 5      # only do the first 5 ranking rows
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
KEY = os.environ["WCL_V1_KEY"]
BASE = "https://www.warcraftlogs.com/v1"
SLEEP = 0.35

DATA = Path(__file__).parent / "data"
CSV_IN = DATA / "rankings_zone46_mythic_dps_top100.csv"
CACHE_FIGHTS = DATA / "cache_fights.json"
CACHE_SRCIDS = DATA / "cache_source_ids.json"
CACHE_CASTS = DATA / "cache_casts.json"
SPELL_DB = DATA / "spell_db_en.json"

TARGETS = {
    ("Warlock", "Demonology"),
    ("Druid",   "Balance"),
    ("Hunter",  "Beast Mastery"),
}


def load_json(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_json(p: Path, obj) -> None:
    p.write_text(json.dumps(obj), encoding="utf-8")


cache_fights: dict = load_json(CACHE_FIGHTS)
cache_srcids: dict = load_json(CACHE_SRCIDS)
cache_casts: dict = load_json(CACHE_CASTS)
spell_db: dict = load_json(SPELL_DB)


def api_get(url: str, params: dict) -> dict | None:
    params = dict(params, api_key=KEY)
    for attempt in range(6):
        try:
            r = requests.get(url, params=params, timeout=45)
        except requests.RequestException as e:
            print(f"    req err: {e}")
            time.sleep(4)
            continue
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 30))
            print(f"    429, sleep {wait}s")
            time.sleep(wait)
            continue
        if r.status_code in (400, 403, 404):
            return None
        if r.status_code >= 500:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    return None


def ensure_source_ids(rid: str) -> dict[str, int] | None:
    """Return {char_name: source_id} for the report, fetching if needed."""
    if rid in cache_srcids:
        return cache_srcids[rid]
    data = api_get(f"{BASE}/report/fights/{rid}", {})
    if data is None:
        cache_srcids[rid] = None
        return None
    friendlies = data.get("friendlies") or []
    mapping: dict[str, int] = {}
    for f in friendlies:
        name = f.get("name")
        sid = f.get("id")
        if isinstance(name, str) and isinstance(sid, int):
            mapping[name] = sid
    cache_srcids[rid] = mapping
    return mapping


def absorb_ability(ev: dict) -> None:
    """Update spell_db from one event's ability metadata."""
    ab = ev.get("ability") or {}
    gid = ab.get("guid")
    if not isinstance(gid, int) or gid <= 0:
        return
    key = str(gid)
    if key in spell_db:
        return
    spell_db[key] = {
        "name": ab.get("name") or "",
        "icon": ab.get("abilityIcon") or "",
    }


def fetch_casts(rid: str, fid: int, sid: int, start_ms: int, end_ms: int) -> list | None:
    """Fetch all cast events for one player in one fight. Handles pagination."""
    key = f"{rid}:{fid}:{sid}"
    if key in cache_casts:
        return cache_casts[key]

    collected: list[list] = []
    cur_start = start_ms
    page = 0
    while True:
        page += 1
        data = api_get(
            f"{BASE}/report/events/casts/{rid}",
            {"start": cur_start, "end": end_ms, "sourceid": sid},
        )
        if data is None:
            cache_casts[key] = None
            return None
        events = data.get("events") or []
        for ev in events:
            ab = ev.get("ability") or {}
            gid = ab.get("guid")
            if not isinstance(gid, int):
                continue
            ts = ev.get("timestamp")
            t = ev.get("type") or ""
            if ts is None:
                continue
            collected.append([ts, gid, t])
            absorb_ability(ev)
        nxt = data.get("nextPageTimestamp")
        if not nxt or nxt <= cur_start or page > 20:
            break
        cur_start = nxt
        time.sleep(SLEEP)
    cache_casts[key] = collected
    return collected


def main(limit: int | None = None) -> None:
    df = pd.read_csv(CSV_IN)
    df["report_id"] = df["report_id"].astype(str)
    df["fight_id"] = df["fight_id"].astype(int)

    sub = df[df.apply(lambda r: (r["class"], r["spec"]) in TARGETS, axis=1)].copy()
    sub = sub.sort_values(["encounter_name", "class", "spec", "rank"]).reset_index(drop=True)
    if limit is not None:
        sub = sub.head(limit)
    print(f"Target ranking rows: {len(sub)}")
    print(f"Unique reports     : {sub['report_id'].nunique()}")
    print(f"Unique (rid, fid)  : {len(sub[['report_id', 'fight_id']].drop_duplicates())}")

    # ---- phase 1: source_id maps per report ----
    needed_reports = sub["report_id"].unique().tolist()
    missing_reports = [r for r in needed_reports if r not in cache_srcids]
    print(f"\n[1/2] source_id maps: {len(missing_reports)} new, "
          f"{len(needed_reports) - len(missing_reports)} cached")
    for i, rid in enumerate(missing_reports, 1):
        ensure_source_ids(rid)
        if i % 50 == 0:
            save_json(CACHE_SRCIDS, cache_srcids)
            print(f"    {i}/{len(missing_reports)}")
        time.sleep(SLEEP)
    save_json(CACHE_SRCIDS, cache_srcids)

    # ---- phase 2: casts per ranking row ----
    todo: list[tuple[str, int, int, int, int, str]] = []
    skipped_no_window = 0
    skipped_no_sid = 0
    for _, row in sub.iterrows():
        rid = row["report_id"]
        fid = int(row["fight_id"])
        char = row["character"]
        fights = cache_fights.get(rid) or {}
        window = fights.get(str(fid))
        if not window:
            skipped_no_window += 1
            continue
        sid_map = cache_srcids.get(rid) or {}
        sid = sid_map.get(char) if isinstance(sid_map, dict) else None
        if sid is None:
            skipped_no_sid += 1
            continue
        key = f"{rid}:{fid}:{sid}"
        if key in cache_casts:
            continue
        todo.append((rid, fid, int(sid), int(window[0]), int(window[1]), char))

    print(f"\n[2/2] cast fetches: {len(todo)} todo, "
          f"skipped no_window={skipped_no_window}, no_sid={skipped_no_sid}")

    for i, (rid, fid, sid, s, e, char) in enumerate(todo, 1):
        fetch_casts(rid, fid, sid, s, e)
        if i % 25 == 0:
            save_json(CACHE_CASTS, cache_casts)
            save_json(SPELL_DB, spell_db)
            print(f"    {i}/{len(todo)}   spells_seen={len(spell_db)}")
        time.sleep(SLEEP)
    save_json(CACHE_CASTS, cache_casts)
    save_json(SPELL_DB, spell_db)

    # quick coverage / size summary
    covered = sum(
        1 for _, r in sub.iterrows()
        if (sm := cache_srcids.get(r["report_id"]))
        and isinstance(sm, dict)
        and r["character"] in sm
        and cache_casts.get(f"{r['report_id']}:{int(r['fight_id'])}:{sm[r['character']]}") is not None
    )
    print(f"\nDone. Coverage: {covered}/{len(sub)} rows have cast events.")
    print(f"Distinct spells captured: {len(spell_db)}")


if __name__ == "__main__":
    lim = None
    if len(sys.argv) > 1:
        try:
            lim = int(sys.argv[1])
        except ValueError:
            sys.exit(f"bad limit arg: {sys.argv[1]}")
    main(lim)
