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


def main(limit: int | None = None, all_specs: bool = False,
         per_spec: int | None = None) -> None:
    df = pd.read_csv(CSV)
    df["report_id"] = df["report_id"].astype(str)
    df["fight_id"] = df["fight_id"].astype(int)
    if all_specs:
        # 전 스펙 — 로테 난이도용 casts 필요. events 도 전원 페치.
        sub = df.copy()
    else:
        sub = df[df.apply(lambda r: (r["class"], r["spec"]) in TARGETS, axis=1)].copy()
    sub = sub.sort_values(["encounter_name", "class", "spec", "rank"]).reset_index(drop=True)
    # 스펙당 상위 N 만 (로테 난이도는 ~100이면 통계적으로 충분, 풀의 6배 비용 회피)
    if per_spec is not None:
        sub = (sub.sort_values("rank")
               .groupby(["class", "spec"], group_keys=False)
               .head(per_spec)
               .reset_index(drop=True))
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

        # events (casts + buffs) — all_specs 면 전원, 아니면 primary 만
        if all_specs or (cls, spec) in PRIMARY_TARGETS:
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

    # PC 간 sync 용 history 한 줄
    try:
        from update_log import record
        record(
            action="backfill_v2",
            params={"limit": limit, "processed": len(sub)},
            result={"pf_new": pf_new, "pf_fail": pf_fail,
                    "ev_new": ev_new, "ev_fail": ev_fail, "ev_skip": ev_skip,
                    "rate_end": rate.get("pointsSpentThisHour") if rate else None},
            files=["data/v2_cache_player_fight.json",
                   "data/v2_cache_events.json"],
        )
    except Exception as e:
        print(f"[update_log] skip: {e}")


if __name__ == "__main__":
    # 사용:
    #   python backfill_v2.py            # 5 타깃 스펙 (기존)
    #   python backfill_v2.py --all      # 전 스펙 casts+buffs (로테 난이도용)
    #   python backfill_v2.py --all --per-spec 150  # 스펙당 상위 150
    #   python backfill_v2.py 200        # 앞 200행만 (파일럿)
    lim = None; all_specs = False; per_spec = None
    args = sys.argv[1:]; i = 0
    while i < len(args):
        a = args[i]
        if a == "--all":
            all_specs = True; i += 1
        elif a == "--per-spec":
            per_spec = int(args[i + 1]); i += 2
        else:
            lim = int(a); i += 1
    main(lim, all_specs=all_specs, per_spec=per_spec)
