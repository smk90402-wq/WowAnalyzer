"""Enrich rankings with hero talent picks by pulling each fight's summary table.

The /v1/report/tables/summary/{reportID}?start=..&end=.. endpoint exposes
playerDetails.{dps,tanks,healers}[].combatantInfo.talentTree, which is the
list of chosen talent nodes: [{id, rank, nodeID}, ...].

We cache only the minimum we need: for each (report, fight), a mapping
{character_name: [talent_id, ...]}. Hero-tree identification happens later
(clustering) in classify_talents.py so we don't bake a spec->tree-id table
into the fetch pass.

Reuses cache_fights.json written by enrich_pi.py for fight windows.
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
CACHE_TALENTS = DATA / "cache_talents.json"   # "rid:fid" -> {char_name: [talent_id, ...]}


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
cache_talents: dict = load_json(CACHE_TALENTS)


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


def fetch_summary(rid: str, fid: int, start: int, end: int) -> dict | None:
    """Return {char_name: [talent_id, ...]} for the DPS players in this fight."""
    key = f"{rid}:{fid}"
    if key in cache_talents:
        return cache_talents[key]
    data = api_get(
        f"{BASE}/report/tables/summary/{rid}",
        {"start": start, "end": end},
    )
    if data is None:
        cache_talents[key] = None
        return None
    pd_ = data.get("playerDetails", {}) or {}
    out: dict[str, list[int]] = {}
    for role in ("dps", "tanks", "healers"):
        for p in pd_.get(role, []) or []:
            name = p.get("name")
            if not name:
                continue
            ci = p.get("combatantInfo") or {}
            tt = ci.get("talentTree") or []
            # talentTree entries: {id, rank, nodeID} -- keep id list
            ids = [t.get("id") for t in tt if isinstance(t, dict) and t.get("id") is not None]
            if ids:
                out[name] = sorted(set(ids))
    cache_talents[key] = out
    return out


def main() -> None:
    df = pd.read_csv(CSV_IN)
    df["report_id"] = df["report_id"].astype(str)
    df["fight_id"] = df["fight_id"].astype(int)

    pairs = df[["report_id", "fight_id"]].drop_duplicates()
    print(f"(report, fight) pairs: {len(pairs)}")

    todo = []
    for rid, fid in pairs.itertuples(index=False):
        key = f"{rid}:{fid}"
        if key in cache_talents:
            continue
        fights = cache_fights.get(rid)
        if not fights:
            cache_talents[key] = None
            continue
        window = fights.get(str(fid))
        if not window:
            cache_talents[key] = None
            continue
        todo.append((rid, int(fid), window[0], window[1]))
    print(f"Fetching summary for {len(todo)} fights (cached: {len(pairs) - len(todo)})")

    for i, (rid, fid, s, e) in enumerate(todo, 1):
        fetch_summary(rid, fid, s, e)
        if i % 50 == 0:
            save_json(CACHE_TALENTS, cache_talents)
            print(f"    {i}/{len(todo)}")
        time.sleep(SLEEP)
    save_json(CACHE_TALENTS, cache_talents)

    # quick coverage report
    covered = 0
    for rid, fid, char in df[["report_id", "fight_id", "character"]].itertuples(index=False):
        key = f"{rid}:{fid}"
        entry = cache_talents.get(key)
        if entry and char in entry:
            covered += 1
    print(f"\nRankings rows with talent data: {covered}/{len(df)} ({100*covered/len(df):.1f}%)")


if __name__ == "__main__":
    main()
