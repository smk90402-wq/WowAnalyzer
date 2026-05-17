"""Top100 의 장비 세팅을 캐싱.

`/v1/report/tables/summary/{rid}?start=&end=` 의 playerDetails.{dps,tanks,healers}[]
.combatantInfo.gear 에 슬롯별 아이템이 들어있다. 각 아이템 객체엔:
  - id            : 아이템 ID
  - slot          : 슬롯 인덱스 (0=머리 ~ 18=옵)
  - name, icon
  - itemLevel
  - quality
  - gems          : [{id, itemLevel}, ...]
  - permanentEnchant, permanentEnchantName
  - temporaryEnchant 등
  - bonusIDs      : [int, ...]  (장식·특보 같은 거 식별)

저장 포맷 (간결화):
  cache_gear.json: {
    "rid:fid": {
      char_name: {
        "ilvl": int,           # combatantInfo.gear 평균 itemLevel
        "gear": [
          {"slot": int, "id": int, "name": str, "ilvl": int,
           "gems": [int, ...], "ench": int|null, "bonus": [int, ...]},
          ...
        ]
      },
      ...
    }
  }

기본은 타깃 3스펙(악마/조화/야수)의 ranking row 들만 처리. 풀로 돌리려면
`python enrich_gear.py all`.

cache_fights.json 의 fight window 를 그대로 재사용.
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
CACHE_GEAR = DATA / "cache_gear.json"

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
cache_gear: dict = load_json(CACHE_GEAR)


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


def compact_item(item: dict) -> dict:
    """gear 엔트리 하나를 분석에 필요한 필드만 남긴 dict 로."""
    gems = item.get("gems") or []
    return {
        "slot": item.get("slot"),
        "id":   item.get("id"),
        "name": item.get("name") or "",
        "ilvl": item.get("itemLevel"),
        "gems": [g.get("id") for g in gems if isinstance(g, dict) and g.get("id")],
        "ench": item.get("permanentEnchant"),
        "bonus": list(item.get("bonusIDs") or []),
    }


def fetch_gear(rid: str, fid: int, start: int, end: int) -> dict | None:
    """{char_name: {ilvl, gear:[...]}} for the fight, cached."""
    key = f"{rid}:{fid}"
    if key in cache_gear:
        return cache_gear[key]
    data = api_get(
        f"{BASE}/report/tables/summary/{rid}",
        {"start": start, "end": end},
    )
    if data is None:
        cache_gear[key] = None
        return None
    pd_ = data.get("playerDetails", {}) or {}
    out: dict[str, dict] = {}
    for role in ("dps", "tanks", "healers"):
        for p in pd_.get(role, []) or []:
            name = p.get("name")
            ci = p.get("combatantInfo") or {}
            gear = ci.get("gear") or []
            if not name or not isinstance(gear, list) or not gear:
                continue
            compact = [compact_item(it) for it in gear if isinstance(it, dict)]
            ilvls = [c["ilvl"] for c in compact if isinstance(c.get("ilvl"), int)]
            avg = round(sum(ilvls) / len(ilvls), 1) if ilvls else None
            out[name] = {"ilvl": avg, "gear": compact}
    cache_gear[key] = out
    return out


def main() -> None:
    if not CSV_IN.exists():
        sys.exit(f"입력 없음: {CSV_IN}")
    if not cache_fights:
        sys.exit("cache_fights.json 비어있음. enrich_pi.py 먼저 돌려.")

    full = len(sys.argv) > 1 and sys.argv[1].lower() == "all"
    df = pd.read_csv(CSV_IN)
    df["report_id"] = df["report_id"].astype(str)
    df["fight_id"] = df["fight_id"].astype(int)

    if not full:
        df = df[df.apply(lambda r: (r["class"], r["spec"]) in TARGETS, axis=1)]
    pairs = df[["report_id", "fight_id"]].drop_duplicates()
    print(f"{'전체 스펙' if full else '타깃 3스펙'}  (report,fight) pairs: {len(pairs)}")

    todo = []
    for rid, fid in pairs.itertuples(index=False):
        key = f"{rid}:{fid}"
        if key in cache_gear:
            continue
        fights = cache_fights.get(rid) or {}
        window = fights.get(str(fid))
        if not window:
            cache_gear[key] = None
            continue
        todo.append((rid, int(fid), int(window[0]), int(window[1])))
    print(f"가져올 fight: {len(todo)}  (캐시됨: {len(pairs) - len(todo)})")

    for i, (rid, fid, s, e) in enumerate(todo, 1):
        fetch_gear(rid, fid, s, e)
        if i % 50 == 0:
            save_json(CACHE_GEAR, cache_gear)
            print(f"    {i}/{len(todo)}")
        time.sleep(SLEEP)
    save_json(CACHE_GEAR, cache_gear)

    # 커버리지
    covered = 0
    total_items = 0
    distinct_items: set[int] = set()
    for _, row in df.iterrows():
        rid = row["report_id"]; fid = int(row["fight_id"]); char = row["character"]
        entry = cache_gear.get(f"{rid}:{fid}")
        if isinstance(entry, dict) and char in entry:
            covered += 1
            for it in entry[char].get("gear", []):
                total_items += 1
                if isinstance(it.get("id"), int):
                    distinct_items.add(it["id"])
    print(f"\nrankings rows with gear: {covered}/{len(df)} "
          f"({100*covered/max(1,len(df)):.1f}%)")
    print(f"distinct item IDs captured: {len(distinct_items)}")


if __name__ == "__main__":
    main()
