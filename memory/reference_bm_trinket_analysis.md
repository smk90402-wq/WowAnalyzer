---
name: BM 사냥꾼 장신구·스탯 분석 (랭킹→player_fight 레시피 + 결론)
description: 보스별 BM 무리인도자 스탯/장신구 실측 방법 + 상자 버프ID + 2026-06-13 결론
type: reference
---

**분석 레시피 (보스별 스탯/장신구 실측):**
- 상위 파스: `data/rankings_zone46_mythic_dps_top100.csv` (cols: encounter_id·class·spec·rank·character·dps·item_level·duration_ms·report_id·fight_id). 보스=encounter_id (보라시우스 3177, 선봉대 3180, 카이메루스 3306, 벨로렌 3182, 바엘고어&에조라크 3178, 살라다르 3179, 아베르지안 3176, 우주의왕관 3181, 한밤의도래 3183).
- 스탯/특성/장비: `V2Data.player_fight(rid,fid,char)` → `stats`={Crit,Haste,Mastery,Versatility,...레이팅}, `talents`(영웅판정), `gear`(slot 12/13=장신구).
- 버프(장신구 발동): `V2Data.events_for(rid,fid,char)['buffs']` → applybuff 카운트.
- BM 영웅: talents에 검은화살 **466930** 있으면 어둠순찰자, 없으면 무리인도자.

**상자(알게타르 수수께끼 상자) — 발동 버프 = spell `383781`** (item 193701, 아이콘 inv_misc_enggizmos_18). 발동형은 *casts의 아이템ID*가 아니라 *이 버프 applybuff*로 세야 함.

**결론 (2026-06-13, zone46 신화 상위, BM):**
- BM 상위 = 사실상 **100% 무리인도자**(어둠순찰자 거의 없음).
- **상자는 전 보스 유지**(착용 80~96%, 발동 2~5회, 전투 길수록↑) — 빼는 보스 없음. 광딜용 아니라 주능력치 폭발이라 단일도 이득. 최상위 세팅=상자(고정)+꽁지깃(가변).
- **꽁지깃(Plume) 치명↔특화는 보스별**: cleave(바엘고어 c/m 104%·선봉대 98%)=치명, 단일/펫(벨로렌 54%·보라시우스 64~68%·우주왕관 73%)=특화.
- 보라시우스: 특화 지배(c/m 64%), 가속vs치명 사실상 동률, ilvl이 최강 변수.
- 카이메루스: MM(어순격냥)=빠른킬(<180s) 승, BM(무리야냥)=장기전(270s+) 승.

자세한 방법론: [[feedback_use_project_data]] / 영웅·스킬ID: [[feedback_wow_kr_terms]].
