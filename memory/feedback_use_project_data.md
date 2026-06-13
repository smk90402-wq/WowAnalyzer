---
name: 데이터는 직접 찾아 분석 (사용자에게 떠넘기지 말 것)
description: 프로젝트에 데이터/로그가 있으면 리포트ID·아이템명 등을 사용자에게 묻지 말고 직접 grep·캐시·WCL 페치로 찾아 분석
type: feedback
---

**규칙**: 분석에 필요한 정보가 프로젝트에서 retrievable 하면 **사용자에게 되묻지 말고 직접 찾는다.**
- 아이템/스킬 닉네임 → `data/item_db.json`·`spell_db.json` substring grep + Wowhead. (예: 알른응시=Gaze of the Alnseer 249343, 꽁지깃=Radiant Plume 계열, 상자=알게타르 수수께끼 상자 발동형)
- 상위 파스 → `data/rankings_zone46_*.csv` (cols: encounter_id·class·spec·rank·character·dps·item_level·report_id·fight_id) → `V2Data.player_fight()` 로 stats(Crit/Haste/Mastery/Vers 레이팅)·talents 페치.
- 보스 → `app/main.py` `BOSS_KR` (예: 보라시우스=3177).
- BM 영웅 판정 → talents 에 검은화살 466930 있으면 어둠순찰자, 없으면 무리인도자.
- 장신구 발동형/패시브 판정 → 로그 casts 에 cast 로 찍히면 발동형, 안 찍히면 패시브.

**Why**: 사용자가 이 세션에서 두 번 강하게 지적 — "왜 갑자기 바보가됐어", "로그에 널린게 데이터인데 왜자꾸 나한테물어 니가 알아서 찾고 분석해야지". 데이터가 있는데 떠넘기면 무능으로 읽힘.

**How to apply**: 진짜 선호·모호함만 묻는다. retrievable 데이터는 묻지 말고 직접 페치/grep 해서 분석까지 끝낸다. [[feedback_analysis_rigor]] 의 "추측 금지"는 "직접 검증"이지 "사용자에게 떠넘기기"가 아님. [[feedback_autonomy]] 보강.
