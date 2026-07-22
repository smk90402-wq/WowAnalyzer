# 1265063 '피의 광란' = 12.0 블러드인지 검증: 지속시간 + 탑30 발동 시각/횟수
import statistics
from wcl_v2 import WCLV2
from wcl_v2_data import V2Data

CAND = 1265063
Q_TOP = """
query($encounterId: Int!, $difficulty: Int!, $cls: String!, $spec: String!, $partition: Int!, $page: Int!) {
  worldData { encounter(id: $encounterId) {
    characterRankings(metric: dps, difficulty: $difficulty,
      className: $cls, specName: $spec, page: $page, partition: $partition) } }
}
"""

v2 = V2Data()


def windows(code, fid, char):
    pf = v2.player_fight(code, int(fid), char)
    if not pf:
        return None
    ev = v2.events.get(f"{code}:{fid}:{pf.get('sourceID')}")
    meta = v2.report_meta(code)
    if not ev or not meta:
        return None
    f = next((x for x in meta["fights"] if x["id"] == int(fid)), None)
    start = f["startTime"]
    on = None
    spans = []
    for rec in ev.get("buffs") or []:
        if rec[1] != CAND:
            continue
        t = round((rec[0] - start) / 1000, 1)
        if rec[2] == "applybuff":
            on = t
        elif rec[2] == "removebuff" and on is not None:
            spans.append((on, t, round(t - on, 1)))
            on = None
    return spans


print("만터리:")
for code, fid in (("8bcN17hKrMtmTGDB", 15), ("BtADGd3RkJy6gb4f", 10)):
    print(" ", code, windows(code, fid, "만터리"))

data = v2.cli.query(Q_TOP, {"encounterId": 3183, "difficulty": 5, "cls": "Hunter",
                            "spec": "BeastMastery", "partition": 3, "page": 1})
ranks = ((((data.get("worldData") or {}).get("encounter") or {})
          .get("characterRankings") or {}).get("rankings") or [])
firsts = []
counts = []
n = 0
for row in ranks:
    if n >= 30:
        break
    rep = row.get("report") or {}
    if not rep.get("code"):
        continue
    sp = windows(rep["code"], rep["fightID"], row.get("name"))
    if sp is None:
        continue
    counts.append(len(sp))
    if sp:
        firsts.append(sp[0][0])
    if n < 6:
        print(f"top {row.get('name','')[:12]}: {sp}")
    n += 1
print(f"탑30: 발동 있는 표본 {sum(1 for c in counts if c)}/{len(counts)}, "
      f"첫 발동 중앙값 {statistics.median(firsts):.0f}s ({min(firsts):.0f}~{max(firsts):.0f})"
      if firsts else "탑30: 발동 없음")
