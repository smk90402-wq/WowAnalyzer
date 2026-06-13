---
name: Korean WoW term pitfalls
description: Avoid misreading Korean WoW raid/spec terminology; verify before acting
type: feedback
---

- **마력주입 = Priest's Power Infusion** (spell ID 10060). NOT Augmentation Evoker. Korean WoW name for Augmentation is 증강.
- **한밤 = Midnight expansion** (WoW expansion after The War Within, released ~2025/2026).
- **꿈의 균열 = zone 46 (raid name)**. 보스 별칭이 아니라 **레이드 자체의 한국 클라 이름** ("Crack of Dreams" / "Rift of Dreams"). WCL 의 zone 46 "VS / DR / MQD" 와 매핑.
- **꿈결을 벗어난 신 카이메루스 = Chimaerus, the Undreamt God** (encounter_id 3306). 이 보스가 특정 시전 시 1조/2조 갈라짐 → 딜사이클 분기 추론 필요. 9보스 중 유일.
- **칠흑의 힘 = Ebon Might** (증강 기원사 핵심 능동 버프기, spell **395152**, 아이콘 spell_sarkareth, 10초/쿨30초, 아군 주능력치+치명타, 영상 전체가 이 운영법). **"흑요석의 힘" 아님** — 흑요석(obsidian)은 다른 단어. 증강 흑요석 계열(흑요석 비늘=Obsidian Scales 등)은 방어/패시브라 헷갈림 주의. (2026-06-13 Claude가 "흑요석의 힘"으로 오역 → 사용자 "패시브 오라 아니냐" 의심 → Wowhead/나무위키로 정정. Ebon=칠흑.)
- **번역 출처 규칙 — 영어 → 한글 추측 금지**. 직역하지 말고:
  1. 사용자가 도감/인게임 스크린샷 주면 그게 1순위 권위 (틀린 데 지적당한 적 많음)
  2. WoWhead 한국어 (`/ko/`) — 스펠/아이템에 한해 일반적으로 정확
  3. Blizzard Battle.net Game Data API (locale=ko_KR) — 공식, OAuth 필요 (TODO 통합)
  4. 모르면 영문 그대로 표시하고 "TODO: 공식 확인" 주석.

**Why:** 영문 보고 "Salhadaar→살하다르" 처럼 한 글자씩 어긋난 번역으로 사용자에게 신뢰 잃은 적 여러 번. 인게임 도감이 항상 답.

**zone 46 보스 9명 전수 검증 완료 (2026-05-30, Blizzard journal-encounter ko_KR):**
- 방법: `/data/wow/journal-encounter/index` (en_US) 에서 WCL 영문명 exact 매칭 →
  journalID 확보 → `/data/wow/journal-encounter/{jid}` (ko_KR) 로 공식명.
- WCL encounter_id → Blizzard journalID: 3176→2733, 3177→2734, 3178→2735,
  3179→2736, 3180→2737, 3181→2738, 3182→2739, 3183→2740, 3306→2795.
- **추측 틀렸던 2개 정정**: 3182 "알라르의 자식"→**"알라르의 자손 벨로렌"**,
  3183 "한밤이 내린다"→**"한밤의 도래"** (Midnight Falls).
- 공식명: 전제군주 아베르지안 / 보라시우스 / 바엘고어와 에조라크 / 몰락한 왕 살라다르 /
  빛에 눈이 먼 선봉대 / 우주의 왕관 / 알라르의 자손 벨로렌 / 한밤의 도래 /
  꿈결을 벗어난 신 카이메루스.
- 출처: app/main.py BOSS_KR. WCL zone 46 = "VS / DR / MQD" 는 Blizzard journal
  3개 인스턴스(꿈의 균열=The Dreamrift 1314 등) 합본이라 instance 단위론 안 잡힘 →
  journal-encounter 인덱스 영문명 매칭이 정답.

**교훈 재확인:** 또 추측("한밤이 내린다")이 틀렸다. 새 보스/번역은 항상 Blizzard
journal-encounter ko_KR 로 확정. 영문명 exact 매칭이면 100% 신뢰.

**클래스/전문화 공식 ko_KR (2026-05-30, app/main.py CLASS_KR/SPEC_KR):**
- 출처: Blizzard `/data/wow/playable-class/index` + `/playable-specialization/index`
  (en_US ↔ ko_KR id 매칭). WCL 영문 spec 명과 1:1.
- **Fury=분노** (격노 아님! 격노=Enrage). 26 DPS 스펙 전부 공식 확정.
  예: 흑마법사 악마/고통/파괴, 전사 무기/분노, 마법사 냉기/화염/비전,
  사냥꾼 야수/사격/생존, 죽음의 기사 냉기/부정, 도적 암살/무법/잠행.
- 백엔드가 rankings 행에 class_kr/spec_kr 동봉, inferred_*_kr 도. 프론트는
  영문 값(필터/트리 API)+한글 표시 분리.

**한글화 커버리지 현황 (2026-05-30):** 특성 트리 spell 927개 0% 미한글,
영웅특성 이름 16개 전부 한글, 버프 1% 미한글(=Blizzard 미존재 internal 아우라,
한글화 불가). 사실상 완전. 새 스펙 백필 후엔 enrich_kr 재실행으로 신규 스펠 채움.

**Why:** Misread 마력주입 as Aug Evoker → wrote an enrichment script checking raid composition for Augmentation. User firmly corrected: "마력주입 사제버프거든 제대로 할래?" The correct approach is checking whether the ranking character received the Power Infusion buff (via V2 GraphQL events filter `ability.id = 10060` on the character), not checking raid composition.

**How to apply:** For Korean WoW jargon, if the English mapping isn't crystal clear, either (a) grep/search the codebase or WoWhead for the exact spell/spec, or (b) ask the user to confirm — don't guess. A wrong guess here burned ~20 minutes of work.
