---
name: 외부 API 레퍼런스 위치
description: WCL V2 / Battle.net WoW API 막힐 때 참고할 곳
type: reference
---

**WCL V2 (GraphQL) 참고 코드**:
- 로컬: `C:\Users\smk90\Downloads\warcraftlog-api-v2-master\warcraftlog-api-v2-master`
- Node.js 래퍼 (k0bus 작성). `schema/*.graphql` 폴더에 character / guild / report / characterid 등 query 샘플 들어있음. 우리가 GraphQL 쿼리 구조 막힐 때 (특히 fragment, nested fields) 여기 보면 됨
- 우리 코드: `wcl_v2.py` (직접 requests 로 OAuth + query)

**Blizzard WoW Game Data API 문서**:
- https://community.developer.battle.net/documentation/world-of-warcraft
- (구 URL: https://develop.battle.net 은 community 로 리다이렉트됨)
- Game Data API: spell / item / talent / journal-encounter / talent-tree / playable-class 등
- locale 파라미터로 ko_KR 받음
- 우리 코드: `blizzard.py`

**언제 참고:**
- WCL GraphQL 새 query 짤 때 — k0bus 의 schema/* 보면 어떤 필드가 있는지 빠르게 확인
- Blizzard 새 endpoint 필요할 때 (예: pvp-talent, journal-instance 추가 데이터) — 위 community 사이트
- 막혔다 / 응답 구조 모르겠다 → 둘 중 해당하는 거 먼저 본 다음 probe
