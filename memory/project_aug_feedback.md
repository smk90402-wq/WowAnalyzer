---
name: 증강 기원사 비교 피드백 기능 통합 설계
description: 비교분석 탭 — 1등 대비 빨강 피드백 + 버프 가시성 + 캐릭터 필터 통합 설계 (승인 대기, 2026-06-13)
type: project
---

# 증강 기원사(기원리셋) 비교 피드백 — 통합 설계 v1 (승인 대기)

**사용자 결정(2026-06-13):** 전부 설계 확정 후 한번에 구현 / 버프=세로 스크롤+희귀스킬 접기 / 피드백=셀 마킹+요약 패널 둘 다.

근거 영상(자막 추출 완료, `data/transcripts/aug_evoker.txt` 25,943자):
- https://www.youtube.com/watch?v=Nyz9N14teo4 (M+ 중심, 핵심 로테)
- https://www.youtube.com/watch?v=pwXLEGAQ1OM (레이드 중심, 빌드·장신구·위상분할·세부)

## 확정 spell ID (아이콘 기준 — 이름은 spell_db에서 mojibake)
- 흑요석의 힘 Ebon Might = **395152** (icon spell_sarkareth)
- 예지 Prescience = 409311, 410089
- 영겁의 숨결 Breath of Eons = 403631, 442204
- 불의 숨결 Fire Breath = 357208, 382266
- 격변 Upheaval = 396286
- 분출 Eruption = 395160, 438588
- 살아있는 불꽃 Living Flame = 361469, 361509
- 전세역전 Tip the Scales = 370553
- 시간 도약 Time Skip = 404977
- 하늘빛 일격 Azure Strike = 362969 / 끓어오르는 비늘 Blistering Scales = 360827
- ※ 복수 ID는 빌드 시 기원리셋 실제 cast 분포로 최종 핀.

## 현재 코드 사실 (탐색 결과)
- 비교 탭 = 독립 iframe 2개(`/api/timeline/{rid}/{fid}/{char}`), **diff 로직 없음**. 줌/팬 동기화만 공유.
- 타임라인 서버 렌더 `app/timeline.py:render_html`. cast 셀 = {sid, t_rel, dur}. 버프 레인 별도.
- 캐릭터 목록 = `m.actors`(리포트 전체) — per-fight 아님 → 그래서 다 뜸.
- 데이터: 장신구 OK(gear 12/13), 킬타임 길이 OK·킬플래그 캐시에 없음(0/5732), 조합(subType) WCL이 주지만 `wcl_v2_data.py:349`에서 버림, casts/buffs OK.
- 증강 로테 지식 코드에 0 (Hunter만). 증강 스킬명 mojibake.

## 파트 설계

### ① 버프 가시성 (세로 스크롤 + 희귀스킬 접기)
- `app/timeline.py` ZOOM_JS의 `body.style.overflow='hidden'`(:152)와 `body.horizontal{overflow-y:visible}`(:61) → **overflow-y:auto**로. overflow-x는 드래그 팬 유지.
- 빈도: `Counter(sid for _,_,sid in cast_intervals)`(:404), 버프는 `intervals`(:437). 임계(예: 1~2회) 미만 스킬을 '기타(희귀)' 접이식 행으로. 토글 버튼.

### ② 캐릭터 필터 (friendlyPlayers)
- `Q_REPORT_META`의 `fights{}`에 `friendlyPlayers` 추가 + `report_meta()`(wcl_v2_data.py:351) 저장.
- 프런트 `compFightChange`(main.js:1239): 선택 fight의 friendlyPlayers(sourceID)로 actors 필터. 구캐시(필드 없음)는 전체표시 폴백 + friendlyPlayers 없으면 stale 재페치.

### ③ 증강 스킬명 복구 (선행)
- spell_db의 Evoker 핵심기 name_ko/name_en을 정정(아이콘→한글명 매핑 테이블). /api/spell-map override에도 추가 → 타임라인 셀·툴팁·피드백에서 이름 정상화.

