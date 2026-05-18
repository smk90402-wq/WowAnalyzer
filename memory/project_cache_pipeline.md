---
name: 캐시 파이프라인 (V2 직접, SQLite 폐기)
description: GUI 가 v2_cache_*.json 을 V2Data dict 로 직접 lookup. cache.db / migrate_to_sqlite.py 다 제거됨 (2026-05-18).
type: project
---

**파이프라인 (2단계, 단순화됨):**

1. `python backfill_v2.py` → `data/v2_cache_*.json` 4개 채움 (V2 GraphQL 페치, Platinum 18k pts/hr 기준 풀백필 ~2h)
2. `python gui.py` 또는 `LogAnalyze.exe` → V2Data 가 v2_cache JSON 들고 메모리 dict 로 lookup

**Why (2026-05-18 결정):** 기존엔 V2 cache → SQLite → GUI 3단계였는데 SQLite 중간 단계 자체가 불필요했음. dict lookup 이 SQLite query 보다 느리지 않고 (O(1) hash vs B-tree), 사용자가 backfill 후 migrate 단계 빼먹어서 데이터 안 나타나는 헷갈림이 반복됨. cache.db 와 migrate_to_sqlite.py 둘 다 삭제.

**How to apply:**
- 새 데이터 페치 모듈은 모두 V2Data 의 4개 dict (meta/pfight/events/damage) 에 쓴다
- GUI 의 db_* 함수들 (db_casts, db_buffs, db_source_id, db_fight_window, db_damage, db_talent_counts_for_ranks) 는 V2Data dict lookup 으로 구현 — `gui.py:259` 부근
- GUI 첫 시작 시 V2Data 가 4개 JSON (~150MB) 로드 — 3-5초 freeze. 그 후 모든 query 가 O(1)
- damage 는 backfill 안 채움 — `DamageFetchThread` 가 GUI 안에서 on-demand 4-way 병렬 페치 → 공유 V2Data 의 damage dict 에 in-place 업데이트
- GUI 실행 중에 backfill 이 별도 프로세스로 v2_cache 갱신해도 GUI 메모리에는 안 반영됨 (각자 dict 사본). 새 데이터 보고 싶으면 GUI 재시작 (≈ cache.db 시절과 같은 UX)
