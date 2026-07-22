# 페이즈별 dps — 만터리 vs BM 탑30 (한밤의 도래 신화)
# 페이즈: 1=P1, 2=사이페, 3=P2, 4=P3, 5=막바지(랭킹 제외 구간)
import statistics
import sys
from collections import defaultdict

from wcl_v2 import WCLV2
from wcl_v2_data import V2Data, Q_DAMAGE_TABLE

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
PHASE_KR = {1: "P1", 2: "사이페", 3: "P2", 4: "P3", 5: "막바지(제외)"}

v2 = V2Data()
cli = v2.cli


def phase_dps(code, fid, char):
    pf = v2.player_fight(code, int(fid), char)
    if not pf:
        return None
    sid = pf.get("sourceID")
    d = cli.query(Q_PHASES, {"code": code, "fid": int(fid)})
    f = ((((d.get("reportData") or {}).get("report") or {}).get("fights") or [{}])[0])
    if not f:
        return None
    start, end = f["startTime"], f["endTime"]
    pts = sorted((p["id"], p["startTime"]) for p in f.get("phaseTransitions") or [])
    if not pts:
        return None
    out = {}
    for i, (pid, t0) in enumerate(pts):
        t1 = pts[i + 1][1] if i + 1 < len(pts) else end
        if t1 <= t0:
            continue
        dd = cli.query(Q_DAMAGE_TABLE, {"code": code, "start": float(t0),
                                        "end": float(t1), "sid": int(sid)})
        table = (((dd.get("reportData") or {}).get("report") or {}).get("table") or {})
        inner = table.get("data", table) if isinstance(table, dict) else {}
        total = sum(int(e.get("total") or 0) for e in inner.get("entries") or [])
        out[pid] = {"dps": total / ((t1 - t0) / 1000.0), "dur": round((t1 - t0) / 1000.0, 1)}
    return out


data = cli.query(Q_TOP, {"encounterId": 3183, "difficulty": 5, "cls": "Hunter",
                         "spec": "BeastMastery", "partition": 3, "page": 1})
ranks = ((((data.get("worldData") or {}).get("encounter") or {})
          .get("characterRankings") or {}).get("rankings") or [])

top_phase: defaultdict[int, list[float]] = defaultdict(list)
n = 0
for row in ranks:
    if n >= 20:   # 페이즈당 쿼리 5개라 20표본이면 충분
        break
    rep = row.get("report") or {}
    if not rep.get("code"):
        continue
    try:
        pd_ = phase_dps(rep["code"], rep["fightID"], row.get("name"))
    except Exception as e:
        print("fail:", e)
        continue
    if not pd_:
        continue
    for pid, v in pd_.items():
        top_phase[pid].append(v["dps"])
    n += 1
    print(f"top #{n} ok", flush=True)

print()
print("=== 만터리 ===")
ours_phase: defaultdict[int, list[float]] = defaultdict(list)
for code, fid in (("8bcN17hKrMtmTGDB", 15), ("BtADGd3RkJy6gb4f", 10)):
    pd_ = phase_dps(code, fid, "만터리")
    if pd_:
        print(f"  {code}: " + " | ".join(
            f"{PHASE_KR.get(pid, pid)} {v['dps']:,.0f}({v['dur']}s)" for pid, v in sorted(pd_.items())))
        for pid, v in pd_.items():
            ours_phase[pid].append(v["dps"])

print()
print(f"=== 페이즈별 dps: 만터리(평균) vs 탑{n}(중앙값) ===")
for pid in sorted(top_phase):
    tv = statistics.median(top_phase[pid])
    ov = statistics.mean(ours_phase.get(pid, [0.0]))
    gap = (ov / tv - 1) * 100 if tv else 0
    print(f"  {PHASE_KR.get(pid, pid):10s} 만터리 {ov:8,.0f} vs 탑 {tv:8,.0f} → {gap:+.1f}%")
v2.flush()
