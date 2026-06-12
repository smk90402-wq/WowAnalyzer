---
name: wcl-api-discord-nuggets
description: WCL API 디스코드에서 건진 함정/기법 — 필터 OR 결합, fightIDs 우선, 비참가자 혼입, in-range 버프조건 식
metadata:
  type: reference
---

사용자가 긁어온 WCL API 디스코드(2026-02~03) 검증 결과 (개발자 emallson 답변 포함):

1. **필터 파라미터는 AND가 아니라 OR로 결합** (emallson, 의도된 동작·2022년부터):
   `sourceAurasPresent` + `filterExpression` 동시 사용 시 OR — 교집합을 원하면 **단일 filterExpression으로 합쳐야** 함.
   버프 중 피해 측정 식: `in range from type="applybuff" and ability.id=X to type="removebuff" and ability.id=X group by target on source end`
   (PI uplift·부패의 사격 중 딜 같은 버프조건 분석에 쓸 수 있는 패턴. 단 windfury처럼 피해 직전 버프가 벗겨지는 케이스는 누락)

2. **fightIDs 옵션 > encounterID 필터**: fightIDs는 세그먼트 자체를 스킵(상위 레벨)이라 싸고 정확,
   필터는 전체 이벤트를 훑으며 거름. fight 목록 조회는 "super cheap request" — 먼저 받아서 fightIDs로 좁히는 게 정석.
   (우리 파이프라인은 이미 fight별 start/end 사용 중 — 유지할 것)

3. **로그에 비참가자 혼입**: 도시/인던 밖 사람도 리포트에 기록됨 (source 번호 높은 쪽).
   API가 걸러주지 않음 — 시전/피해 임계값으로 직접 제외해야.
   ★우리 영향 검증(2026-06-12): fight 단위 playerDetails 로스터는 깨끗(KR 1,316전투 중 20인 초과 0건)
   — 혼입은 리포트 레벨 actors 열거 때만 주의★

4. 기타: V1/V2 모두 업로드 API 없음. events 쿼리에 fight의 startTime/endTime 안 넣으면 로그 첫 200ms만 잡힘(우리는 이미 준수).

2025-10~11 분량 추가 (사용자 2차 수집):
5. **인기 탤런트 빌드 API 없음** (emallson "not at this time"): Archon 보스별 인기빌드도, WCL 랭킹 페이지의
   탤런트 집계도 API 미제공 — top100 개별 fight 쿼리 + 탤런트 추출이 유일한 방법.
   ★우리 파이프라인(랭킹 CSV → player_fight nodes → 빌드 분류)이 정답이었다는 공식 확인★
6. **NPC 정밀 HP = events에 `includeResources: true`** (emallson): 피해 이벤트에 대상 hitPoints/maxHitPoints
   실림 (resourceActor=2=대상. 이벤트당 한 액터만, 전부 실리진 않음). 대략값이면 resources graph.
   → 처형/오프닝 구간을 시간 프록시 대신 실제 보스 체력 80%/20% 시점으로 정밀 분석 가능 (2026-06-12 검증·적용).
7. 길드 "raid teams"는 API상 별도 길드 취급, tags≠teams (문서가 구식), 부모-자식 관계 미노출.
