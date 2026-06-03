"""야수냥꾼 경합보스 깊은 분석 — top 600 까지 받아서 단일/광 빌드 × 킬타임 비교.

아베르지안(3176)·살라다르(3179): top-100 단일표본이 2~7판뿐이라 얇음.
깊은 페이지(top 600) 받아 킬타임 구간별로 단일 vs 광 median DPS 비교.

회전베기 node=102341 채택=광빌드, 미채택=단일빌드.
결과: data/bm_build_killtime.csv + 콘솔 요약.
"""
from __future__ import annotations
import sys, time, json
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import pandas as pd, numpy as np
from wcl_v2 import WCLV2
from wcl_v2_data import V2Data

DATA = Path(__file__).parent / "data"
BC = 102341
PARTITION = 2          # 12.0.5
DIFF = 5               # mythic
PAGES = 6             # top ~600
TARGETS = {3176: "아베르지안", 3179: "살라다르", 3306: "카이메루스"}
WINDOW = (150, 380)    # 킬타임 관심 구간(s)

Q = """query($e:Int!,$p:Int!,$d:Int!,$pt:Int!){worldData{encounter(id:$e){
characterRankings(metric:dps,className:"Hunter",specName:"BeastMastery",difficulty:$d,page:$p,partition:$pt)}}}"""


def main():
    cli = WCLV2()
    d = V2Data(data_dir=DATA)
    rate0 = cli.points_left() or {}
    rows = []
    for eid, nm in TARGETS.items():
        print(f"\n=== {nm}({eid}) 랭킹 수집 ===", flush=True)
        entries = []
        for pg in range(1, PAGES + 1):
            try:
                data = cli.query(Q, {"e": eid, "p": pg, "d": DIFF, "pt": PARTITION})
            except Exception as ex:
                print(f"  page {pg} 실패: {str(ex)[:80]}"); break
            obj = (((data or {}).get("worldData") or {}).get("encounter") or {}).get("characterRankings") or {}
            rk = obj.get("rankings") or []
            entries += rk
            if not obj.get("hasMorePages"): break
            time.sleep(0.05)
        print(f"  {len(entries)}판 수집. 빌드 페치(킬타임 {WINDOW[0]}~{WINDOW[1]}s만)...", flush=True)
        done = 0
        for r in entries:
            dur = (r.get("duration") or 0) / 1000
            if not (WINDOW[0] <= dur <= WINDOW[1]):
                continue
            rep = r.get("report") or {}
            rid = rep.get("code"); fid = rep.get("fightID"); char = r.get("name")
            dps = r.get("amount")
            if not (rid and fid and char and dps):
                continue
            try:
                pf = d.player_fight(rid, int(fid), char)
            except Exception:
                pf = None
            if not isinstance(pf, dict):
                continue
            has_bc = BC in set(pf.get("nodes") or [])
            rows.append({"boss": nm, "enc": eid, "dur": dur, "dps": dps, "bc": has_bc})
            done += 1
            if done % 50 == 0:
                d.flush()
                rate = cli.points_left() or {}
                print(f"    {done} 빌드 확보  rate={rate.get('pointsSpentThisHour','?')}/18000", flush=True)
            time.sleep(0.03)
        print(f"  → 빌드 확보 {done}판", flush=True)
    d.flush()
    df = pd.DataFrame(rows)
    df.to_csv(DATA / "bm_build_killtime.csv", index=False, encoding="utf-8")
    rate1 = cli.points_left() or {}
    print(f"\n총 {len(df)}판. 점수 {rate1.get('pointsSpentThisHour',0)-rate0.get('pointsSpentThisHour',0):.0f}", flush=True)

    # 킬타임 구간별 단일 vs 광
    BRACKETS = [(150,200),(200,240),(240,280),(280,320),(320,380)]
    for eid, nm in TARGETS.items():
        g = df[df["enc"] == eid]
        if g.empty: continue
        print(f"\n=== {nm} — 킬타임 구간별 단일 vs 광 median DPS ===")
        print(f"{'구간(s)':<12}{'광 n/DPS':>18}{'단일 n/DPS':>18}{'단일우위':>9}")
        for lo, hi in BRACKETS:
            b = g[(g["dur"] >= lo) & (g["dur"] < hi)]
            o = b[b["bc"]]; x = b[~b["bc"]]
            os = f"{len(o)} / {o['dps'].median():,.0f}" if len(o) else f"{len(o)} / -"
            xs = f"{len(x)} / {x['dps'].median():,.0f}" if len(x) else f"{len(x)} / -"
            adv = f"{(x['dps'].median()-o['dps'].median())/o['dps'].median()*100:+.1f}%" if len(o)>=4 and len(x)>=4 else "-"
            print(f"{f'{lo}~{hi}':<12}{os:>18}{xs:>18}{adv:>9}")


if __name__ == "__main__":
    main()
