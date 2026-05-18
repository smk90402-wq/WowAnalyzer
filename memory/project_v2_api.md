---
name: WCL V2 API + Platinum 구독
description: V2 GraphQL 단일 백엔드 + Platinum 구독 (시간당 18,000 포인트).
type: project
---

**현재 상태 (2026-05-18)**:
- **WCL Platinum 구독 활성** — 시간당 **18,000 points** (free 3.6k 의 5x)
- V2 client 발급 완료, `.env` 에 `WCL_V2_CLIENT_ID` + `WCL_V2_CLIENT_SECRET` 셋업됨
- V2 GraphQL `worldData.encounter.characterRankings(metric: rdps)` 가 사이트 랭킹과 일치하는 유일한 source of truth

**Why:** rdps metric 으로 사이트 랭킹과 일치하는 데이터를 안정적으로 받기 위함. Platinum 5x throughput 으로 풀패치 ~30분 안에 처리 가능.

**How to apply:**
- 새 분석/페치 모듈은 `wcl_v2.py` (OAuth2 + GraphQL helper) 만 사용
- rate-limit (429) 만나면 그냥 대기 — throttle 하지 말 것 (see feedback_rate_limit.md)
- 풀패치 backfill 은 18k points/hr 기준 ~30분
