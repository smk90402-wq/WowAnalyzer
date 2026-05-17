"""rankings CSV 의 server/region 컬럼 backfill.

원인: 초기 fetch_rankings.py 가 'server'/'region' 이라는 필드명으로 찾았는데
실제 /rankings/encounter 응답 키는 'serverName'/'regionName'. /report/fights
의 friendlies 에는 'server'/'region' 이 있으니 거기서 채움.

API: /v1/report/fights/{rid}  — report 당 1콜, 친구목록에서 (name, server, region)
캐시: data/cache_servers.json = {rid: {char_name: {"server", "region"}}}
업데이트 대상 CSV (모두 같은 (rid, char) 키 사용):
  - rankings_zone46_mythic_dps_top100.csv
  - rankings_zone46_mythic_dps_top100_pi.csv
  - rankings_with_talents.csv
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
CACHE = DATA / "cache_servers.json"
CSVS = [
    "rankings_zone46_mythic_dps_top100.csv",
    "rankings_zone46_mythic_dps_top100_pi.csv",
    "rankings_with_talents.csv",
]


def load_json(p: Path):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_json(p: Path, obj) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


cache: dict = load_json(CACHE)


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


def fetch(rid: str) -> dict | None:
    if rid in cache:
        return cache[rid]
    data = api_get(f"{BASE}/report/fights/{rid}", {})
    if data is None:
        cache[rid] = None
        return None
    out: dict[str, dict] = {}
    for f in data.get("friendlies", []) or []:
        name = f.get("name")
        if not name:
            continue
        out[name] = {"server": f.get("server") or "", "region": f.get("region") or ""}
    cache[rid] = out
    return out


def main() -> None:
    base = pd.read_csv(DATA / CSVS[0])
    reports = base["report_id"].astype(str).unique().tolist()
    todo = [r for r in reports if r not in cache]
    print(f"reports: {len(reports)}  new: {len(todo)}  cached: {len(reports) - len(todo)}")

    for i, rid in enumerate(todo, 1):
        fetch(rid)
        if i % 50 == 0:
            save_json(CACHE, cache)
            print(f"    {i}/{len(todo)}")
        time.sleep(SLEEP)
    save_json(CACHE, cache)

    # CSV 업데이트 (in-place)
    print("\nCSV 업데이트:")
    for fname in CSVS:
        path = DATA / fname
        if not path.exists():
            print(f"  {fname}: 없음, 건너뜀")
            continue
        df = pd.read_csv(path)
        if "server" not in df.columns or "region" not in df.columns:
            print(f"  {fname}: server/region 컬럼 없음, 건너뜀")
            continue

        def lookup(row, key):
            m = cache.get(str(row["report_id"]))
            if not isinstance(m, dict):
                return ""
            return m.get(row["character"], {}).get(key, "")

        df["server"] = df.apply(lambda r: lookup(r, "server"), axis=1)
        df["region"] = df.apply(lambda r: lookup(r, "region"), axis=1)
        df.to_csv(path, index=False)
        filled = (df["server"].astype(str) != "").sum()
        print(f"  {fname}: server 채움 {filled}/{len(df)} "
              f"({100 * filled / max(1, len(df)):.1f}%)")


if __name__ == "__main__":
    main()
