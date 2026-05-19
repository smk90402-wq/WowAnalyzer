"""Pre-pull buff (음식/영약/오일/숫돌) 일괄 사전 페치.

primary 5스펙 × 9보스 × top N 캐릭터에 대해 pre_pull_buffs() 호출.
캐시: data/v2_cache_prepull_buffs.json.

ThreadPoolExecutor 병렬 — Platinum 18k pts/hr 안 충분.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from wcl_v2_data import V2Data

DATA = Path(__file__).parent / "data"
CSV = DATA / "rankings_with_talents.csv"

PRIMARY_TARGETS = {
    ("Warlock", "Demonology"),
    ("Druid",   "Balance"),
    ("Hunter",  "Beast Mastery"),
    ("Warrior", "Arms"),
    ("Warrior", "Fury"),
}
TOP_N = 3   # 보스/스펙 당 상위 N명


def main() -> None:
    df = pd.read_csv(CSV, low_memory=False)
    df["report_id"] = df["report_id"].astype(str)
    df["fight_id"] = df["fight_id"].astype(int)
    sub = df[df.apply(lambda r: (r["class"], r["spec"]) in PRIMARY_TARGETS, axis=1)]
    # 보스 × 스펙 별 top N
    sub = (sub.sort_values(["encounter_id", "class", "spec", "rank"])
              .groupby(["encounter_id", "class", "spec"]).head(TOP_N)
              .reset_index(drop=True))
    print(f"target chars: {len(sub)}")

    d = V2Data()
    rate = d.cli.points_left() or {}
    print(f"start rate: {rate}")

    fetched = cached = failed = 0
    work = [(str(r["report_id"]), int(r["fight_id"]), str(r["character"]))
            for _, r in sub.iterrows()]

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(d.pre_pull_buffs, *args): args for args in work}
        for fut in as_completed(futures):
            args = futures[fut]
            try:
                res = fut.result()
            except Exception as e:
                print(f"  fail {args}: {e}")
                failed += 1
                continue
            if res is None:
                failed += 1
            elif isinstance(res, list):
                fetched += 1
            done = fetched + cached + failed
            if done % 25 == 0:
                d.flush()
                rate = d.cli.points_left() or {}
                print(f"  {done}/{len(work)}  ok={fetched} fail={failed}  "
                      f"rate={rate.get('pointsSpentThisHour', '?')}/18000")
            time.sleep(0.02)

    d.flush()
    print(f"\nDone. ok={fetched} fail={failed}")
    rate = d.cli.points_left() or {}
    print(f"end rate: {rate}")


if __name__ == "__main__":
    main()
