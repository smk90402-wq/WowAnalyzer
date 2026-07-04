# WoW 레이드 보스방 3D 지형/메시 확보 경로 조사

작성일: 2026-07-04 · 성격: 조사 문서 (코드 수정 없음) · 선행 문서: `REPLAY3D_PLAN.md` (2D 맵타일 체인 §3-1)

전제: 리플레이 기능에서 유닛 점을 3D 보스방 위에 얹는다. 전투로그에 Z가 없으므로 **유닛 높이 = 지형 표면 샘플링**으로 해결한다.

---

## 0. 결론 먼저

**완전 자동 파이프라인이 가능하다. 그것도 이미 절반은 이 세션에서 실증했다.**

핵심 발견 (전부 이 PC에서 실제 다운로드/파싱으로 검증):

1. **미드나잇 현역 레이드 두 맵이 모두 WMO(건물) 단독 맵이 아니라 ADT(야외 지형) 맵이다.**
   - Map 2939 "The Dreamrift" (카이메루스) — ADT 64타일, Map 2913 "March on Quel'Danas" (본 레이드) — ADT 25타일.
   - 즉 보스방 바닥 높이가 지형 파일(MCVT 청크)에 **그대로 들어 있고**, wago.tools에서 fdid로 받아 ~150줄짜리 파서로 읽힌다.
2. 실제 전투로그 좌표 bbox 위에 높이맵을 샘플링해 봤다: 카이메루스 바닥 640.8~646.4yd, 한밤의 도래 바닥 17.4~27.8yd (완만한 실제 기복). **"Z가 없어서 못 올린다"던 REPLAY3D_PLAN §3-5의 결정타가 이 경로로 해소된다.**
3. **wow.export는 CLI/headless가 전무하다** (소스 전수 검색: 유일한 플래그 `--disable-auto-update`). GUI 수동 4~5클릭 익스포트 도구다. 12.0 Midnight 지원은 확실.
4. **공개 변환본(glTF/OBJ)은 12.0 레이드에 대해 사실상 존재하지 않는다** (noclip=WotLK까지, wow.tools 3D뷰어 사망, Sketchfab=구콘텐츠+무라이선스).

### 경로 비교표

| 경로 | 자동화 | 구현 난이도 | 사용자 수동 단계 | 예상 작업량 | 비고 |
|---|---|---|---|---|---|
| **D. wago.tools ADT 높이맵** (추천) | **완전 자동** | 낮음 (파서 검증 완료) | **0** | **2~3일** | 유닛 Z 스냅 + 2.5D 지형 기복까지. 텍스처는 기존 2D 맵타일 재사용 |
| A. wago.tools 풀 메시 (지형+WMO) | 완전 자동 | 중~높음 (WMO 배치/회전 정렬) | 0 | D + 3~5일 | D의 확장. 회색 무재질 메시로 건물 실루엣 표시 |
| B. wow.export 수동 익스포트 | **불가** (GUI 전용) | 낮음 (GLTFLoader/OBJLoader) | 맵당 4~5클릭 + 레이드마다 반복 | 1~2일 + 맵당 수 분 | 텍스처 포함 최고 품질. 특정 보스방 "이벤트성 고품질" 용 |
| C. 공개 변환본 재사용 | — | — | — | — | **불가 확정** (12.0 레이드 변환본 없음) |

**추천: D를 기본 파이프라인으로, B를 보조(원하는 보스방만 고품질)로.**
- D는 기존 계획(REPLAY3D_PLAN V2 three.js 2.5D)과 자연 결합: 맵 PNG를 평면이 아니라 **높이맵으로 굴곡진 PlaneGeometry**에 입히고, 유닛 y좌표를 `height(x,z)`로 스냅하면 끝.
- "완전 자동 불가"가 아니다 — 단, **모든 레이드가 ADT 맵이라는 보장은 없다**(과거 레이드엔 WMO-only 인테리어 맵 다수). WMO-only 맵을 만나면 A의 WMO 파싱(이것도 검증 완료)으로 분기해야 하고, 그 경우 다층 바닥 레이캐스트 문제가 다시 생긴다. 이번 티어 두 맵은 해당 없음.

---

## 1. 이 세션에서 실제로 실행한 체인 (재현 가능)

