# 시간 건너뛰기(404977) ↔ 영겁의 숨결(442204/403631) 연계 — 탑30 vs 우리
# 탑이 영겁 실효쿨 73초를 만드는 메커니즘: 시간 건너뛰기를 영겁 뒤 언제 넣는가
import statistics
from collections import defaultdict

from wcl_v2 import WCLV2
from wcl_v2_data import V2Data

EONS = {442204, 403631}
TIME_SKIP = 404977
Q_TOP = """
query($encounterId: Int!, $difficulty: Int!, $cls: String!, $spec: String!, $partition: Int!, $page: Int!) {
  worldData { encounter(id: $encounterId) {
    characterRankings(metric: dps, difficulty: $difficulty,
      className: $cls, specName: $spec, page: $page, partition: $partition) } }
}
"""

v2 = V2Data()
data = v2.cli.query(Q_TOP, {"encounterId": 3183, "difficulty": 5, "cls": "Evoker",
                            "spec": "Augmentation", "partition": 3, "page": 1})
ranks = ((((data.get("worldData") or {}).get("encounter") or {})
          .get("characterRankings") or {}).get("rankings") or [])


def pull_times(code, fid, char):
    pf = v2.player_fight(code, int(fid), char)
    if not pf:
        return None
    ev = v2.events.get(f"{code}:{fid}:{pf.get('sourceID')}")
    meta = v2.report_meta(code)
    if not ev or not meta:
        return None
    f = next((x for x in meta["fights"] if x["id"] == int(fid)), None)
    if not f:
        return None
    start = f["startTime"]
    eons = sorted(round((t - start) / 1000, 1) for t, gid, typ in ev.get("casts") or []
                  if typ == "cast" and gid in EONS)
    skips = sorted(round((t - start) / 1000, 1) for t, gid, typ in ev.get("casts") or []
                  if typ == "cast" and gid == TIME_SKIP)
    return eons, skips


def link_offsets(eons, skips):
    """각 시간 건너뛰기의 (직전 영겁으로부터 오프셋, 몇 번째 영겁 뒤인지)."""
    out = []
    for st in skips:
        prev = [(i + 1, e) for i, e in enumerate(eons) if e <= st]
        if prev:
            n, e = prev[-1]
            out.append((st, n, round(st - e, 1)))
    return out


print("=== 탑 시간 건너뛰기 배치 (시각 / 직전영겁 n번째 / 영겁 후 +초) ===")
top_offsets = defaultdict(list)   # n번째 영겁 뒤 → 오프셋들
top_skip_times = []
count = 0
for row in ranks:
    if count >= 30:
        break
    rep = row.get("report") or {}
    got = pull_times(rep.get("code"), rep.get("fightID"), row.get("name"))
    if not got:
        continue
    eons, skips = got
    top_skip_times.append(skips)
    links = link_offsets(eons, skips)
    if count < 8:
        print(f"  {row.get('name','')[:12]:12s} 영겁={eons[:4]}... 건너뛰기={skips} → {[(n, off) for _, n, off in links]}")
    for _, n, off in links:
        top_offsets[n].append(off)
    count += 1

print()
print("=== 탑: n번째 영겁 뒤 시간 건너뛰기 오프셋 (중앙값) ===")
for n in sorted(top_offsets):
    v = top_offsets[n]
    print(f"  영겁{n} 후 +{statistics.median(v):.0f}s (n={len(v)}, {min(v):.0f}~{max(v):.0f})")
skip_counts = [len(s) for s in top_skip_times]
print(f"  풀당 시간 건너뛰기 횟수: 중앙값 {statistics.median(skip_counts)}")

print()
print("=== 우리(하늘연달스물엿새) ===")
meta = v2.report_meta("CPA42mqBHXMyca86")
our_offsets = defaultdict(list)
for f in meta["fights"]:
    if f.get("encounterID") != 3183 or (f["endTime"] - f["startTime"]) / 1000 < 180:
        continue
    got = pull_times("CPA42mqBHXMyca86", f["id"], "하늘연달스물엿새")
    if not got:
        continue
    eons, skips = got
    links = link_offsets(eons, skips)
    print(f"  fight {f['id']}: 영겁={eons} 건너뛰기={skips} → {[(n, off) for _, n, off in links]}")
    for _, n, off in links:
        our_offsets[n].append(off)
print()
print("=== 우리: n번째 영겁 뒤 오프셋 (중앙값) ===")
for n in sorted(our_offsets):
    v = our_offsets[n]
    print(f"  영겁{n} 후 +{statistics.median(v):.0f}s (n={len(v)})")
