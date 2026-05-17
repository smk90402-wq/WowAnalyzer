"""Fetch WarcraftLogs Top-N DPS rankings per spec for every boss in a zone.

V1 quirks that shape this implementation:
  - class/spec filter params return 400 ("Invalid class and spec"), so we can't
    filter server-side. Fetch raw top-N pages and group by spec client-side.
  - metric=rdps returns 500 (broken or retired). Using metric=dps instead -
    external buff stripping is NOT applied.
"""
from __future__ import annotations

import csv
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
API_KEY = os.environ.get("WCL_V1_KEY")
if not API_KEY:
    sys.exit("WCL_V1_KEY missing - fill .env (see .env.example)")

BASE = "https://www.warcraftlogs.com/v1"
ZONE_ID = 46
DIFFICULTY = 5          # 5 = Mythic
METRIC = "dps"
TOP_N = 100
MAX_PAGES = 40          # up to 40*100 = 4000 rankings per boss
SLEEP = 0.4

OUT_DIR = Path(__file__).parent / "data"
OUT_DIR.mkdir(exist_ok=True)

# Spec names to exclude (tanks + healers). Anything else = DPS.
NON_DPS_SPEC_NAMES = {
    "Blood", "Vengeance", "Guardian", "Brewmaster", "Protection",
    "Restoration", "Mistweaver", "Holy", "Discipline", "Preservation",
}


def get(url: str, params: dict | None = None):
    params = dict(params or {})
    params["api_key"] = API_KEY
    for attempt in range(5):
        r = requests.get(url, params=params, timeout=30)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 30))
            print(f"    rate-limited, sleep {wait}s")
            time.sleep(wait)
            continue
        if r.status_code >= 500:
            print(f"    {r.status_code} server error (attempt {attempt+1})")
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"giving up on {url}")


def build_spec_map() -> dict[tuple[int, int], tuple[str, str, bool]]:
    """(class_id, spec_id) -> (class_name, spec_name, is_dps)"""
    m = {}
    for c in get(f"{BASE}/classes"):
        for s in c["specs"]:
            m[(c["id"], s["id"])] = (c["name"], s["name"], s["name"] not in NON_DPS_SPEC_NAMES)
    return m


def fetch_zone(zone_id: int) -> dict:
    for z in get(f"{BASE}/zones"):
        if z["id"] == zone_id:
            return z
    raise ValueError(f"zone {zone_id} not found")


def fetch_boss_rankings(encounter_id: int) -> list[dict]:
    out: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        data = get(
            f"{BASE}/rankings/encounter/{encounter_id}",
            params={"metric": METRIC, "difficulty": DIFFICULTY, "page": page},
        )
        chunk = data.get("rankings", [])
        if not chunk:
            break
        out.extend(chunk)
        if not data.get("hasMorePages"):
            break
        time.sleep(SLEEP)
    return out


def main() -> None:
    spec_map = build_spec_map()
    dps_spec_count = sum(1 for _, _, dps in spec_map.values() if dps)
    print(f"Spec map loaded: {dps_spec_count} DPS specs recognized")

    zone = fetch_zone(ZONE_ID)
    encounters = zone["encounters"]
    print(f"Zone: {zone['name']} ({len(encounters)} encounters)")

    out_path = OUT_DIR / f"rankings_zone{ZONE_ID}_mythic_dps_top{TOP_N}.csv"
    total_rows = 0
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "encounter_id", "encounter_name", "class", "spec", "rank",
            "character", "guild", "server", "region",
            "dps", "item_level", "duration_ms",
            "report_id", "fight_id", "start_time",
        ])

        for enc in encounters:
            print(f"\n  {enc['name']} (id={enc['id']})")
            try:
                raw = fetch_boss_rankings(enc["id"])
            except Exception as e:
                print(f"    ! failed: {e}")
                continue
            print(f"    fetched {len(raw)} rankings")

            per_spec: dict[tuple[int, int], list[dict]] = {}
            for r in raw:
                key = (r.get("class"), r.get("spec"))
                meta = spec_map.get(key)
                if not meta or not meta[2]:
                    continue
                per_spec.setdefault(key, []).append(r)

            for key, ranks in sorted(per_spec.items()):
                cls_name, spec_name, _ = spec_map[key]
                take = ranks[:TOP_N]
                for i, r in enumerate(take, 1):
                    w.writerow([
                        enc["id"], enc["name"], cls_name, spec_name, i,
                        r.get("name"),
                        r.get("guildName") or r.get("guild"),
                        r.get("serverName") or r.get("server"),
                        r.get("regionName") or r.get("region"),
                        r.get("total"), r.get("itemLevel"), r.get("duration"),
                        r.get("reportID"), r.get("fightID"), r.get("startTime"),
                    ])
                total_rows += len(take)
                if len(take) < TOP_N:
                    print(f"    {cls_name}/{spec_name}: only {len(take)} entries")
            time.sleep(SLEEP)

    print(f"\nDone. {total_rows} rows -> {out_path}")


if __name__ == "__main__":
    main()