| # | 실행 | 결과 |
|---|---|---|
| 1 | 아카이브 로그 grep `ENCOUNTER_START` | `ENCOUNTER_START,3306,"꿈결을 벗어난 신 카이메루스",16,20,2939` — **로그 5번째 필드가 instanceID(=Map.db2 ID)**. uiMapID 매핑조차 필요 없음 |
| 2 | `curl "https://wago.tools/db2/Map/csv?filter[ID]=2939"` | `The Dreamrift, WdtFileDataID=6915037` (2913 → `March on Quel'Danas, WdtFileDataID=6684041`) |
| 3 | `curl "https://wago.tools/api/casc/6915037"` → 163,908B | WDT 파싱: MPHD flags 0x3CA, **MAIN 64타일, MAID 있음, MODF 없음** → ADT 기반 맵 확정 |
| 4 | 로그 한 풀 좌표 27,945샘플 bbox 추출 | 카이메루스: x −1421.8~−1353.3, y −1192.1~−1153.6 → 타일 (col 34, row 34). 공식: `col = floor(32 − y/533.33333)`, `row = floor(32 − x/533.33333)` — 두 맵 모두 정합 |
| 5 | MAID[row*64+col] 엔트리(32B = uint32×8) | `{rootADT=6916202, obj0=6916203, obj1, tex0, lodADT, mapTex=6915346, mapTexN, minimap=6915318}` |
| 6 | `curl .../api/casc/6916202` (451KB) → MCNK×256 → MCVT 파싱 | 전투 중심 청크(ix2,iy9) 높이 640.5~646.6. **전투 bbox 전체 높이맵 샘플 성공** (§5 표) |
| 7 | `curl .../api/casc/6916203` (32KB, obj0) → MODF 파싱 | WMO 배치 100개. **nameId가 fdid를 직접 담음**. 배치 변환 `world = (17066.667−pos.z, 17066.667−pos.x, z=pos.y)` 가 전투 bbox와 정합 |
| 8 | `curl .../api/casc/6423104` (1.4MB, 보스방 위 WMO root) | MOHD nGroups=1, GFID=[6429026, …] (LOD 4개) |
| 9 | `curl .../api/casc/6429026` (110KB, group) → MOVT/MOVI | **1,217 verts / 1,828 tris 추출**, 로컬 bbox가 MOGI와 일치. 10줄 추가로 OBJ 생성 완료 |

파서 총량: Python ~150줄 (scratchpad `terrain/parse_wdt.py`, `parse_adt.py`, `parse_wmo.py`, `heightmap.py`). 외부 라이브러리 0.

주의 실측 2건:
- wago.tools는 **기본 python UA를 403으로 차단** — `urllib` 실패, `curl` 정상. 구현 시 User-Agent 헤더 필수 (기존 2D 타일 페처와 동일 이슈).
- Midnight WMO group에는 신 청크가 있음 (`MOPY`→`MPY2`, 신규 `MOGX`/`MOQG`/`MOC2`). **MOVT/MOVI는 불변**이라 "모르는 청크는 스킵" 전략이면 문제 없음. 구세대 파서 라이브러리는 여기서 깨질 수 있음.

---

## 2. wow.export (Kruithne) — GUI 전용, 자동화 불가

릴리스/소스/실행 검증 (portable zip 335MB를 scratchpad에 받아 압축 해제·실행까지 확인):

- 최신 **0.2.19 (2026-06-22)**. NW.js 앱 (Electron 아님, `nw.dll` 267MB). 소스가 `src/`에 **평문 JS**로 동봉 (MIT).
- **CLI/headless/RCP 없음**: 소스 전수 grep 결과 명령행 처리는 `src/app.js:14`의 `--disable-auto-update` 하나. commander/yargs/IPC/websocket 서버 코드 없음. `wow.export.exe --help` 실행 → stdout 공백, GUI 6프로세스 기동 (kill로 정리).
- 익스포트 능력:
  - Models 탭: WMO/M2 → **OBJ / STL / glTF / GLB / Raw / PNG**. 단 **WMO glTF에는 내부 doodad 미포함** (`WMOExporter.js` L346 TODO — OBJ 경로는 doodad set 지원).
  - Maps 탭: 지형 타일 → OBJ + `ModelPlacementInformation.csv` (WMO/M2 배치 정보, Blender 애드온이 자동 조립) / PNG / **Heightmaps**. WMO-only 맵이면 "**Export Global WMO**" 버튼 노출 (OBJ 고정).
