---
name: Korean WoW term pitfalls
description: Avoid misreading Korean WoW raid/spec terminology; verify before acting
type: feedback
---

- **마력주입 = Priest's Power Infusion** (spell ID 10060). NOT Augmentation Evoker. Korean WoW name for Augmentation is 증강.
- **한밤 = Midnight expansion** (WoW expansion after The War Within, released ~2025/2026).
- **꿈의 균열 = zone 46 (raid name)**. 보스 별칭이 아니라 **레이드 자체의 한국 클라 이름** ("Crack of Dreams" / "Rift of Dreams"). WCL 의 zone 46 "VS / DR / MQD" 와 매핑.
- **꿈결을 벗어난 신 카이메루스 = Chimaerus, the Undreamt God** (encounter_id 3306). 이 보스가 특정 시전 시 1조/2조 갈라짐 → 딜사이클 분기 추론 필요. 9보스 중 유일.
- **번역 출처 규칙 — 영어 → 한글 추측 금지**. 직역하지 말고:
  1. 사용자가 도감/인게임 스크린샷 주면 그게 1순위 권위 (틀린 데 지적당한 적 많음)
  2. WoWhead 한국어 (`/ko/`) — 스펠/아이템에 한해 일반적으로 정확
  3. Blizzard Battle.net Game Data API (locale=ko_KR) — 공식, OAuth 필요 (TODO 통합)
  4. 모르면 영문 그대로 표시하고 "TODO: 공식 확인" 주석.

**Why:** 영문 보고 "Salhadaar→살하다르" 처럼 한 글자씩 어긋난 번역으로 사용자에게 신뢰 잃은 적 여러 번. 인게임 도감이 항상 답.

**zone 46 보스 도감 검증 현황 (2026-05-17):**
- ✅ 전제군주 아베르지안, 보라시우스, 바엘고어와 에조라크, 몰락한 왕 살라다르, 빛에 눈이 먼 선봉대, 우주의 왕관, 꿈결을 벗어난 신 카이메루스
- ⏳ Belo'ren / Midnight Falls — 도감 미확인, 추측값 유지

**Why:** Misread 마력주입 as Aug Evoker → wrote an enrichment script checking raid composition for Augmentation. User firmly corrected: "마력주입 사제버프거든 제대로 할래?" The correct approach is checking whether the ranking character received the Power Infusion buff (via V2 GraphQL events filter `ability.id = 10060` on the character), not checking raid composition.

**How to apply:** For Korean WoW jargon, if the English mapping isn't crystal clear, either (a) grep/search the codebase or WoWhead for the exact spell/spec, or (b) ask the user to confirm — don't guess. A wrong guess here burned ~20 minutes of work.
