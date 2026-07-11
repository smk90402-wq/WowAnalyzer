# -*- coding: utf-8 -*-
"""분노 flow — 조건부 실측(fury_procprio) 반영. 핵심 교정: 맨 천둥벼락은 분강 아래."""
import json, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

R = "data/rotation_data.json"
d = json.load(open(R, encoding="utf-8"))
fury = d["Warrior"]["specs"]["Fury"]["builds"]
sl, th = fury["학살자"]["flow"], fury["산왕"]["flow"]

# 공통: 광란/급살 행 실측 뉘앙스
for f in (sl, th):
    for c in f["checklist"]:
        if c["a"] == "광란" and "제1규칙" in c["why"]:
            c["why"] = ("분노의 제1규칙 — 이 두 조건 중 하나면 다른 모든 버튼보다 먼저. 광란이 격노를 켜고 분노를 비웁니다. "
                        "상위권은 격노가 끊기면 1글쿨(중앙 0.7초) 안에 광란으로 되돌립니다(끊김 직후 첫 버튼의 51~57%가 광란). "
                        "분노 임계값(100)은 로그로 잴 수 없어 가이드 통설을 따름")
        if c["a"] == "마무리 일격":
            c["why"] = ("급살은 패닉 버튼이 아닙니다 — 상위권도 광란·피의 갈증을 먼저 끝내고 1~2글쿨 안(실측 1.9초)에 소모. "
                        "덮어쓰기 낭비만 조심")

# 학살자: 칼폭 why 교정(홀드가 아니라 자연 동주기) + 필러 근거
for c in sl["checklist"]:
    if c["a"] == "칼날폭풍":
        c["why"] = ("상위 로그의 90%가 무모한 희생 창 안 — 다만 아껴서 맞추는 게 아니라, 급살이 칼폭 쿨을 깎아 줘서 "
                    "쿨마다 눌러도 무희와 같은 주기(~49초)로 자연히 돕니다. 반드시 격노 상태에서. "
                    "도는 동안 피의 갈증은 자동 시전됨(불안정한 정신 — 버튼 아님)")
    if c["a"] == "분노의 강타":
        c["why"] = "단일 필러의 실측 1순위(전부 꺼진 상황의 36%) — 무모한 희생 창에서는 분쇄의 타격으로 변신"
    if c["a"] == "소용돌이":
        c["why"] = "정말 마지막 — 단일에서 상위권 GCD의 10%도 안 됩니다(광역 버프 켤 때가 본업)"

# 산왕: ⑦천둥벼락/⑧분강 순서 교정 + 우레 작렬·투신 why 실측치
rows = th["checklist"]
for c in rows:
    if c["a"] == "투신 + 무모한 희생":
        c["why"] = ("상위 로그 99.8%가 ±3초 동시(무희 먼저 → 0~1초 뒤 투신이 84%) — 한 버튼처럼, 매크로 추천. "
                    "분노를 쓸수록 쿨이 줄어 실측 47초 주기. 바엘고어·벨로렌은 오프너에 안 쓰고 쫄에 맞춰 엽니다(첫 사용 20~23초)")
    if c["a"] == "우레 작렬":
        c["why"] = ("2충전은 부채 — 상위권은 중앙 1.5초 안에 하나를 비웁니다(794회 중 낭비 35건뿐). "
                    "투신 지속 2초 연장 + 벼락 연쇄 엔진")
tc_i = next(i for i, c in enumerate(rows) if c["a"] == "천둥벼락")
rb_i = next(i for i, c in enumerate(rows) if c["a"] == "분노의 강타")
rows[tc_i], rows[rb_i] = rows[rb_i], rows[tc_i]   # 분강을 위로
for c in rows:
    if c["a"] == "분노의 강타":
        c["q"] = "그다음은"
        c["why"] = "맨 천둥벼락보다 분노의 강타가 위입니다(실측 20% vs 12%) — '천둥벼락 우선'은 우레 작렬로 변신했을 때 얘기"
    if c["a"] == "천둥벼락":
        c["q"] = "전부 쿨이면"
        c["why"] = "마지막 필러 — 우레 작렬(프록)이 아닌 맨 천둥벼락은 여기입니다. 광역에선 소용돌이 연마 유지용으로 승격"
json.dump(d, open(R, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# spec_guide 분노 팁 추가
G = "data/spec_guide.json"
g = json.load(open(G, encoding="utf-8"))
g["Warrior|Fury"]["tips"].append({
    "t": "상태별 정답표 — '천둥벼락>분강'은 프록일 때만", "scope": "공용",
    "d": "격노 꺼짐 → 광란(1글쿨 내 복구가 상위권 표준). 급살 → 1~2글쿨 안 마무리(패닉 아님). "
         "급살 없고 피갈 쿨 돌았으면 → 피의 갈증(해당 상황 GCD의 절반). 전부 꺼지면: 학살자는 분노의 강타(36%, 소용돌이는 10% 미만), "
         "산왕은 분노의 강타 > 맨 천둥벼락(20% vs 12%) — 천둥벼락이 위인 건 우레 작렬로 변신했을 때만. "
         "산왕 투신+무희 동시율 99.8%(한 버튼), 오딘은 아무것도 기다리지 않음(창 정렬 52%는 우연 수준).",
    "src": "top100 조건부 시퀀스 실측 (296킬, 자동시전 3,720건 오염 제거)"})
json.dump(g, open(G, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("분노 조건부 반영 완료")
