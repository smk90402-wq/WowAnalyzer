# 같은 주차 자연실험: 탑30 각각의 킬 날짜 vs 풀타임 dps — 주차 인플레 기울기 추정
# + 7/2 킬(最高的山) vs 만터리(6/30, 7/7) 직접 비교
import datetime
import statistics
from wcl_v2 import WCLV2
from wcl_v2_data import V2Data

Q_TOP = """
query($encounterId: Int!, $difficulty: Int!, $cls: String!, $spec: String!, $partition: Int!, $page: Int!) {
  worldData { encounter(id: $encounterId) {
    characterRankings(metric: dps, difficulty: $difficulty,
      className: $cls, specName: $spec, page: $page, partition: $partition) } }
}
"""
v2 = V2Data()
data = v2.cli.query(Q_TOP, {"encounterId": 3183, "difficulty": 5, "cls": "Hunter",
                            "spec": "BeastMastery", "partition": 3, "page": 1})
ranks = ((((data.get("worldData") or {}).get("encounter") or {})
          .get("characterRankings") or {}).get("rankings") or [])

rows = []
for row in ranks[:30]:
    rep = row.get("report") or {}
    code, fid, char = rep.get("code"), rep.get("fightID"), row.get("name")
    ts = row.get("startTime")
    if not code or not ts:
        continue
    meta = v2.report_meta(code)
    f = next((x for x in (meta or {}).get("fights", []) if x.get("id") == int(fid)), None)
    table = v2.damage_table(code, int(fid), char)
    if not f or not table:
        continue
    dur = (f["endTime"] - f["startTime"]) / 1000.0
    total = sum(int(e.get("total") or 0) for e in table)
    dt = datetime.datetime.fromtimestamp(ts / 1000)
    rows.append((dt, char, total / dur, row.get("amount")))

rows.sort()
print("날짜순 탑30 (풀타임 dps):")
for dt, char, dps, amt in rows:
    print(f"  {dt:%m-%d} {char[:14]:14s} {dps:8,.0f} (랭킹 {float(amt or 0):,.0f})")

# 주차 그룹 평균
def week_of(dt):
    # 수요일 리셋 기준 근사: 7/1 주, 7/8 주, 7/15 주, 7/22 주
    if dt < datetime.datetime(2026, 7, 8):
        return "7/01주"
    if dt < datetime.datetime(2026, 7, 15):
        return "7/08주"
    if dt < datetime.datetime(2026, 7, 22):
        return "7/15주"
    return "7/22주"

from collections import defaultdict
wk = defaultdict(list)
for dt, char, dps, _ in rows:
    wk[week_of(dt)].append(dps)
print()
print("주차별 탑 파스 풀타임 dps 중앙값:")
for k in ("7/01주", "7/08주", "7/15주", "7/22주"):
    if wk.get(k):
        print(f"  {k}: {statistics.median(wk[k]):,.0f} (n={len(wk[k])})")
print()
print("만터리: 6/30 킬 147,724 / 7/7 킬 142,336 (풀타임)")
