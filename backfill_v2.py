"""V2 GraphQL 로 target 스펙들의 신규 rankings 디테일 백필.

타깃 (5스펙): 악마흑마 · 조화드루 · 야수냥꾼 · 무기전사 · 분노전사

V2Data 가 단일 fight 당 두 콜 (playerDetails + events)로
talents/gear/casts/buffs 다 가져옴. Platinum 18k pts/hr 에서
~4500 rows × ~7 pts = ~31k pts ≈ 1.8시간 (rate limit 끼면 더)

기존 V1 cache 는 그대로 두고 V2 캐시 (v2_cache_*) 에만 적재.
"""
from __future__ import annotations

import os
import shutil
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
PRINT_EVERY = 25
FLUSH_EVERY = 5000
MIN_FREE_GB = int(os.environ.get("LOGANALYZE_MIN_FREE_GB", "50"))
LOCK_FILE = DATA / ".backfill_v2.lock"

# 풀 데이터 (talents + gear + casts + buffs)
PRIMARY_TARGETS = {
    ("Warlock", "Demonology"),
    ("Druid",   "Balance"),
    ("Hunter",  "Beast Mastery"),
    ("Hunter",  "Marksmanship"),
    ("Hunter",  "Survival"),
    ("Warrior", "Arms"),
    ("Warrior", "Fury"),
}
# 트리 분석 비교용 — talents 만 필요 (같은 클래스 다른 DPS 스펙)
TREE_COMP_TARGETS = {
    ("Warlock", "Affliction"),
    ("Warlock", "Destruction"),
    ("Druid",   "Feral"),
}
TARGETS = PRIMARY_TARGETS | TREE_COMP_TARGETS


def _free_gb(path: Path) -> float:
    usage = shutil.disk_usage(path)
    return usage.free / (1024 ** 3)


def _check_free_space(path: Path = DATA) -> None:
    free = _free_gb(path)
    if free < MIN_FREE_GB:
        raise SystemExit(
            f"Refusing to run: only {free:.1f}GB free under {path}. "
            f"Need at least {MIN_FREE_GB}GB. Set LOGANALYZE_MIN_FREE_GB "
            "if you intentionally want a different limit."
        )


def _acquire_lock() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(f"Another backfill appears to be running: {LOCK_FILE}")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"pid={os.getpid()}\nstarted={time.time()}\n")


def _release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


def main(limit: int | None = None, all_specs: bool = False,
         per_spec: int | None = None, missing_only: bool = False,
         max_new: int | None = None, pf_all: bool = False,
         no_events: bool = False) -> None:
    _check_free_space()
    _acquire_lock()
    try:
        _main(limit, all_specs=all_specs, per_spec=per_spec,
              missing_only=missing_only, max_new=max_new,
              pf_all=pf_all, no_events=no_events)
    finally:
        _release_lock()


def _main(limit: int | None = None, all_specs: bool = False,
          per_spec: int | None = None, missing_only: bool = False,
          max_new: int | None = None, pf_all: bool = False,
          no_events: bool = False) -> None:
    df = pd.read_csv(CSV)
    df["report_id"] = df["report_id"].astype(str)
    df["fight_id"] = df["fight_id"].astype(int)
    if all_specs or pf_all:
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
    scanned = work = 0
    for _, row in sub.iterrows():
        scanned += 1
        rid = row["report_id"]; fid = int(row["fight_id"]); char = row["character"]
        cls = row["class"]; spec = row["spec"]
        pf_key = f"{rid}:{fid}:{char}"
        needs_events = (not no_events) and (all_specs or (cls, spec) in PRIMARY_TARGETS)
        cached_pf = d.pfight.get(pf_key)
        if missing_only and isinstance(cached_pf, dict):
            sid = cached_pf.get("sourceID")
            ev_key = f"{rid}:{fid}:{sid}" if sid is not None else None
            if not needs_events or (ev_key and ev_key in d.events):
                continue
        if max_new is not None and work >= max_new:
            break
        work += 1
        # playerDetails (talents + gear) — 항상
        pf = d.player_fight(rid, fid, char)
        if pf:
            pf_new += 1
        else:
            pf_fail += 1

        # events (casts + buffs) — all_specs 면 전원, 아니면 primary 만
        if needs_events:
            ev = d.events_for(rid, fid, char)
            if ev:
                ev_new += 1
            else:
                ev_fail += 1
        else:
            ev_skip += 1

        if work % FLUSH_EVERY == 0:
            d.flush()
        if work % PRINT_EVERY == 0:
            rate = d.cli.points_left() or {}
            print(f"  scanned={scanned}/{len(sub)} work={work}  pf={pf_new}/{pf_fail}f  ev={ev_new}/{ev_fail}f/skip{ev_skip}  "
                  f"rate={rate.get('pointsSpentThisHour', '?'):.1f}/{rate.get('limitPerHour', '?')}")
        time.sleep(0.05)
        if work % PRINT_EVERY == 0:
            _check_free_space()

    d.flush()
    rate = d.cli.points_left()
    print(f"\nDone. pf_succ={pf_new}  ev_succ={ev_new}  ev_skip={ev_skip}  fails: pf={pf_fail} ev={ev_fail}")
    print(f"end rate: {rate}")

    # PC 간 sync 용 history 한 줄
    try:
        from update_log import record
        record(
            action="backfill_v2",
            params={"limit": limit, "processed": work, "scanned": scanned,
                    "missing_only": missing_only, "max_new": max_new,
                    "pf_all": pf_all, "no_events": no_events},
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
    missing_only = False; max_new = None
    pf_all = False; no_events = False
    args = sys.argv[1:]; i = 0
    while i < len(args):
        a = args[i]
        if a == "--all":
            all_specs = True; i += 1
        elif a == "--per-spec":
            per_spec = int(args[i + 1]); i += 2
        elif a == "--missing-only":
            missing_only = True; i += 1
        elif a == "--max-new":
            max_new = int(args[i + 1]); i += 2
        elif a == "--pf-all":
            pf_all = True; i += 1
        elif a == "--no-events":
            no_events = True; i += 1
        else:
            lim = int(a); i += 1
    main(lim, all_specs=all_specs, per_spec=per_spec,
         missing_only=missing_only, max_new=max_new,
         pf_all=pf_all, no_events=no_events)
