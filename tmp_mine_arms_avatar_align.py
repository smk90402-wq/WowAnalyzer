# -*- coding: utf-8 -*-
"""무기 투신 심층: 재사용 간격 분포(45/50초 도달?) + 투신→거강→칼폭 3중 정렬 실측.

데이터: 스크래치패드 arms_cd_events.json (top100 296킬 캐스트, ms 단위 t).
분노 제어 = 분노 20 소모당 투신·거강 쿨 1초 감소 (기본 투신 90s).
"""
import json, statistics, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SP = r"C:\Users\MKSEORTV\AppData\Local\Temp\claude\C--Users-MKSEORTV-Desktop-WowAnalyzer\30b0abb8-5226-4b13-9c1c-14e4a1562211\scratchpad"
AVATAR, CS, BS = 107574, 167105, 446035

d = json.load(open(SP + r"\arms_cd_events.json", encoding="utf-8"))

gaps = []
triple = {"avatar_n": 0, "cs3": 0, "cs3_bs10": 0}
per_kill_min = []
for key, kill in d.items():
    casts = kill.get("casts") or []
    av = sorted(c[0] for c in casts if c[1] == AVATAR)
    cs = sorted(c[0] for c in casts if c[1] == CS)
    bs = sorted(c[0] for c in casts if c[1] == BS)
    kg = [(b - a) / 1000 for a, b in zip(av, av[1:])]
    gaps.extend(kg)
    if kg:
        per_kill_min.append(min(kg))
    # 3중 정렬: 투신 시전 후 3초 내 거강 → 그 거강 후 10초(디버프 창) 내 칼폭
    for a in av:
        triple["avatar_n"] += 1
        nxt_cs = next((c for c in cs if 0 <= (c - a) / 1000 <= 3), None)
        if nxt_cs is None:
            continue
        triple["cs3"] += 1
        if any(0 <= (b - nxt_cs) / 1000 <= 10 for b in bs):
            triple["cs3_bs10"] += 1

gaps.sort()
n = len(gaps)
pct = lambda p: gaps[min(n - 1, int(n * p))]
print(f"투신 재사용 간격 n={n} (296킬)")
print(f"  중앙값 {statistics.median(gaps):.1f}s | p25 {pct(0.25):.1f} | p10 {pct(0.10):.1f} | p5 {pct(0.05):.1f} | 최소 {gaps[0]:.1f}")
for th in (60, 55, 50, 45):
    k = sum(1 for g in gaps if g <= th)
    print(f"  {th}s 이하: {k}건 ({k/n*100:.1f}%)")
km = sorted(per_kill_min)
print(f"판별 최단 간격 중앙값 {statistics.median(km):.1f}s — 한 판에서 한 번이라도 50s 이하: {sum(1 for v in km if v<=50)}/{len(km)}판, 45s 이하: {sum(1 for v in km if v<=45)}/{len(km)}판")
print()
a, c3, cb = triple["avatar_n"], triple["cs3"], triple["cs3_bs10"]
print(f"3중 정렬 (투신 {a}회 기준):")
print(f"  투신→3초 내 거강: {c3} ({c3/a*100:.1f}%)")
print(f"  +거강 창 10초 내 칼폭까지: {cb} ({cb/a*100:.1f}%)")