- 소스: **로컬 CASC**(`.build.info` 파싱 — 이 PC `C:\Program Files (x86)\World of Warcraft` = kr 12.0.7.68275, 형식 확인 완료) / **Battle.net CDN 스트리밍(클라 설치 불필요)** 둘 다.
- **12.0 Midnight 지원 확정**: CHANGELOG에 "variable layer terrain blending on Midnight maps", "12.X (Midnight)" 수정 다수. 0.2.19 자체가 "modern map exports 회귀 수정" 릴리스.
- 수동 절차 (인앱 KB007 기준): 실행 → 소스 선택 → Maps 탭 → 맵 검색 → 타일 선택 → 옵션(WMO/M2/Liquids 포함 여부) → Export. **실질 4~5클릭**. 레이드 신규 티어마다 이 손작업 반복 필요.
- GUI 실전 익스포트 리허설: portable 앱을 실제 기동해 **소스 선택 화면(Open Local Installation / Use Battle.net CDN·Region Korea / Legacy)까지 확인**. 그 다음 클릭부터는 동시 실행 중이던 League of Legends(Riot Vanguard, 관리자 권한)가 시뮬레이션 입력을 전역 차단(UIPI)해 중단 — 도구 문제가 아니라 이 세션의 환경 제약. 나머지 export 동작은 소스 레벨에서 확인 (`tab_maps.js` L291/L442-471에 인스턴스 맵 Export Global WMO 분기 실존). 포터블 앱은 scratchpad에 준비돼 있어 아무 때나 수동 재현 가능.

판정: **"사용자 수동 1회" 경로로는 최상급** (품질·간편함). 앱 파이프라인에 넣을 자동화 수단으로는 불가.

---

## 3. wago.tools raw 파일 — 자동 파이프라인의 본체 (검증 완료)

