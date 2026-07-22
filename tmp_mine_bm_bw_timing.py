# 야수의 격노(19574) 타이밍 — BM 탑30 vs 만터리 (한밤의 도래 신화)
# 야격/야생의 부름/물약 시전 시각 + 블러드 받은 시각(버프 스트림) 정렬 분석
import statistics
import sys
from collections import defaultdict

from wcl_v2 import WCLV2
from wcl_v2_data import V2Data

BW = 19574              # 야수의 격노
CWILD = {359844}        # 야생의 부름
POTIONS = {1234768, 1236616, 1236994, 1236998, 1238443, 431932, 453035}
LUST = {2825, 32182, 80353, 264667, 272678, 390386, 466904,
        178207, 230935, 256740, 309658, 444257}

Q_TOP = """
query($encounterId: Int!, $difficulty: Int!, $cls: String!, $spec: String!, $partition: Int!, $page: Int!) {
  worldData { encounter(id: $encounterId) {
    characterRankings(metric: dps, difficulty: $difficulty,
      className: $cls, specName: $spec, page: $page, partition: $partition) } }
}
"""
Q_CHAR_RANK = """
query($name: String!, $server: String!, $region: String!, $encounterId: Int!) {
  characterData {
    character(name: $name, serverSlug: $server, serverRegion: $region) {
      encounterRankings(encounterID: $encounterId, difficulty: 5, metric: dps)
    }
  }
}
"""

v2 = V2Data()
cli = v2.cli


def sample(code, fid, char):
    pf = v2.player_fight(code, int(fid), char)
    if not pf:
        return None
    ev = v2.events_for(code, int(fid), char)
    meta = v2.report_meta(code)
    if not ev or not meta:
        return None
    f = next((x for x in meta["fights"] if x["id"] == int(fid)), None)
    if not f:
        return None
    start, end = f["startTime"], f["endTime"]
    rel = lambda t: round((t - start) / 1000, 1)
    casts = [(t, gid) for t, gid, typ in ev.get("casts") or [] if typ == "cast"]
    bw = sorted(rel(t) for t, gid in casts if gid == BW)
    cw = sorted(rel(t) for t, gid in casts if gid in CWILD)
    pots = sorted(rel(t) for t, gid in casts if gid in POTIONS)
    lust = sorted(rel(r[0]) for r in ev.get("buffs") or []
                  if r[1] in LUST and r[2] == "applybuff")
    return {"dur": round((end - start) / 1000), "bw": bw, "cw": cw,
            "pots": pots, "lust": lust[:1]}


# ── 탑30 BM ──
data = cli.query(Q_TOP, {"encounterId": 3183, "difficulty": 5, "cls": "Hunter",
                         "spec": "BeastMastery", "partition": 3, "page": 1})
ranks = ((((data.get("worldData") or {}).get("encounter") or {})
          .get("characterRankings") or {}).get("rankings") or [])
tops = []
for row in ranks:
    if len(tops) >= 30:
        break
    rep = row.get("report") or {}
    if not rep.get("code"):
        continue
    s = sample(rep["code"], rep["fightID"], row.get("name"))
    if s:
        s["char"] = row.get("name")
        tops.append(s)
        if len(tops) % 10 == 0:
            v2.flush()
        print(f"top #{len(tops)} {s['char'][:12]} ok", flush=True)

nth = defaultdict(list)
gaps_all = []
for s in tops:
    for i, t in enumerate(s["bw"]):
        nth[i + 1].append(t)
    gaps_all.extend(round(b - a, 1) for a, b in zip(s["bw"], s["bw"][1:]))

print()
print(f"=== 탑{len(tops)} 야수의 격노 ===")
for s in tops[:10]:
    print(f"  {s['char'][:12]:12s} {s['dur']}s: 야격={s['bw']} | 야생부름={s['cw']} | 물약={s['pots']} | 블러드={s['lust']}")
print()
print("=== n번째 야격 시각 (중앙값 / 범위) ===")
for n in sorted(nth):
    v = nth[n]
    if len(v) >= len(tops) * 0.5:
        print(f"  {n}번째: 중앙값 {statistics.median(v):.0f}s ({min(v):.0f}~{max(v):.0f}) n={len(v)}")
print()
if gaps_all:
    s_ = sorted(gaps_all)
    print(f"야격 간격: 중앙값 {statistics.median(s_):.1f}s / 최소 {min(s_):.1f} / p25 {s_[len(s_)//4]:.1f} / p75 {s_[3*len(s_)//4]:.1f}")
lusts = [s["lust"][0] for s in tops if s["lust"]]
if lusts:
    print(f"블러드 시각: 중앙값 {statistics.median(lusts):.0f}s ({min(lusts):.0f}~{max(lusts):.0f})")
pot1 = [s["pots"][0] for s in tops if s["pots"]]
pot2 = [s["pots"][1] for s in tops if len(s["pots"]) > 1]
if pot1:
    print(f"물약1: 중앙값 {statistics.median(pot1):.0f}s / 물약2: {statistics.median(pot2):.0f}s (n={len(pot2)})")
# 블러드와 가장 가까운 야격 오프셋
offs = []
for s in tops:
    if s["lust"] and s["bw"]:
        L = s["lust"][0]
        offs.append(round(min((abs(t - L), t - L) for t in s["bw"])[1], 1))
if offs:
    print(f"블러드 기준 최근접 야격 오프셋: 중앙값 {statistics.median(offs):.1f}s (음수=블러드 전 선시전)")

# ── 만터리 ──
print()
print("=== 만터리 (아즈샤라 KR) 한밤의 도래 신화 ===")
try:
    d = cli.query(Q_CHAR_RANK, {"name": "만터리", "server": "azshara", "region": "KR",
                                "encounterId": 3183})
    er = ((((d.get("characterData") or {}).get("character") or {})
           .get("encounterRankings") or {}))
    ranks_m = er.get("ranks") or []
    print(f"기록 {len(ranks_m)}건 (총 킬 {er.get('totalKills')})")
    for r in ranks_m[:6]:
        rep = r.get("report") or {}
        code, fid = rep.get("code"), rep.get("fightID")
        print(f"  report {code} fight {fid} dps {round(float(r.get('amount') or 0)):,} "
              f"({r.get('startTime')})")
        s = sample(code, fid, "만터리")
        if s:
            print(f"    {s['dur']}s: 야격={s['bw']}")
            print(f"    야생부름={s['cw']} | 물약={s['pots']} | 블러드={s['lust']}")
except Exception as e:
    print("만터리 조회 실패:", e)
v2.flush()
