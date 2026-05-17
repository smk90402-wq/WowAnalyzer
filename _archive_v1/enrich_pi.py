"""Enrich rankings CSV with pi_received: did the ranking character receive
Power Infusion (Priest, spell 10060) during their fight?

API calls:
  - /v1/report/fights/{reportID}  -- once per unique report (for fight start/end)
  - /v1/report/tables/buffs/{reportID}?abilityid=10060&start=..&end=..
       -- once per unique (report, fight) pair
Both cached to disk so reruns are cheap and interruption-safe.
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
PI_SPELL = 10060
SLEEP = 0.35

DATA = Path(__file__).parent / "data"
CSV_IN = DATA / "rankings_zone46_mythic_dps_top100.csv"
CSV_OUT = DATA / "rankings_zone46_mythic_dps_top100_pi.csv"
CACHE_FIGHTS = DATA / "cache_fights.json"       # report_id -> {fight_id(str): [start_ms, end_ms]}
CACHE_PI = DATA / "cache_pi.json"               # "report_id:fight_id" -> [char_name, ...] or None


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
cache_pi: dict = load_json(CACHE_PI)


def api_get(url: str, params: dict) -> dict | None:
    params = dict(params, api_key=KEY)
    for attempt in range(5):
        try:
            r = requests.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            print(f"    req error: {e}")
            time.sleep(3)
            continue
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 30))
            print(f"    rate limit, sleep {wait}s")
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


def get_fights(rid: str) -> dict[str, list[int]] | None:
    """Return {fight_id_str: [start_ms, end_ms]} for this report."""
    if rid in cache_fights:
        return cache_fights[rid]
    data = api_get(f"{BASE}/report/fights/{rid}", {})
    if data is None:
        cache_fights[rid] = None
        return None
    fights = {}
    for f in data.get("fights", []):
        fights[str(f["id"])] = [f.get("start_time", 0), f.get("end_time", 0)]
    cache_fights[rid] = fights
    return fights


def get_pi_recipients(rid: str, fight_id: int, start_ms: int, end_ms: int) -> list[str] | None:
    key = f"{rid}:{fight_id}"
    if key in cache_pi:
        return cache_pi[key]
    data = api_get(
        f"{BASE}/report/tables/buffs/{rid}",
        {"start": start_ms, "end": end_ms, "abilityid": PI_SPELL},
    )
    if data is None:
        cache_pi[key] = None
        return None
    names = [a.get("name") for a in data.get("auras", []) if a.get("name")]
    cache_pi[key] = names
    return names


def main() -> None:
    df = pd.read_csv(CSV_IN)
    df["report_id"] = df["report_id"].astype(str)
    df["fight_id"] = df["fight_id"].astype(int)

    unique_reports = df["report_id"].unique()
    pairs = df[["report_id", "fight_id"]].drop_duplicates()
    print(f"Reports: {len(unique_reports)}   (report,fight) pairs: {len(pairs)}")

    # Phase 1: report fights metadata
    missing = [r for r in unique_reports if r not in cache_fights]
    print(f"\n[1/2] Fetching fights for {len(missing)} reports (cached: {len(unique_reports) - len(missing)})")
    for i, rid in enumerate(missing, 1):
        get_fights(rid)
        if i % 50 == 0:
            save_json(CACHE_FIGHTS, cache_fights)
            print(f"    {i}/{len(missing)}")
        time.sleep(SLEEP)
    save_json(CACHE_FIGHTS, cache_fights)

    # Phase 2: PI recipients per fight
    todo = []
    for rid, fid in pairs.itertuples(index=False):
        key = f"{rid}:{fid}"
        if key in cache_pi:
            continue
        fights = cache_fights.get(rid)
        if not fights:
            cache_pi[key] = None
            continue
        window = fights.get(str(fid))
        if not window:
            cache_pi[key] = None
            continue
        todo.append((rid, int(fid), window[0], window[1]))
    print(f"\n[2/2] Fetching PI buff data for {len(todo)} fights (cached: {len(pairs) - len(todo)})")

    for i, (rid, fid, s, e) in enumerate(todo, 1):
        get_pi_recipients(rid, fid, s, e)
        if i % 100 == 0:
            save_json(CACHE_PI, cache_pi)
            print(f"    {i}/{len(todo)}")
        time.sleep(SLEEP)
    save_json(CACHE_PI, cache_pi)

    # Merge into rankings
    def row_got_pi(row):
        key = f"{row['report_id']}:{row['fight_id']}"
        recipients = cache_pi.get(key)
        if recipients is None:
            return None
        return row["character"] in recipients

    df["pi_received"] = df.apply(row_got_pi, axis=1)
    df.to_csv(CSV_OUT, index=False)
    print(f"\nWrote {CSV_OUT}")

    # Summary
    sub = df.dropna(subset=["pi_received"]).copy()
    sub["pi_received"] = sub["pi_received"].astype(bool)
    summary = (
        sub.groupby(["class", "spec"])
        .agg(
            n=("pi_received", "size"),
            pi_rate=("pi_received", "mean"),
            median_dps_with_pi=("dps", lambda s: s[sub.loc[s.index, "pi_received"]].median()),
            median_dps_no_pi=("dps", lambda s: s[~sub.loc[s.index, "pi_received"]].median()),
        )
        .reset_index()
    )
    summary["pi_rate_pct"] = (summary["pi_rate"] * 100).round(1)
    summary = summary.sort_values("pi_rate")
    print("\n=== PI dependence (lower pi_rate = less dependent) ===")
    cols = ["class", "spec", "n", "pi_rate_pct", "median_dps_with_pi", "median_dps_no_pi"]
    print(summary[cols].to_string(index=False))


if __name__ == "__main__":
    main()
