---
name: WCL V2 API + Platinum 구독
description: V2 GraphQL로 마이그레이션 중. Platinum 구독 (시간당 18,000 포인트).
type: project
---

**현재 상태 (2026-05-17)**:
- V1 한계 확인됨: `metric=rdps` 가 500 server error → 사이트 랭킹과 항상 불일치
- 사용자가 **WCL Platinum 구독** 결제 — 시간당 **18,000 points** (free 3.6k 의 5x)
- V2 client 발급 중 (client_id 일부 받았지만 truncated + client_secret 미수령)

**Why:** 사이트의 "best DPS" 와 우리 데이터 정렬이 완전히 달라서 사용자가 신뢰 안 함. V2 GraphQL 의 `worldData.encounter.characterRankings(metric: rdps)` 가 정답.

**How to apply:**
- `.env` 에 `WCL_V2_CLIENT_ID` + `WCL_V2_CLIENT_SECRET` 들어오면 즉시 `python wcl_v2.py` 로 인증/잔량 확인
- `fetch_rankings_v2.py` 부터 돌려서 rdps 기반 새 rankings CSV 받기 — 기존 enrich 스크립트들 CSV 스키마 동일하게 받도록 작성해둠 → 자동 호환
- 다른 fetch 스크립트들 (casts/buffs/gear/talents/servers) 도 점진적으로 V2 GraphQL 로 마이그 (cache 는 report_id 기준이라 재활용 가능)
- 18k points/hour 이면 풀패치 1회 ~30분 안에 가능 (free 의 5배 속도)
- V1 키 도 `.env` 에 일단 유지 (점진 마이그 동안 fallback)
