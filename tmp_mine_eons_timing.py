# 영겁의 숨결(442204/403631) 탑30 시전 타이밍 — 쿨마다 vs 타이밍 정렬 판별
# + WCL phaseTransitions 로 페이즈 내 위치 확인
import json
import statistics
import sys
from collections import Counter, defaultdict

from wcl_v2 import WCLV2
from wcl_v2_data import V2Data

EONS = {442204, 403631}
Q_TOP = """
query($encounterId: Int!, $difficulty: Int!, $cls: String!, $spec: String!, $partition: Int!, $page: Int!) {
  worldData { encounter(id: $encounterId) {
    characterRankings(metric: dps, difficulty: $difficulty,
      className: $cls, specName: $spec, page: $page, partition: $partition) } }
}
"""
Q_PHASES = """
query($code: String!, $fid: Int!) {
  reportData { report(code: $code) {
    fights(fightIDs: [$fid]) { id startTime endTime phaseTransitions { id startTime } }
  } }
}
"""

v2 = V2Data()
cli = v2.cli
data = cli.query(Q_TOP, {"encounterId": 3183, "difficulty": 5, "cls": "Evoker",
                         "spec": "Augmentation", "partition": 3, "page": 1})
ranks = ((((data.get("worldData") or {}).get("encounter") or {})
          .get("characterRankings") or {}).get("rankings") or [])

per_player = []      # (char, dur, [영겁 시각들], [간격들])
phase_marks = []     # 첫 표본 몇 개의 페이즈 전환 시각
gap_all = []
nth_times = defaultdict(list)

count = 0
for row in ranks:
    if count >= 30:
        break
    rep = row.get("report") or {}
    code, fid, char = rep.get("code"), rep.get("fightID"), row.get("name")
    if not code or not fid:
        continue
    pf = v2.player_fight(code, int(fid), char)
    if not pf:
        continue
    sid = pf.get("sourceID")
    ev = v2.events.get(f"{code}:{fid}:{sid}")
    meta = v2.report_meta(code)
    if not ev or not meta:
        continue
    f = next((x for x in meta["fights"] if x["id"] == int(fid)), None)
    if not f:
        continue
    start, end = f["startTime"], f["endTime"]
    times = sorted(round((t - start) / 1000, 1) for t, gid, typ in ev.get("casts") or []
                   if typ == "cast" and gid in EONS)
    gaps = [round(b - a, 1) for a, b in zip(times, times[1:])]
    gap_all.extend(gaps)
    for i, t in enumerate(times):
        nth_times[i + 1].append(t)
    per_player.append((char, round((end - start) / 1000), times, gaps))
    # 페이즈 전환: 상위 5명만 조회 (쿼리 절약)
    if len(phase_marks) < 5:
        try:
            pd_ = cli.query(Q_PHASES, {"code": code, "fid": int(fid)})
            ff = ((((pd_.get("reportData") or {}).get("report") or {})
                   .get("fights") or [{}])[0])
            pts = [(p.get("id"), round((p.get("startTime") - start) / 1000, 1))
                   for p in ff.get("phaseTransitions") or []]
            if pts:
                phase_marks.append((char, pts))
        except Exception as e:
            print("phase query fail:", e)
    count += 1

print(f"=== 탑{len(per_player)} 영겁의 숨결 시전 시각 ===")
for char, dur, times, gaps in per_player[:12]:
    print(f"  {char[:14]:14s} {dur}s: {times}  간격={gaps}")
print()
print("=== n번째 시전 시각 분포 (중앙값 / 최소~최대) ===")
for n in sorted(nth_times):
    v = nth_times[n]
    print(f"  {n}번째: n={len(v)} 중앙값 {statistics.median(v):.0f}s ({min(v):.0f}~{max(v):.0f})")
print()
print(f"=== 시전 간격 분포 (n={len(gap_all)}) ===")
if gap_all:
    s = sorted(gap_all)
    print(f"  중앙값 {statistics.median(s):.1f}s / p25 {s[len(s)//4]:.1f} / p75 {s[3*len(s)//4]:.1f} / 최소 {min(s):.1f} / 최대 {max(s):.1f}")
print()
print("=== 페이즈 전환 (상위 표본) ===")
for char, pts in phase_marks:
    print(f"  {char[:14]}: {pts}")

# 우리 하늘연달
print()
print("=== 우리(하늘연달스물엿새) ===")
meta = v2.report_meta("CPA42mqBHXMyca86")
for f in meta["fights"]:
    if f.get("encounterID") != 3183 or (f["endTime"] - f["startTime"]) / 1000 < 180:
        continue
    pf = v2.player_fight("CPA42mqBHXMyca86", f["id"], "하늘연달스물엿새")
    if not pf:
        continue
    ev = v2.events.get(f'CPA42mqBHXMyca86:{f["id"]}:{pf.get("sourceID")}')
    if not ev:
        continue
    times = sorted(round((t - f["startTime"]) / 1000, 1) for t, gid, typ in ev.get("casts") or []
                   if typ == "cast" and gid in EONS)
    gaps = [round(b - a, 1) for a, b in zip(times, times[1:])]
    print(f"  fight {f['id']} ({round((f['endTime']-f['startTime'])/1000)}s): {times} 간격={gaps}")
v2.flush()