- **fdid 다운로드**: `https://wago.tools/api/casc/{fdid}` — 2D 타일(BLP)과 동일 엔드포인트로 **WDT/ADT/WMO 원본이 전부 내려온다** (§1 체인으로 실증, API 키 불필요).
- **fdid를 찾는 법이 완전 자동**: 로그 `ENCOUNTER_START` 5번째 필드(instanceID) = `Map.db2` ID → `WdtFileDataID` → WDT `MAID`에 타일별 8종 fdid(지형/오브젝트/텍스처/**미니맵**) → obj0 `MODF.nameId` = WMO fdid → WMO root `GFID` = group fdid. 커뮤니티 listfile(이름→fdid) 없이도 전 단계가 ID 체인으로 닫힌다.
- 파싱 라이브러리 재사용성:
  - **자체 파서로 충분** — 필요한 청크(MAID/MCVT/MODF/MOVT/MOVI)만 읽으면 되고, 이번 세션 Python 150줄로 끝. JS 포팅도 동일 규모 (DataView + struct).
  - 참고용 기존 구현: wow.export `src/js/3D/loaders/*.js` (MIT, 평문 JS — 최신 12.0 대응, 최고의 레퍼런스), `pywowlib` (MIT, Python, 2025-05까지 커밋 — 구포맷 중심이라 12.0 신청크 보장 없음), `wowserhq/format` (MIT, TS — 2024-04 정지). **그대로 import해서 쓸 물건은 없고, 청크 오프셋 참고서로 쓰는 게 현실적.**
- 좌표 정렬 공식 (전부 실데이터로 정합 확인):
  - 타일: `col = floor(32 − worldY/533.33333)`, `row = floor(32 − worldX/533.33333)`
  - MCNK 코너 = (posx=X북, posy=Y서), 정점 간격 4.1667yd (9×9 외곽 + 8×8 내부 = 145 float), `z_world = posz + h`
  - WMO 배치: `worldX = 17066.667 − pos.z`, `worldY = 17066.667 − pos.x`, `worldZ = pos.y` (+ MODF rot 3축, 도 단위)
- 용량 실측: WDT 160KB + 타일당 rootADT ~450KB + obj0 ~30-77KB. 보스방 하나(타일 1~4장) 높이맵이면 **~0.5-2MB 다운로드, 1회 캐시**. WMO까지 받으면 +수 MB~수십 MB.

---

## 4. 공개 변환본 — 없음 (재확인 완료)

- `wow.tools` 3D 뷰어: **2025-05 서버 폐쇄** 공지 확인. 후속 wago.tools에는 3D 뷰어/모델 다운로드 없음 (`/models` 404).
- **noclip.website**: WoW 렌더러는 활발(TS+Rust/WASM)하지만 씬 목록이 **Vanilla/TBC/WotLK 레이드까지만**. 데이터는 자체 서버의 재패키징 원본 포맷("sheepfile")이고 export 기능·재배포 허가 없음.
- **wowser/wowserhq**: 3.3.5a 전용 PoC, 2023~2024 정지. `wowserhq/format`(TS WMO/ADT 파서, MIT)은 참고 가치만.
- **Deamon87/WebWowViewerCpp**: 현행 포맷을 그리는 유일한 웹 렌더러(2025-05 활동)지만 C++→WASM — three.js에 이식할 물건 아님.
- Sketchfab 등 립 모델: 구콘텐츠 위주(예: 카라잔), 라이선스 부재, 12.0 레이드 없음. 번들 재배포는 Blizzard IP 리스크.
- 결론: **직접 추출이 유일한 현실 경로.** 라이선스 관행도 2D 타일과 동일 — 산출물을 exe에 동봉하지 말고 **사용자 PC에서 런타임 다운로드 + 로컬 캐시**.

---

## 5. 높이맵 절충안 — 실측으로 확정된 추천안

풀 메시 없이 **보스방 바닥 높이맵만** 뽑는 경로. 이번 티어에선 WMO조차 필요 없었다:

```
카이메루스 방 (Map 2939, 타일 34,34) — 전투 bbox 위 8yd 그리드 샘플 (yd):
        y=-1150  y=-1158  y=-1166  y=-1174  y=-1182  y=-1190
x=-1350   645.0    645.0    645.0    644.0    642.3    640.8
x=-1382   644.3    644.6    646.4    646.4    646.4    646.4
x=-1422   645.0    643.8    646.4    646.4    646.4    646.4
→ 바닥 640.8~646.4 (기복 5.6yd)

한밤의 도래 (Map 2913, 타일 40,11): 바닥 17.4~27.8 (남→북 완경사 10.4yd)
```

- 교차 검증: 카이메루스 방을 덮는 WMO(6423104) 배치 상단 z=647.6 ≈ 지형 646.4 — 지형면이 실제 바닥과 1yd 내 일치.
- 구현 스케치 (기존 REPLAY3D_PLAN V2에 얹기):
  1. 서버: `GET /api/replay-terrain/{instanceID}` → (Map.db2→WDT→해당 타일 MCVT) → 전투 bbox+여유 구간의 높이 그리드 JSON (4.17yd 해상도, 수십 KB) + 캐시. instanceID는 ENCOUNTER_START에서 이미 확보됨.
  2. 프런트: three.js `PlaneGeometry(w,h,nx,ny)` 정점 z에 그리드 대입, 기존 2D 맵타일 PNG(또는 MAID의 mapTex/minimap 타일)를 텍스처로. 유닛 y = 바이리니어 `height(x,z)` + 0.5.
  3. WMO 바닥 전투(다리/플랫폼)를 만나면: 해당 보스방만 MODF→MOVT/MOVI 삼각형 하향 레이캐스트로 교체(§3 파서 그대로) — 다층 구조면 "로그 좌표 클러스터에 가장 가까운 층" 휴리스틱 또는 보스별 수동 offset 1개.
- 한계 명시: 지형이 아닌 **탈것/플랫폼 위상 전투**(예: 비행 페이즈)는 어떤 경로로도 Z 복원 불가 — 2D 폴백 유지.

---

## 6. 추천 로드맵

| 단계 | 내용 | 작업량 | 산출 |
|---|---|---|---|
| T1 | `replay_terrain.py`: instanceID→WDT→MCVT 높이 그리드 JSON + 캐시 (§5-1) | 1~1.5일 | 유닛 Z 스냅 (2D 뷰에도 등고선/음영 활용 가능) |
| T2 | three.js 지형 메시 + 맵타일 텍스처 + 유닛 스냅 (V2와 통합) | 1~1.5일 | "진짜 기복 있는 보스방" 렌더 |
| T3 (옵션) | WMO 실루엣 오버레이 (회색 무재질) + WMO 바닥 레이캐스트 | 3~5일 | 건물 안 보스방 대응 + 시각 완성도 |
| 수동 보조 | wow.export로 원하는 보스방만 OBJ/glTF 추출 → 정적 에셋 교체 슬롯 | 보스방당 수 분 | 최고 품질 (텍스처 포함) |

리스크: wago.tools 다운/포맷 변경(→캐시 우선, 로컬 CASC 직독은 미래 과제), 미래 티어의 WMO-only 맵(→T3), 암호화 파일(현 티어 전 파일 정상 수신 확인), UA 차단(헤더로 해결).

---

## 부록: 스크래치패드 산출물

`...\scratchpad\terrain\`: `parse_wdt.py` `parse_adt.py` `parse_wmo.py` `heightmap.py` `fight_coords.py` — 파서/실측 스크립트 · `2939.wdt` `2913.wdt` `69*.adt` `6423104.bin` `6429026.bin` — 원본 파일 · `6916202_arena_hm.json` `6695524_arena_hm.json` — 보스방 높이맵 · `wmo_6423104_g0.obj` — WMO→OBJ 변환 증명 (1,217v/1,828t)
`...\scratchpad\wowexport\app\` — wow.export 0.2.19 portable (실행 검증용, 335MB)
