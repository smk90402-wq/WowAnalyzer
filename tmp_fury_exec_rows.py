# -*- coding: utf-8 -*-
"""분노 양 빌드 — 처형구간 마무리 행 추가 + 무기 오프너에 투신 스텝 삽입."""
import json, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

R = "data/rotation_data.json"
d = json.load(open(R, encoding="utf-8"))
fury = d["Warrior"]["specs"]["Fury"]["builds"]

EXEC_ROWS = {
    "학살자": {
        "q": "처형구간(35%↓)이면 급살 없어도", "a": "마무리 일격",
        "why": "대학살로 체력 개방 — 필러(분노의 강타 16%·소용돌이)보다 위입니다(실측 22%). "
               "광란 규칙(비격노·분노캡)은 여전히 그 위 — 처형구간에도 광란이 38%로 1위",
        "tone": "spend"},
    "산왕": {
        "q": "처형구간(35%↓)이면 급살 없어도", "a": "마무리 일격",
        "why": "대학살로 체력 개방 — 분노의 강타(6%)보다 훨씬 위(실측 17%, 우레 작렬과 동급). "
               "광란·우레 작렬 2충전 규칙은 여전히 그 위",
        "tone": "spend"},
}
for b, row in EXEC_ROWS.items():
    rows = fury[b]["flow"]["checklist"]
    if any(r["q"].startswith("처형구간") for r in rows):
        continue
    # 급살(마무리) 행 바로 뒤에 삽입
    i = next(i for i, r in enumerate(rows) if r["a"] == "마무리 일격") + 1
    rows.insert(i, row)

# 무기 오프너 — 투신을 정식 스텝으로 (거강 앞, 글쿨 없음 캡션)
arms = d["Warrior"]["specs"]["Arms"]["builds"]
sl_op = arms["학살자"]["flow"]["opener_single"]
if not any(s["s"] == "투신" for s in sl_op):
    i = next(i for i, s in enumerate(sl_op) if s["s"] == "거인의 강타")
    sl_op.insert(i, {"s": "투신", "t": "글쿨 없음 — 거강과 같이"})
    for s in sl_op:
        if s["s"] == "거인의 강타":
            s["t"] = "물약도 이때"
gi_op = arms["거신"]["flow"]["opener_single"]
if not any(s["s"] == "투신" for s in gi_op):
    i = next(i for i, s in enumerate(gi_op) if s["s"] == "거인의 강타")
    gi_op.insert(i, {"s": "투신", "t": "글쿨 없음 — 거강과 같이"})
    for s in gi_op:
        if s["s"] == "거인의 강타":
            s["t"] = "물약도 이때"

json.dump(d, open(R, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("분노 처형행 2개 + 무기 오프너 투신 스텝 완료")
