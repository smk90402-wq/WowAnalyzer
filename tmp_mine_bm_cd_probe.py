"""lust/물약 실제 ID 탐색 — 추출된 BM 이벤트에서 '판당 1~3회, 지속 25~45s' 버프 찾기."""
from __future__ import annotations
import json, sys
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze\data")
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")

db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
def nm(s): return db.get(str(s), {}).get("name_ko") or "?"

ev = json.load(open(SCRATCH / "bm_cd_events.json", encoding="utf-8"))
nf = len(ev)

fights_with = Counter()      # buff id -> n fights
applies = Counter()          # buff id -> total applies
durs = defaultdict(list)     # buff id -> apply->remove durations (s)

for e in ev.values():
    seen = set()
    active = {}
    for b in sorted((b for b in (e.get("buffs") or []) if len(b) >= 3), key=lambda x: x[0]):
        ts, sid, typ = b[0], b[1], b[2]
        if typ == "applybuff":
            applies[sid] += 1; seen.add(sid); active[sid] = ts
        elif typ == "removebuff" and sid in active:
            durs[sid].append((ts - active.pop(sid)) / 1000)
    for s in seen: fights_with[s] += 1

def med(v):
    v = sorted(v); return v[len(v)//2] if v else None

print(f"n_fights={nf}")
print("\n== 대부분의 판(>60%)에 있고 판당 1~3회 적용되는 버프 ==")
rows = []
for sid, c in fights_with.items():
    if c < nf * 0.6: continue
    per = applies[sid] / c
    if per > 3.5: continue
    d = med(durs[sid])
    rows.append((sid, c, round(per, 1), round(d, 1) if d is not None else None))
for sid, c, per, d in sorted(rows, key=lambda x: -x[1]):
    print(f"  {sid:>8} {nm(sid):<24} 판 {c}/{nf}  판당 {per}  지속중앙 {d}s")

print("\n== 지속 25~45s & 판당 1~3회 (출현율 무관, 판>=30) ==")
rows = []
for sid, c in fights_with.items():
    if c < 30: continue
    per = applies[sid] / c
    if per > 3.5: continue
    d = med(durs[sid])
    if d is None or not (22 <= d <= 47): continue
    rows.append((sid, c, round(per, 1), round(d, 1)))
for sid, c, per, d in sorted(rows, key=lambda x: -x[1]):
    print(f"  {sid:>8} {nm(sid):<24} 판 {c}/{nf}  판당 {per}  지속중앙 {d}s")
