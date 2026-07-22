# 탑30 BM 파스의 킬 날짜 분포 — 만터리 킬(7/1, 7/8)과의 주차 차이 확인
import datetime
from collections import Counter
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
print("첫 행 키:", sorted((ranks[0] or {}).keys()) if ranks else None)
weeks = Counter()
for i, row in enumerate(ranks[:30], 1):
    ts = row.get("startTime")
    if not ts:
        # report 안에 있을 수도
        ts = (row.get("report") or {}).get("startTime")
    if ts:
        dt = datetime.datetime.fromtimestamp(ts / 1000)
        weeks[dt.strftime("%m/%d(%a)")[:5]] += 1
        if i <= 10:
            print(f"  #{i} {row.get('name','')[:12]:12s} {dt:%Y-%m-%d %H:%M}")
print()
print("날짜 분포:", dict(sorted(weeks.items())))
for label, ts in (("만터리 킬1", 1782821550751), ("만터리 킬2", 1783435538779)):
    print(label, datetime.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M"))
