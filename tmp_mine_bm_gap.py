# 만터리 vs BM 탑30 — 딜 격차 분해 (스킬별 dps + 타겟 분배 + 세팅)
import statistics
from collections import Counter, defaultdict

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


def sample(code, fid, char):
    meta = v2.report_meta(code)
    if not meta:
        return None
    f = next((x for x in meta["fights"] if x["id"] == int(fid)), None)
    if not f:
        return None
    dur = (f["endTime"] - f["startTime"]) / 1000.0
    table = v2.damage_table(code, int(fid), char)
    pf = v2.player_fight(code, int(fid), char)
    if not table or not pf:
        return None
    spells = {}
    targets: Counter = Counter()
    for e in table:
        nm = str(e.get("name") or "?")
        spells[nm] = spells.get(nm, 0) + int(e.get("total") or 0)
        for tg in e.get("targets") or []:
            targets[str(tg.get("name") or "?")] += int(tg.get("total") or 0)
    total = sum(spells.values())
    return {"dur": dur, "total": total, "dps": total / dur,
            "spells_dps": {k: v / dur for k, v in spells.items()},
            "targets_pct": {k: round(v / total * 100, 1) for k, v in targets.most_common(8)},
            "trinkets": [g.get("name") for g in pf.get("gear") or [] if g.get("slot") in (12, 13)],
            "ilvl": (pf.get("stats") or {}).get("Item Level"),
            "stats": pf.get("stats") or {},
            "talents": set(pf.get("talents") or [])}


data = v2.cli.query(Q_TOP, {"encounterId": 3183, "difficulty": 5, "cls": "Hunter",
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
        s["rank_dps"] = round(float(row.get("amount") or 0))
        tops.append(s)
        if len(tops) % 10 == 0:
            v2.flush()
        print(f"top #{len(tops)} ok", flush=True)
v2.flush()

ours = []
for code, fid in (("8bcN17hKrMtmTGDB", 15), ("BtADGd3RkJy6gb4f", 10)):
    s = sample(code, fid, "만터리")
    if s:
        ours.append(s)
v2.flush()

# 스킬별 dps: 탑 중앙값 vs 만터리 평균
top_spell: defaultdict[str, list[float]] = defaultdict(list)
for s in tops:
    for k, v in s["spells_dps"].items():
        top_spell[k].append(v)
our_spell: defaultdict[str, list[float]] = defaultdict(list)
for s in ours:
    for k, v in s["spells_dps"].items():
        our_spell[k].append(v)

rows = []
for k, tv in top_spell.items():
    if len(tv) < len(tops) * 0.5:
        continue
    t_med = statistics.median(tv)
    o = statistics.mean(our_spell.get(k, [0.0]))
    rows.append((k, o, t_med, o - t_med))
rows.sort(key=lambda r: r[3])

print()
print(f"만터리 전체 dps: {[round(s['dps']) for s in ours]} (풀시간 기준)")
print(f"탑30 전체 dps 중앙값: {round(statistics.median([s['dps'] for s in tops]))}")
print()
print("=== 스킬별 dps 격차 (탑 중앙값 대비, 큰 손실 순) ===")
for k, o, t, d in rows[:16]:
    print(f"  {k[:22]:22s} 우리 {o:8,.0f} vs 탑 {t:8,.0f} → {d:+8,.0f}")
print("  ... (이득 상위)")
for k, o, t, d in rows[-4:]:
    print(f"  {k[:22]:22s} 우리 {o:8,.0f} vs 탑 {t:8,.0f} → {d:+8,.0f}")

print()
print("=== 타겟 분배 (총딜 %) ===")
print("만터리:", ours[0]["targets_pct"])
agg: defaultdict[str, list[float]] = defaultdict(list)
for s in tops:
    for k, v in s["targets_pct"].items():
        agg[k].append(v)
print("탑30 중앙값:", {k: round(statistics.median(v), 1) for k, v in
                    sorted(agg.items(), key=lambda kv: -statistics.median(kv[1]))[:8]
                    if len(v) >= 15})

print()
print("=== 세팅 ===")
print("만터리 장신구:", ours[0]["trinkets"], "/ 킬2:", ours[1]["trinkets"] if len(ours) > 1 else "")
tt: Counter = Counter()
for s in tops:
    for t in s["trinkets"]:
        tt[t] += 1
print("탑30 장신구:", tt.most_common(6))
print("만터리 ilvl:", [s["ilvl"] for s in ours], "/ 탑 중앙값:", statistics.median([s["ilvl"] for s in tops if s["ilvl"]]))
for key in ("Haste", "Crit", "Mastery", "Versatility", "Agility"):
    ov = [s["stats"].get(key) for s in ours if s["stats"].get(key)]
    tv = [s["stats"].get(key) for s in tops if s["stats"].get(key)]
    if ov and tv:
        print(f"  {key}: 만터리 {round(statistics.mean(ov))} vs 탑 {round(statistics.median(tv))}")

# 특성 차이: 탑 80%+ 채택인데 만터리에 없는 것
talent_count: Counter = Counter()
for s in tops:
    for t in s["talents"]:
        talent_count[t] += 1
common = {t for t, n in talent_count.items() if n >= len(tops) * 0.8}
missing = common - ours[0]["talents"]
extra = {t for t in ours[0]["talents"]
         if talent_count.get(t, 0) <= len(tops) * 0.2}
print(f"탑 80%+ 공통 특성 중 만터리 미채택: {len(missing)}개 {sorted(missing)[:12]}")
print(f"만터리만 쓰는 특성(탑 20% 이하): {len(extra)}개 {sorted(extra)[:12]}")
