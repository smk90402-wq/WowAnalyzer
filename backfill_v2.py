"""V2 GraphQL 로 target 스펙들의 신규 rankings 디테일 백필.

타깃 (5스펙): 악마흑마 · 조화드루 · 야수냥꾼 · 무기전사 · 분노전사

V2Data 가 단일 fight 당 두 콜 (playerDetails + events)로
talents/gear/casts/buffs 다 가져옴. Platinum 18k pts/hr 에서
~4500 rows × ~7 pts = ~31k pts ≈ 1.8시간 (rate limit 끼면 더)

기존 V1 cache 는 그대로 두고 V2 캐시 (v2_cache_*) 에만 적재.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from wcl_v2_data import V2Data

DATA = Path(__file__).parent / "data"
CSV = DATA / "rankings_zone46_mythic_dps_top100.csv"

# 풀 데이터 (talents + gear + casts + buffs)
PRIMARY_TARGETS = {
    ("Warlock", "Demonology"),
    ("Druid",   "Balance"),
    ("Hunter",  "Beast Mastery"),
    ("Warrior", "Arms"),
    ("Warrior", "Fury"),
}
# 트리 분석 비교용 — talents 만 필요 (같은 클래스 다른 DPS 스펙)
TREE_COMP_TARGETS = {
    ("Warlock", "Affliction"),
    ("Warlock", "Destruction"),
    ("Druid",   "Feral"),
    ("Hunter",  "Marksmanship"),
    ("Hunter",  "Survival"),
}
TARGETS = PRIMARY_TARGETS | TREE_COMP_TARGETS


def main(limit: int | None = None) -> None:
    df = pd.read_csv(CSV)
    df["report_id"] = df["report_id"].astype(str)
    df["fight_id"] = df["fight_id"].astype(int)
    sub = df[df.apply(lambda r: (r["class"], r["spec"]) in TARGETS, axis=1)].copy()
    sub = sub.sort_values(["encounter_name", "class", "spec", "rank"]).reset_index(drop=True)
    if limit is not None:
        sub = sub.head(limit)

    print(f"target rows: {len(sub)}")
    d = V2Data()
    print(f"start rate: {d.cli.points_left()}")

    pf_new = pf_fail = 0
    ev_new = ev_fail = ev_skip = 0
    for i, (_, row) in enumerate(sub.iterrows(), 1):
        rid = row["report_id"]; fid = int(row["fight_id"]); char = row["character"]
        cls = row["class"]; spec = row["spec"]
        # playerDetails (talents + gear) — 항상
        pf = d.player_fight(rid, fid, char)
        if pf:
            pf_new += 1
        else:
            pf_fail += 1

        # events (casts + buffs) — primary 만
        if (cls, spec) in PRIMARY_TARGETS:
            ev = d.events_for(rid, fid, char)
            if ev:
                ev_new += 1
            else:
                ev_fail += 1
        else:
            ev_skip += 1

        if i % 25 == 0:
            d.flush()
            rate = d.cli.points_left() or {}
            print(f"  {i}/{len(sub)}  pf={pf_new}/{pf_fail}f  ev={ev_new}/{ev_fail}f/skip{ev_skip}  "
                  f"rate={rate.get('pointsSpentThisHour', '?'):.1f}/{rate.get('limitPerHour', '?')}")
        time.sleep(0.05)

    d.flush()
    rate = d.cli.points_left()
    print(f"\nDone. pf_succ={pf_new}  ev_succ={ev_new}  ev_skip={ev_skip}  fails: pf={pf_fail} ev={ev_fail}")
    print(f"end rate: {rate}")


if __name__ == "__main__":
    lim = None
    if len(sys.argv) > 1:
        try:
            lim = int(sys.argv[1])
        except ValueError:
            sys.exit(f"bad limit: {sys.argv[1]}")
    main(lim)
