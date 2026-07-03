"""boss_dealcycle.json 의 Mage|Frost 보스별 하이라이트 요약 출력."""
from __future__ import annotations
import sys, json
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(__file__).parent / "data"
d = json.load(open(DATA / "boss_dealcycle.json", encoding="utf-8"))
print("스펙 키:", {k: len(v) for k, v in d.items()})
fr = d.get("Mage|Frost", {})
for eid, b in sorted(fr.items(), key=lambda x: int(x[0])):
    print(f"\n=== {b['boss_kr']} (eid={eid}, n={b['n']}, kill={b['kill_s']}s) ===")
    print("  오프너(" + str(b.get("opener_match")) + "% 일치): " +
          " → ".join(o["skill"] for o in b.get("opener") or []))
    for c in b.get("cooldowns") or []:
        print(f"  쿨기 {c['skill']}: 첫사용 {c['first_s']}s, 판당 {c['count']}회")
    if b.get("lust"):
        print(f"  블러드: {b['lust']['cover']} @ {b['lust']['first_s']}s")
    if b.get("potion"):
        print(f"  물약: {b['potion']['cover']} @ {b['potion']['first_s']}s")
    for u in b.get("buff_uptime") or []:
        print(f"  버프 {u['buff']}: {u['pct']}%")
    if b.get("box"):
        print(f"  상자: {b['box']}")
