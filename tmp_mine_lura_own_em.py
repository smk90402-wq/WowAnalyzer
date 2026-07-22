"""하늘연달스물엿새 칠흑의 힘(395296) 유지율 채굴 — 비교표의 '미측정' 칸 채우기.

CPA42mqBHXMyca86 의 르우라 풀 전체에 대해 fight 별 Buffs table 로
자기 버프 uptime 을 재고, data/lura_own_pair_mining.json 에 병합한다.
(상위권 채굴과 같은 방식: table(Buffs, abilityID=395296, source=target=self))
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from wcl_v2 import WCLV2

DATA = Path(__file__).parent / "data"
REPORT = "CPA42mqBHXMyca86"
ENCOUNTER = 3183
EBON_MIGHT = 395296
AUG_ACTOR = 1
MIN_PULL_S = 90

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

own_path = DATA / "lura_own_pair_mining.json"
own = json.loads(own_path.read_text(encoding="utf-8"))

cli = WCLV2()
fights = cli.query(
    """query($code: String!) { reportData { report(code: $code) {
         fights(killType: Encounters) { id startTime endTime encounterID }
       } } }""",
    {"code": REPORT},
)["reportData"]["report"]["fights"]
by_id = {f["id"]: f for f in fights if f.get("encounterID") == ENCOUNTER}

# 풀별 Buffs table 을 한 쿼리로 (alias)
fields = []
for pull in own["pulls"]:
    f = by_id.get(pull["fight_id"])
    if not f:
        continue
    fields.append(
        f'f{f["id"]}:table(dataType:Buffs,abilityID:{EBON_MIGHT},'
        f'sourceID:{AUG_ACTOR},targetID:{AUG_ACTOR},'
        f'startTime:{float(f["startTime"]):.3f},endTime:{float(f["endTime"]):.3f})'
    )
payload = cli.query(
    "query($code:String!){reportData{report(code:$code){" + " ".join(fields) + "}}}",
    {"code": REPORT},
)["reportData"]["report"]

total_up_ms = 0.0
total_dur_ms = 0.0
per_pull = {}
for pull in own["pulls"]:
    f = by_id.get(pull["fight_id"])
    if not f:
        continue
    dur_ms = float(f["endTime"]) - float(f["startTime"])
    table = (payload.get(f'f{f["id"]}') or {}).get("data") or {}
    auras = table.get("auras") or []
    up_ms = float(auras[0].get("totalUptime") or 0) if auras else 0.0
    pct = round(up_ms / dur_ms * 100, 1) if dur_ms else 0.0
    per_pull[pull["pull"]] = pct
    pull["aug"]["ebon_might_uptime_pct"] = pct
    if dur_ms >= MIN_PULL_S * 1000:
        total_up_ms += up_ms
        total_dur_ms += dur_ms

session_pct = round(total_up_ms / total_dur_ms * 100, 1) if total_dur_ms else 0.0
own["session_aggregates"]["aug"]["ebon_might_uptime_pct"] = session_pct
own["session_aggregates"]["aug"]["ebon_might_uptime_note"] = (
    f">=90s 풀 가중 평균 (버프 395296 self, 상위권 채굴과 동일 방식)"
)
own_path.write_text(json.dumps(own, ensure_ascii=False, indent=2), encoding="utf-8")

best = own["best_pull"]["pull"]
print(f"session ebon might uptime (>=90s pulls): {session_pct}%")
print(f"best pull #{best}: {per_pull.get(best)}%")
print("per-pull:", {k: per_pull[k] for k in sorted(per_pull)[:10]}, "...")
