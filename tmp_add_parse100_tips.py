# -*- coding: utf-8 -*-
"""parse100 갭 실측(2026-07-11)을 spec_guide 전사 팁에 추가."""
import json, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

P = "data/spec_guide.json"
g = json.load(open(P, encoding="utf-8"))

g["Warrior|Fury"]["tips"].append({
    "t": "100점 로드맵 — 실행이 아니라 킬타임과 PI", "scope": "레이드",
    "d": "1~5등과 21~100등의 분당 시전·쿨기 횟수 차이는 2% 이내(실측) — 손이 문제가 아닙니다. "
         "가르는 건 ①보스별 유리한 킬타임(살라다르는 오히려 +44% 긴 킬에서 100점이 나옴 — 쫄 패딩) "
         "②PI 수급(1~5등 33% vs 21~100등 14%). 로테이션이 익었다면 다음 단계는 파티 구성과 킬 설계입니다.",
    "src": "parse100 갭 실측 (밴드 층화 296킬)"})

g["Warrior|Arms"]["tips"].append({
    "t": "100점 로드맵 — PI가 분노보다 훨씬 크게 작용", "scope": "레이드",
    "d": "실행 지표는 밴드 간 무차이(다운타임은 상위가 오히려 김) — 가르는 건 PI(1~5등 48% vs 21~100등 25%)와 킬타임 설계입니다. "
         "특히 카이메루스 100점은 '평균보다 2.5배 긴 킬 + PI 70%' 패턴(쫄 패딩+지원 조합). "
         "예외: 한밤의 도래는 상위 20명 PI 0% — 모든 보스에서 PI가 필수는 아님.",
    "src": "parse100 갭 실측 (밴드 층화 296킬)"})

json.dump(g, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("팁 추가 완료")
