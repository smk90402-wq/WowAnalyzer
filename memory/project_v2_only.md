---
name: V2 only — V1 deprecation + CSV minimization
description: 사용자 결정 — V1 다 버리고 V2로 통일. CSV 는 rankings 만 남기고 나머지는 V2 on-demand.
type: project
---

**결정 (2026-05-17)**: V1 API 완전 폐기 + CSV 최소화.

**왜:**
- V1 의 cache_fights 의존성이 V2 신규 report 데이터에서 무력화됨 (enrich_talents 가 15647/15649 를 None 으로 스킵)
- Platinum 18k pts/hr V2 가 V1 보다 빠르고 정확 (rankings 일치 확인됨)
- 사용자 명시 "v1 api는 쓸모없으면 다 버려"

**아키텍처:**
- **유일한 API**: `wcl_v2.py` (GraphQL, OAuth2)
- **CSV**: `rankings_zone46_mythic_dps_top100.csv` 만 유지 (~22k rows, 빠른 첫 로드용). `rankings_with_talents.csv` 도 promote 된 사본으로 유지 — GUI 호환.
- **JSON 캐시**: V2 호출 결과를 디스크에 캐시 (cross-session). 키는 (report_id, fight_id, char_name) 또는 (report_id, fight_id).
- **GUI 흐름**:
  - 시작: rankings CSV 로드 (~21k rows, 빠름)
  - 보스/스펙 선택: 메모리에서 필터 (즉시)
  - 캐릭터 클릭: 해당 fight 의 talents/gear/casts/buffs **on-demand V2 fetch** (없으면), 디스크 캐시 hit 면 즉시
  - 집계 패널 (특성 분포, 시전 TOP10): 처음 보스/스펙 들어갈 때 background fetch (~100 calls, ~1분), 캐시 후 즉시

**폐기 대상 (V1):**
- `enrich_pi.py`, `enrich_talents.py`, `enrich_gear.py`, `enrich_servers.py`,
  `fetch_casts.py`, `fetch_buffs.py`, `fetch_rankings.py`
- 옛 캐시 파일 (cache_fights/source_ids 등) 도 V2 데이터로 점진 교체

**유지:**
- `wcl_v2.py`, `fetch_rankings_v2.py`
- `analyze_talent_trees.py`, `classify_talents.py`, `analyze_hero.py`, `analyze_difficulty.py`, `analyze_pi_impact.py`, `analyze_builds.py`, `analyze_ramp.py`
- `enrich_spell_ko.py` (WoWhead 독립)
- `gui.py`

**How to apply:**
- 새 fetch 스크립트는 무조건 V2 (`wcl_v2.py` 사용)
- V1 스크립트들 점진 삭제 / archive 폴더로 이동
- 큰 캐시 (cache_talents.json 31MB) → V2 키 기반 새 캐시로 마이그 시 옛것 삭제
- 사용자가 다른 PC 에서 오프라인으로 보고 싶다는 명시 없는 한, CSV 늘리지 말 것
