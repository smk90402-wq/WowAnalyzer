"""냉법 SPEC_CONFIG 후보 ID 교차검증 — tmp_caster_events.json(냉법 표본 포함)에서
캐스트/버프에 실제로 등장하는지 확인. (v2_cache_events 1.4GB 재스캔 회피)"""
from __future__ import annotations
import sys, json
from pathlib import Path
from collections import Counter
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import pandas as pd

DATA = Path(__file__).parent / "data"
DB = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
def nm(s): return DB.get(str(s), {}).get("name_ko") or f"#{s}"

df = pd.read_csv(DATA / "rankings_zone46_mythic_dps_top100.csv")
pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
ev = json.load(open(DATA / "tmp_caster_events.json", encoding="utf-8"))

sub = df[(df["class"] == "Mage") & (df["spec"] == "Frost")]
cast_ids, buff_ids = Counter(), Counter()
n = 0
for _, r in sub.iterrows():
    p = pf.get(f'{r["report_id"]}:{int(r["fight_id"])}:{r["character"]}')
    if not isinstance(p, dict):
        continue
    e = ev.get(f'{r["report_id"]}:{int(r["fight_id"])}:{p.get("sourceID")}')
    if not isinstance(e, dict):
        continue
    n += 1
    for c in e.get("casts") or []:
        if len(c) >= 3 and c[2] == "cast":
            cast_ids[c[1]] += 1
    for b in e.get("buffs") or []:
        if len(b) >= 3 and "apply" in b[2]:
            buff_ids[b[1]] += 1
print(f"냉법 표본 판수: {n}")

CAND_CAST = {84714: "얼어붙은 구슬", 205021: "서리 광선", 12472: "얼음 핏줄(구 쿨기 확인용)"}
CAND_BUFF = {190446: "두뇌 빙결", 44544: "서리의 손가락", 270232: "빙결의 비(추정ID 검증)"}
print("\n[캐스트 후보]")
for cid, label in CAND_CAST.items():
    print(f"  {cid} {label}: {cast_ids.get(cid, 0)}회")
print("\n[버프 후보]")
for bid, label in CAND_BUFF.items():
    print(f"  {bid} {label}: apply {buff_ids.get(bid, 0)}회")

print("\n[캐스트 상위 20]")
for cid, c in cast_ids.most_common(20):
    print(f"  {cid} {nm(cid)}: {c}")
print("\n[버프 apply 상위 25]")
for bid, c in buff_ids.most_common(25):
    print(f"  {bid} {nm(bid)}: {c}")
# 빙결의 비 후보: 이름에 '빙결'이 들어가거나 DB에 없는 버프 중 다수 등장
print("\n[DB에 없는(#) 버프 중 상위 10]")
unknown = [(b, c) for b, c in buff_ids.most_common() if str(b) not in DB]
for bid, c in unknown[:10]:
    print(f"  {bid}: {c}")
