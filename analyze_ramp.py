"""Per-spec ramp analysis: first-N-seconds DPS vs full-fight DPS.

Proxy for "how much setup does this spec need in the current patch":
  ratio = first_30s_dps / full_fight_dps
  low ratio (e.g. 0.6) -> big ramp, needs buildup (setup-heavy)
  ~1.0 or higher      -> front-loaded / burst opener, minimal setup

Sampling: top 5 logs per (class, spec) across bosses (rank-1 per boss preferred),
each log needs 2 /v1/report/tables/damage-done calls (first window + full fight).
Caches all responses to data/cache_damage.json so reruns are free.
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
SLEEP = 0.5

CSV = Path(__file__).parent / "data" / "rankings_zone46_mythic_dps_top100.csv"
CACHE_FIGHTS = Path(__file__).parent / "data" / "cache_fights.json"
CACHE_DMG = Path(__file__).parent / "data" / "cache_damage.json"

OPENING_MS = 30_000
SAMPLES_PER_SPEC = 5


def load_json(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


cache_fights = load_json(CACHE_FIGHTS)
cache_dmg = load_json(CACHE_DMG)


def save_dmg() -> None:
    CACHE_DMG.write_text(json.dumps(cache_dmg), encoding="utf-8")


def api(url: str, params: dict) -> dict | None:
    params = dict(params, api_key=KEY)
    for attempt in range(8):
        try:
            r = requests.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            print(f"    req err: {e}")
            time.sleep(5)
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


def fetch_damage(rid: str, start: int, end: int) -> dict | None:
    k = f"{rid}:{start}:{end}"
    if k in cache_dmg:
        return cache_dmg[k]
    data = api(f"{BASE}/report/tables/damage-done/{rid}", {"start": start, "end": end})
    if data is None or "entries" not in data:
        cache_dmg[k] = None
        return None
    # keep only what we need: actor name -> total damage
    slim = {"totalTime": data.get("totalTime"),
            "entries": [{"name": e.get("name"), "total": e.get("total")}
                        for e in data.get("entries", [])]}
    cache_dmg[k] = slim
    return slim


def dps_for(data: dict | None, name: str) -> float | None:
    if not data or not data.get("entries") or not data.get("totalTime"):
        return None
    for e in data["entries"]:
        if e["name"] == name:
            return e["total"] / data["totalTime"] * 1000
    return None


def main() -> None:
    df = pd.read_csv(CSV)
    df["report_id"] = df["report_id"].astype(str)
    df["fight_id"] = df["fight_id"].astype(int)

    # sample: rank 1 per (boss, class, spec), then top SAMPLES_PER_SPEC per spec
    rank1 = df[df["rank"] == 1].copy()
    picks = (
        rank1.sort_values("dps", ascending=False)
        .groupby(["class", "spec"])
        .head(SAMPLES_PER_SPEC)
        .reset_index(drop=True)
    )
    print(f"Samples to process: {len(picks)}")

    ratios: list[tuple[str, str, float]] = []
    for i, row in picks.iterrows():
        rid = row["report_id"]
        fid = row["fight_id"]
        fights = cache_fights.get(rid)
        if not fights:
            continue
        window = fights.get(str(fid))
        if not window:
            continue
        start, end = window
        full_duration = end - start
        if full_duration < 45_000:   # skip very short fights
            continue
        opening_end = start + OPENING_MS

        opening = fetch_damage(rid, start, opening_end)
        full = fetch_damage(rid, start, end)

        if (i + 1) % 10 == 0:
            save_dmg()
            print(f"  {i+1}/{len(picks)}")

        open_dps = dps_for(opening, row["character"])
        full_dps = dps_for(full, row["character"])
        if open_dps is None or full_dps is None or full_dps <= 0:
            continue
        ratios.append((row["class"], row["spec"], open_dps / full_dps))
        time.sleep(SLEEP)
    save_dmg()

    rdf = pd.DataFrame(ratios, columns=["class", "spec", "ratio"])
    summary = (
        rdf.groupby(["class", "spec"])
        .agg(samples=("ratio", "size"), mean_ratio=("ratio", "mean"),
             median_ratio=("ratio", "median"))
        .reset_index()
        .sort_values("mean_ratio")
    )
    summary["mean_ratio"] = summary["mean_ratio"].round(3)
    summary["median_ratio"] = summary["median_ratio"].round(3)
    print("\nfirst-30s DPS / full-fight DPS   (low = setup-heavy, high = instant)")
    print(summary.to_string(index=False))
    out = Path(__file__).parent / "data" / "ramp_ratio.csv"
    summary.to_csv(out, index=False)
    print(f"\nSaved -> {out}")


if __name__ == "__main__":
    main()
