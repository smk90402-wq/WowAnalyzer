# -*- coding: utf-8 -*-
"""무기 학살자 flow — 처형구간 무프록 정답 행 추가 + 광역 우선순위 명시화."""
import json, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

R = "data/rotation_data.json"
d = json.load(open(R, encoding="utf-8"))
sl = d["Warrior"]["specs"]["Arms"]["builds"]["학살자"]["flow"]

# 제압 행(q '위에 아무것도 없으면') 앞에 처형구간 전용 행 삽입
rows = sl["checklist"]
idx = next(i for i, c in enumerate(rows) if c["a"] == "제압")
rows.insert(idx, {
    "q": "처형구간(35%↓)인데 필사·영격 다 꺼져 있으면", "a": "마무리 일격",
    "why": "급살 없이도 체력 조건으로 개방 — 이 상황의 실측 1순위(47%)입니다. 분노가 바닥이면 제압(28%)으로 "
           "분노를 벌어 다시 마무리 — '분노 100 넘보면 마무리, 아니면 제압' 순환. 격돌은 처형구간에서 사실상 봉인(5%)",
    "tone": "spend"})

sl["aoe_diff"] = [
    "쫄이 섞이면(르우라 크리스탈 등) 우선순위가 이렇게 바뀝니다 —",
    "① 분쇄 선도포(도트가 없으면, 처형구간 제외) — 분노 수급. 상위 로그도 살라다르·벨로렌 오프너에서 선도포",
    "② 거인의 강타·칼날폭풍은 그대로 (칼폭이 광역 버스트의 몸통)",
    "③ 회전베기 — 3타겟부터 우선순위 상단. 영웅의 일격 프록도 수동 대신 회전베기 경유로 소모(강화 격돌 자동 발사)",
    "④ 제압이 필사의 일격보다 위로 올라옴(광역 파동) → ⑤ 급살 마무리 → ⑥ 필사 → ⑦ 회전베기 필러",
    "쫄이 오래 살면 거신 빌드가 표준(바엘고어·선봉대 100%) — 르우라처럼 잠깐 나오는 쫄은 학살자 유지가 다수입니다.",
]

json.dump(d, open(R, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# spec_guide 처형구간 팁 보강
G = "data/spec_guide.json"
g = json.load(open(G, encoding="utf-8"))
tips = g["Warrior|Arms"]["tips"]
for t in tips:
    if t["t"].startswith("처형구간"):
        t["d"] = ("분쇄를 더 바르지 않고(상위 로그 60%가 70% 지점 전 중단), 마무리 일격 비중 2.3배. "
                  "발광의 의미가 바뀝니다 — 마무리가 급살 없이 체력으로 상시 개방되어, 필사·영격이 다 꺼진 상황의 "
                  "1순위가 제압에서 마무리(47% vs 28%)로 교체. 분노 100 넘보면 마무리, 바닥이면 제압으로 순환. "
                  "영격+필사 동시엔 처형구간만 영격 먼저.")
        t["src"] = "top100 조건부 시퀀스 실측"
json.dump(g, open(G, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("처형구간 행 + 광역 우선순위 + 팁 갱신 완료")
