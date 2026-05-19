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

**WoW Wiki API 참고 (in-game Lua API + UI/event 명세)**:
- https://warcraft.wiki.gg/wiki/World_of_Warcraft_API
- 게임 내 Lua API + COMBAT_LOG_EVENT_UNFILTERED 같은 이벤트 정의 + 클래스/스펙/스펠 ID 매핑 인덱스
- WCL 응답이 source/target/flag 등 어떤 의미인지 확인할 때 (예: combat log event 의 source/target 정의), 또는 talent/buff API 이름 매핑 확인할 때 유용
- 정적 데이터 + community-curated, 빠른 lookup 용

**언제 참고:**
- WCL GraphQL 새 query 짤 때 — k0bus 의 schema/* 보면 어떤 필드가 있는지 빠르게 확인
- Blizzard 새 endpoint 필요할 때 (예: pvp-talent, journal-instance 추가 데이터) — 위 community 사이트
- WCL 의 event 필드 의미 모를 때 (특히 source/target 의 buff 동작 같은 거) → wiki.gg 의 combat log 페이지
- 막혔다 / 응답 구조 모르겠다 → 셋 중 해당하는 거 먼저 본 다음 probe
