"""산왕 분노 이벤트 추출 — 프록 우선순위 실측용 (casts + buffs).

학살자는 tmp_fury_bs_events.json에 이미 있음. 산왕만 추출.
출력: data/tmp_fury_thane_events.json
"""
from __future__ import annotations
import sys, json
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import pandas as pd

DATA = Path(__file__).parent / "data"
PER = 90


def main():
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))
    THANE = set(n["id"] for n in tt["Warrior/Fury"]["hero"]["산왕"]["nodes"])
    df = pd.read_csv(DATA / "rankings_zone46_mythic_dps_top100.csv")
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))

    fu = df[(df["class"] == "Warrior") & (df["spec"] == "Fury")].sort_values("rank")
    wanted = {}
    for _, r in fu.iterrows():
        p = pf.get(f'{r["report_id"]}:{int(r["fight_id"])}:{r["character"]}')
        if not isinstance(p, dict) or p.get("sourceID") is None:
            continue
        if len(set(p.get("nodes") or []) & THANE) < 3:   # 산왕만
            continue
        wanted[f'{r["report_id"]}:{int(r["fight_id"])}:{p["sourceID"]}'] = None
        if len(wanted) >= PER:
            break

    cache = DATA / "tmp_fury_thane_events.json"
    if cache.exists():
        print("이미 추출됨"); return
    s = open(DATA / "v2_cache_events.json", encoding="utf-8").read()
    print(f"events {len(s)/1e6:.0f}MB 스캔 (산왕 {len(wanted)}명 대상)...", flush=True)
    dec = json.JSONDecoder(); ev, i, n, seen = {}, 1, len(s), 0
    while i < n:
        while i < n and s[i] in " \t\r\n,": i += 1
        if i >= n or s[i] == "}": break
        k, j = dec.raw_decode(s, i); i = j
        while s[i] in " \t\r\n:": i += 1
        v, j = dec.raw_decode(s, i); i = j
        seen += 1
        if seen % 2000 == 0: print(f"  스캔 {seen} 적중 {len(ev)}", flush=True)
        if k in wanted: ev[k] = v
    json.dump(ev, open(cache, "w", encoding="utf-8"))
    print(f"추출 {len(ev)}명 → {cache.name}", flush=True)


if __name__ == "__main__":
    main()