### ④ 데이터 기반
- 조합(comp): v1 **제외**(2026-06-13 결정 b) — killtime·장신구만. subType 보존+재페치는 v2로 연기.
  ※ 'v1' = 이 기능의 1차 버전(WCL API v1 아님 — API v1은 2026-05-18 폐기).
- 킬플래그: report_meta 재페치로 kill/name 채움(필요 리포트만).
- 공용 KPI 모듈 `app/aug_feedback.py`: casts/buffs/gear → KPI + per-cast 위반리스트 계산.

### ⑤ 피드백 엔진 (셀 마킹 + 요약 패널)
**측정 가능(구현):**
| KPI | 측정 | 빨강/노랑 |
|---|---|---|
| 흑요석 유지율% | 395152 cast + 연장모델(불숨/격변+2,분출+1) | 1등 또는 목표 미달 |
| 예지 가동률 | 409311/410089 cadence, 빈 글쿨 | 과다 유휴 |
| 영겁 순서 | Breath가 Ebon 직후 X초내 | 앞·무Ebon → 빨강 |
| 연장기 순서 | Ebon 뒤 불숨→격변→분출, +2먼저 | 어긋남 → 노랑 |
| 전세역전 대상 | Tip 직후 불숨 empower | Upheaval에 씀 → 노랑 |
| 필러 과다 | Living Flame 비율(상위기 쿨중일때) | 버스트중 과다 → 노랑 |
| 장신구 유형 | gear 12/13 vs 패시브 권장목록 | use형 → info |

**측정 불가 → 교육용 주석(2026-06-13 결정):** 흑요석 크리값 보호·버프 대상 최적성·위상분할 악용은 현재 캐시로 자동판정 불가 → 빨강 아님. 대신 패널/툴팁에 '알아야 할 점' 개념 설명(info)으로 노출하고 넘어감.

**1등(강증) 기준선:** 동일 KPI를 강증 로그로 계산해 병기. 빨강=강증값(또는 영상 목표) 미달. 셀 툴팁에 "왜·근거영상" 표기.

**정규화:** 킬타임=%유지율·분당비율로(원시횟수 X). 장신구/조합 다르면 툴팁 주석. 조합은 subType 확보 후 반영.

**렌더:**
- 셀 마킹: timeline_html에서 aug_feedback로 위반 cast 표시 → `.flag-red`/`.flag-warn` 클래스 + 툴팁(규칙·근거).
- 요약 패널: 신규 `/api/aug-feedback/{rid}/{fid}/{char}` JSON → main.js가 row 아래 패널(KPI 표: 내값/강증/목표 + 개선점 리스트 + 영상링크). 같은 aug_feedback 모듈 공유.

### ⑥ 네임드별 반복
- 기원리셋 최근 로그 보스별(못잡은 우주의왕관·벨로렌·한밤의도래 제외) 순회 → 보스별 패널/요약.

## 빌드 순서(한번에)
③스킬명 → ④데이터(subType/killflag/aug_feedback 모듈) → ⑤엔진(셀+패널) → ①버프 → ②필터 → ⑥보스순회 → exe 빌드.

## 검증 완료 (2026-06-13, 실측 NTydRwMQPC2F7kqp:1:1)
- ✅ **흑요석의 힘 395152가 cast로 찍힘**(8회) → 유지율 재구성 전제 성립.
- ✅ **보너스**: buffs 이벤트에 흑요석 395152(76건)·예지 410089(366건) 존재 → **버프 구간 union으로 실측 유지율·예지 적용횟수 직접 계산 가능**(캐스트 모델보다 정확 → 이 방식 채택).
- 실측 cast ID 핀: 흑요석 cast=395152 / 예지 cast=409311·buff=410089 / 영겁 cast=**442204** / 불숨=357208 / 격변=396286 / 분출 cast=395160·buff=438588 / 살불=361469(+361509) / 전세역전=370553 / 시간도약=404977 / 하늘빛일격=362969.
- 데이터 현실: 기원리셋 로컬 캐시엔 이 1판만 → ⑥ 보스순회는 character-reports로 추가 페치(빌드 시).
- 남은 확인: 강증(1등) 로그 캐시 유무(없으면 1회 페치).
