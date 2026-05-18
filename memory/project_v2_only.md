---
name: V2 only — V1 fully removed + CSV minimization
description: V1 API 완전 제거 완료 (2026-05-18). V2 GraphQL 단일 백엔드. CSV 는 rankings 만, 나머지는 V2 on-demand JSON 캐시.
type: project
---

**상태 (2026-05-18)**: V1 API 완전 제거 완료. `_archive_v1/`, `analyze_ramp.py`, `WCL_V1_KEY` 전부 삭제됨.

**왜:**
- Platinum 18k pts/hr V2 가 V1 보다 빠르고 정확 (rankings 일치 확인됨, rdps 도 V2 만 정상)
- V1 cache_fights 가 V2 신규 report 데이터에서 무력화되었음
- 사용자 명시 "v2가 있는데 이제 v1은 필요없을거같아" (2026-05-18)

**아키텍처:**
- **유일한 API**: `wcl_v2.py` (GraphQL, OAuth2) + `blizzard.py` (한글 메타)
- **CSV**: `rankings_zone46_mythic_dps_top100.csv` 만 유지 (~22k rows, 빠른 첫 로드용). `rankings_with_talents.csv` 도 promote 된 사본으로 유지 — GUI 호환.
- **JSON 캐시**: V2 호출 결과를 디스크에 캐시 (cross-session). 키는 (report_id, fight_id, char_name) 또는 (report_id, fight_id).
- **GUI 흐름**:
  - 시작: rankings CSV 로드 (~21k rows, 빠름)
  - 보스/스펙 선택: 메모리에서 필터 (즉시)
  - 캐릭터 클릭: 해당 fight 의 talents/gear/casts/buffs **on-demand V2 fetch** (없으면), 디스크 캐시 hit 면 즉시
  - 집계 패널 (특성 분포, 시전 TOP10): 처음 보스/스펙 들어갈 때 background fetch (~100 calls, ~1분), 캐시 후 즉시

**활성 모듈:**
- `wcl_v2.py`, `wcl_v2_data.py`, `fetch_rankings_v2.py`, `blizzard.py`
- `analyze_talent_trees.py`, `classify_talents.py`, `analyze_hero.py`, `analyze_difficulty.py`, `analyze_pi_impact.py`, `analyze_builds.py`
- `enrich_spell_ko.py`, `enrich_blizzard.py` (한글 메타)
- `gui.py`

**How to apply:**
- 새 fetch 스크립트는 무조건 V2 (`wcl_v2.py` 사용) — V1 endpoint 호출 금지
- ramp/setup 같은 추가 분석이 필요해지면 V2 GraphQL `reportData.report.table(dataType: DamageDone, startTime, endTime)` 으로 신규 작성
- 사용자가 다른 PC 에서 오프라인으로 보고 싶다는 명시 없는 한, CSV 늘리지 말 것
