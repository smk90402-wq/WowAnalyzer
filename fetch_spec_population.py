"""스펙별 모집단(인구) 정밀 페치 — 파스 난이도 지표용.

논리: 파스%는 백분위라, 모집단에 '깔아주는' 약한 플레이어가 많을수록
(=인구 많고 진입장벽 낮을수록) 평균이상 실력자가 고파스 따기 쉬움.
인구 적은 스펙 = 고인물만 남음 = 백분위 경쟁 빡셈.

각 스펙의 마지막 페이지를 이진탐색으로 찾아 인구 = (lastpage-1)*100 + lastcount.
여러 보스 평균내서 노이즈 감소. data/spec_population.csv 저장.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import pandas as pd
from wcl_v2 import WCLV2

DATA = Path(__file__).parent / "data"
DIFF = 5      # mythic
PT = 2        # 12.0.5
# 인구 측정용 보스 3개 (초반 쉬운 보스 = 인구 많음, 대표성)
BOSSES = [3176, 3181, 3179]   # 아베르지안, 우주의왕관, 살라다르
MAXPAGE = 20   # WCL 하드캡: ranking 은 page20(=2000개)에서 잘림. 2000=상위인기(캡), <2000=정확.

SPECS = [
    ("Mage", "Frost", "냉마"), ("Mage", "Fire", "화염"), ("Mage", "Arcane", "비전"),
    ("Hunter", "BeastMastery", "야수"), ("Hunter", "Marksmanship", "사격"),
    ("Hunter", "Survival", "생존"), ("DemonHunter", "Devourer", "포식"),
    ("DemonHunter", "Havoc", "파멸"), ("Warlock", "Demonology", "악마"),
    ("Warlock", "Destruction", "파괴"), ("Warlock", "Affliction", "고통"),
    ("Priest", "Shadow", "암흑"), ("Druid", "Balance", "조화"), ("Druid", "Feral", "야성"),
    ("Evoker", "Devastation", "황폐"), ("Evoker", "Augmentation", "증강"),
    ("DeathKnight", "Unholy", "부정"), ("DeathKnight", "Frost", "냉죽"),
    ("Shaman", "Elemental", "정기"), ("Shaman", "Enhancement", "고양"),
    ("Monk", "Windwalker", "풍운"), ("Rogue", "Assassination", "암살"),
    ("Rogue", "Outlaw", "무법"), ("Rogue", "Subtlety", "잠행"),
    ("Paladin", "Retribution", "징벌"), ("Warrior", "Arms", "무기"), ("Warrior", "Fury", "분노"),
]
Q = """query($e:Int!,$d:Int!,$pt:Int!,$p:Int!,$cn:String!,$sn:String!){worldData{encounter(id:$e){
  characterRankings(metric:dps,className:$cn,specName:$sn,difficulty:$d,partition:$pt,page:$p)}}}"""


def page_info(cli, eid, cn, sn, p):
    d = cli.query(Q, {"e": eid, "d": DIFF, "pt": PT, "p": p, "cn": cn, "sn": sn})
    o = (((d or {}).get("worldData") or {}).get("encounter") or {}).get("characterRankings") or {}
    return bool(o.get("hasMorePages")), len(o.get("rankings") or [])


def population(cli, eid, cn, sn):
    """이진탐색으로 마지막 페이지 찾기."""
    # 먼저 page1 비어있나
    more, cnt = page_info(cli, eid, cn, sn, 1)
    if cnt == 0:
        return 0
    if not more:
        return cnt
    # 지수로 상한 찾기
    lo, hi = 1, 2
    while hi <= MAXPAGE:
        more, cnt = page_info(cli, eid, cn, sn, hi)
        if not more:
            break
        lo = hi
        hi *= 2
        time.sleep(0.02)
    if hi > MAXPAGE:
        return MAXPAGE * 100
    # lo(있음) ~ hi(마지막) 사이 이진탐색
    last = hi
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        more, cnt = page_info(cli, eid, cn, sn, mid)
        if more:
            lo = mid
        else:
            hi = mid
            last = mid
        time.sleep(0.02)
    _, lastcnt = page_info(cli, eid, cn, sn, last)
    return (last - 1) * 100 + lastcnt


def main():
    cli = WCLV2()
    rate0 = (cli.points_left() or {}).get("pointsSpentThisHour", 0)
    rows = []
    for cn, sn, kr in SPECS:
        pops = []
        for eid in BOSSES:
            try:
                pops.append(population(cli, eid, cn, sn))
            except Exception as ex:
                print(f"  {kr} boss{eid} 실패: {str(ex)[:40]}", flush=True)
            time.sleep(0.02)
        avg = sum(pops) / len(pops) if pops else 0
        rows.append({"class": cn, "spec": sn, "kr": kr,
                     "pop_avg": round(avg), "pops": ",".join(map(str, pops))})
        print(f"  {kr:<6} 평균 ~{avg:,.0f}명  ({pops})", flush=True)
    df = pd.DataFrame(rows).sort_values("pop_avg", ascending=False)
    df.to_csv(DATA / "spec_population.csv", index=False, encoding="utf-8")
    rate1 = (cli.points_left() or {}).get("pointsSpentThisHour", 0)
    print(f"\n저장 spec_population.csv · 점수 {rate1 - rate0:.0f}")
    print("최다:", ", ".join(df.head(3)["kr"]), "| 최소:", ", ".join(df.tail(3)["kr"]))


if __name__ == "__main__":
    main()
