# 로컬 전투로그 리플레이 뷰어(WCL replay 스타일) — 설계 + 타당성 검증

작성일: 2026-07-04 · 과제: 구현이 아니라 설계/실증. 코드 수정 없음, 신규 파일은 이 문서와 스파이크뿐.

---

## 0. 결론 먼저

**된다.** 그것도 생각보다 확실하게 된다.

| 질문 | 답 |
|---|---|
| 좌표 데이터가 실제로 있나? | **있다.** 이 PC의 로그는 고급 전투 기록(`ADVANCED_LOG_ENABLED,1`)이 켜져 있고, 플레이어 초당 3~15회 x/y/facing이 기록된다 (실측). |
| 어느 맵인지 알 수 있나? | **로그가 직접 알려준다.** 고급 파라미터 15번째 필드가 uiMapID다 (예: 2082 = 주입의 전당 1층). 별도 API 불필요. |
| 맵 이미지를 자동으로 받을 수 있나? | **가능. 실제 URL로 검증 완료.** wago.tools CSV API 4번 + 타일 이미지 12장이면 uiMapID → 스티칭된 PNG가 나온다. |
| 3D는? | 2.5D(three.js, 평면 맵 텍스처 + 카메라 틸트)까지는 무난. **진짜 지형 기복(V3)은 비추천** — 고급 로그에 Z(높이) 좌표가 아예 없어서 지형을 만들어도 유닛을 올려놓을 높이 데이터가 없다. WCL도 2D 평면 방식이다. |
| 얼마나 걸리나? | MVP(2D 탑다운 + 맵 텍스처 + 스크럽 + 죽음 마커) **3~4일**, V2(three.js 틸트) **+2~3일**, V3(지형) 보류 권장. |
| 스파이크는? | **완료.** `tmp_replay_spike.html` — 실제 로그에서 뽑은 6유닛 2,622좌표가 궤적·facing과 함께 움직인다. 브라우저에서 열어서 확인 완료(콘솔 에러 0). |

---

## 1. 현재 리플레이 파이프라인 (있는 그대로)

### 1-1. 구성 요소

```
[WoW 로그]  C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-*.txt
[CCTV 영상] E:\cctv\*.json + *.mp4   (WarcraftCCTV 애드온/앱이 풀 단위로 녹화)
     │
     ▼
app/local_replay.py ── 파싱/매칭 전부 여기
     │
     ▼
app/main.py 엔드포인트 3개 (1735~1759행)
  GET /api/local-replay/list           → 캡처 목록 + 로그 전투 매칭
  GET /api/local-replay/{id}           → 상세 (이벤트/좌표/배우/영상 URL)
  GET /api/local-replay/video/{id}     → mp4 FileResponse
     │
     ▼
app/static/index.html  pane-replay (366~390행: 목록 테이블 + 상세 패널)
app/static/main.js     1337~1526행: 목록/상세 렌더 + renderReplayMap()
```

### 1-2. 서버 파싱 (app/local_replay.py)

- `latest_log_path()` — Logs 폴더에서 **가장 최신 `WoWCombatLog-*.txt` 하나만** 본다. `warcraftlogsarchive\Archive-WoWCombatLog-*.txt`(WCL 업로더가 옮긴 과거 로그, 최대 1.2GB짜리 13개 존재)는 **안 본다**. → 과거 레이드 풀 리플레이가 안 되는 첫 번째 한계.
- `_encounter_index_cached()` — `ENCOUNTER_START/END` 줄만 스캔해 전투 목록(시작/끝 시각, 줄 번호)을 lru_cache. 
- `_load_captures()` — E:\cctv 의 JSON을 읽음. 필드: `encounterID, encounterName, difficultyID, duration, result, bossPercent, player, deaths[], combatants[](GUID/spec/team), start(epoch ms), uniqueHash` 등. mp4는 같은 이름의 `.json → .mp4`.
- `_match_capture()` — 캡처 start와 ENCOUNTER_START 시각 차이 **8초 이내 + encounterID 일치**로 영상↔로그 매칭.
- `_parse_log_window()` — 매칭된 전투 구간(줄 번호 범위)만 다시 읽어서:
  - 이벤트: 시전(cast)/플레이어 대상 디버프/25만 이상 피해/죽음 → 타임라인 마커용 (max 3000개)
  - 좌표: `_advanced_position()` — **row[12]=infoGUID, row[26]=x, row[27]=y, row[28]=uiMapID, row[29]=facing, row[30]=level**. 유닛당 0.35초 스로틀.
- `_replay_positions()` — 지배적인 uiMapID만 남기고, **플레이어 + 이름에 보스 토큰이 들어간 유닛만** 필터.
- `_bounds()` — 좌표 min/max에 8% 패딩. 맵 이미지가 없으니 화면 맞춤용.

### 1-3. 프런트 (app/static/main.js)

- `renderLocalReplayDetail()` — 좌: mp4 `<video>` + 시간 슬라이더, 우: `<svg id="replay-map">`(1000×580), 아래: 이벤트 버튼 목록(클릭 시 영상+맵 점프).
- `renderReplayMap()` (1487행) — 슬라이더 시각 t 이하의 **마지막 좌표를 유닛별로 하나씩** 점으로 찍음. 보간 없음, 궤적 없음, 배경은 단색 rect. 좌표를 bounds로 정규화만 하므로 **회전/축 방향 개념 없음**.

### 1-4. 정리하면 지금은

"영상 리플레이 + 보조용 좌표 점 찍기"까지 이미 되어 있고, **없는 것**은 ① 맵 이미지 ② 좌표 보간/궤적 ③ 아카이브(과거) 로그 ④ 영상 없이 로그만으로 보는 모드 ⑤ 3D.

---

## 2. 좌표 데이터 실증 (이 PC 실측)

### 2-1. 전제조건: 고급 전투 기록 — **켜져 있음**

```
WoWCombatLog-070226_230331.txt 첫 줄:
COMBAT_LOG_VERSION,22,ADVANCED_LOG_ENABLED,1,BUILD_VERSION,12.0.7,PROJECT_ID,1
```

(꺼져 있으면 좌표가 전부 사라지므로 이 기능의 유일한 하드 전제조건. 설정: 시스템 → 네트워크 → "고급 전투 기록". WCL 업로드하는 유저라 이미 상시 ON.)

### 2-2. 좌표 필드 포맷 (실제 줄)

```
SPELL_CAST_SUCCESS,Player-205-0ABAB30D,"흑털이-아즈샤라-KR",...,104316,"공포사냥개 부르기",0x20,
  Player-205-0ABAB30D,0000000000000000,77572,87375,5,403,228,0,0,30948,0,50000,50000,0,
  25.13,-212.20,2082,2.8855,90
   └x     └y      └uiMapID └facing(라디안) └레벨
```

- 고급 파라미터는 `SPELL_CAST_SUCCESS, SPELL_DAMAGE, SPELL_PERIODIC_DAMAGE, SPELL_HEAL, SPELL_ENERGIZE, SWING_DAMAGE(_LANDED), RANGE_DAMAGE` 등에 붙음. 좌표의 주인은 **대부분 이벤트의 소스 유닛**(infoGUID로 명시됨).
- spell 계열은 x가 row[26], SWING 계열은 prefix 3필드가 없어 row[23] — 현재 `_advanced_position()`은 고정 인덱스 26이라 **SWING 이벤트 좌표를 버리고 있음** (개선 포인트, 밀도 +13% 정도).
- 좌표 단위 = 야드(월드좌표). **+X=북, +Y=서.** facing 0=북, 반시계.
- **Z(높이)는 로그에 없음** — V3 판단의 근거.

### 2-3. 좌표 밀도 실측 (두 케이스)

**A. 5인 던전 (주입의 전당 시간의길, 감시자 이리데우스, 58.5초):**

| 유닛 | 샘플 수 | 초당 | 최악 공백 |
|---|---|---|---|
| 보스 | 1,321 | 22.6/s | 0.5s |
| 플레이어 5명 | 175~403 | 3.0~6.9/s | 0.9~3.8s |
| 주요 쫄 | 77~111 | 1.3~1.9/s | 0.7~1.5s |

**B. 20인 신화 레이드 (카이메루스 M, 217초 풀, Archive 로그):**

- 총 68,584 좌표샘플 = **초당 316개**, 좌표 찍힌 유닛 676개(플레이어 19)
- 플레이어: 최소 6.6/s · 중앙값 8.5/s · 최대 14.7/s
- 플레이어 최악 공백: 중앙값 1.4s · p90 3.3s · 최대 6.1s
- uiMapID는 풀 내내 2532 하나로 균일

**판정:** 0.5초 그리드 + 선형보간이면 WCL replay와 체감 동일한 부드러움이 나온다. 힐러가 이동 없이 캐스팅만 하는 구간의 3~6초 공백은 보간으로 자연스럽게 커버됨(원래 안 움직이는 구간이라 공백이 김).

**데이터 크기:** 신화 217초 풀을 "10샘플 이상 유닛만 + 0.5초 다운샘플"로 줄이면 약 19,240샘플 ≈ JSON 560KB (바이너리로 짜면 300KB). 한 풀 단위 API 응답으로 전혀 부담 없음.

---

## 3. 맵/지형 소스 조사 결과 (인터넷 조사, 전부 실제 fetch로 검증)

### 3-1. uiMapID → 맵 텍스처: wago.tools 파이프라인 ✅

API 키 불필요, 전부 HTTP GET:

```
1) https://wago.tools/db2/UiMapXMapArt/csv?filter[UiMapID]=2082   → UiMapArtID=1754
2) https://wago.tools/db2/UiMapArtTile/csv?filter[UiMapArtID]=1754 → 3행×4열, FileDataID 4692773~4692784
3) https://wago.tools/api/casc/{fdid}                              → BLP 타일(256×256) 바이너리 (검증: 43.8KB 정상 수신)
4) Pillow가 BLP 네이티브 지원 → 스티칭(1024×768) → 1002×668 크롭 → PNG 캐시
```

### 3-2. 월드좌표 → 맵픽셀 변환: UiMapAssignment ✅

```
https://wago.tools/db2/UiMapAssignment/csv?filter[UiMapID]=2082
→ Region: worldX ∈ [-411.667, 221.667], worldY ∈ [-575.0, 375.0]  (OrderIndex 0 행 하나면 충분)

u (가로 0→1) = (maxY − worldY) / (maxY − minY)    # +Y=서쪽 = 지도 왼쪽
v (세로 0→1) = (maxX − worldX) / (maxX − minX)    # +X=북쪽 = 지도 위
```

실측 좌표(x∈[-6,25], y∈[-216,-187])가 이 Region 안에 정확히 들어감 → 정합성 OK. 단 위키 문서상 X/Y 라벨이 뒤집혀 기술된 전통이 있으므로 **첫 구현 때 실데이터로 1회 캘리브레이션**(블립이 90° 돌아가 보이면 축 스왑) 필요.

- 층 구분: `UiMap` 테이블의 ParentUiMapID로 형제 층 열거 (주입의 전당 2층 = 2083). 로그의 uiMapID가 층까지 구분해 주므로 층 전환도 자동.
- 인스턴스당 다운로드는 최초 1회 → `data/replay_maps/{uiMapID}.png` + `{uiMapID}.json`(Region) 캐시. 오프라인 exe에서도 캐시만 있으면 동작.

### 3-3. 대안 소스 (플랜 B)

- warcraft.wiki.gg 완성 이미지: `https://warcraft.wiki.gg/images/WorldMap-HallsOfInfusion_A.jpg?format=original` (1002×668 수신 확인). 파일명이 인스턴스마다 일관되지 않아 자동화엔 부적합 — 수동 보충용.
- Blizzard 공식 Game Data API에는 던전 바닥 지도가 **없음** (로딩스크린/홍보 이미지뿐).
- WCL replay도 결국 게임 파일에서 추출한 2D 지도 위에 좌표를 그리는 같은 방식 (공개 포럼에서 확인: API는 좌표+mapID만 제공).

### 3-4. 라이선스

맵 타일은 Blizzard 저작물. **exe에 동봉 배포하지 말고, 사용자 PC에서 런타임에 받아 로컬 캐시**하는 방식 권장 (wow.export, WCL 컴패니언과 같은 커뮤니티 관행).

### 3-5. 3D 지형(V3) 현실성 — 비추천

- 보스방은 대부분 WMO(인스턴스 건물) 내부. 수동 추출은 wow.export가 GLB/OBJ 내보내기를 지원해 쉬운 편이지만, uiMapID→WMO 자동 파이프라인(WMOGroupID 매핑, 배치 좌표 정렬)은 상당한 R&D.
- 결정타: **로그에 Z좌표가 없어서** 지형을 만들어도 유닛 높이를 알 수 없음. 바닥 레이캐스트로 스냅하는 방법이 있지만 다층 구조물(카이메루스 플랫폼 같은)에서 틀린 층에 붙는 문제가 생김.
- 결론: V3는 "특정 보스방 1~2개를 수작업 아트 에셋으로 넣는 이벤트성 작업"으로만 고려. 자동화 대상 아님.

---

## 4. 설계안

### 4-1. 단계

**MVP — 2D 탑다운 (3~4일)**
1. 서버 `app/replay_map.py` (신규): uiMapID → wago.tools fetch → 스티칭 PNG + Region JSON 캐시 → `GET /api/replay-map/{uiMapID}` (~150줄, Pillow 의존성 추가)
2. `local_replay.py` 확장:
   - 아카이브 로그 지원: `warcraftlogsarchive\Archive-*.txt`도 인덱싱. 1GB 파일이므로 인코더 인덱스에 **바이트 오프셋** 저장 후 `fh.seek()` (지금은 줄번호라 처음부터 읽음)
   - "로그 전용 리플레이": CCTV 캡처 없이 ENCOUNTER 목록에서 바로 열기 (지금은 영상이 있어야만 상세를 볼 수 있음)
   - 좌표 다운샘플 0.5s 그리드 + SWING 이벤트 좌표도 수용 + 쫄 포함(샘플 10개 이상 유닛)
   - 죽음/주요기믹 마커는 기존 events(kind: death/cast/debuff)를 그대로 사용
3. 프런트: `renderReplayMap()`의 SVG를 canvas로 교체 — 배경에 맵 PNG, world→pixel 변환, 선형보간, 최근 6초 궤적, facing 눈금, 스크럽 연동(스파이크 코드 이식 수준)

**V2 — 2.5D three.js (+2~3일)**
- three.module.min.js r185 (~357KB, ESM 전용)를 `app/static/vendor/`에 넣고 importmap으로 로드. 앱은 pywebview(WebView2, WebGL OK)가 `http://127.0.0.1:포트`로 서빙하므로 CDN·CSP 문제 없음. exe는 `LogAnalyze.spec`의 `datas=[('app/static', 'app/static')]`에 자동 포함.
- 씬: 맵 PNG를 PlaneGeometry 텍스처로, 유닛은 SpriteMaterial 빌보드(직업색 원 + 이름), OrbitControls로 틸트/줌. 렌더 루프는 MVP와 같은 보간 함수 공유.
- 2D/2.5D 토글 버튼 하나로 두 렌더러 전환.

**V3 — 지형 기복 (보류)**
- 조건이 갖춰지면(특정 보스방 한정, wow.export 수동 추출 GLB): three.js GLTFLoader로 로드 + 수동 정렬. Z 부재 문제 때문에 자동화 불가. 우선순위 낮음.

### 4-2. 데이터 흐름 (MVP)

```
Archive-*.txt / WoWCombatLog-*.txt
  └(1회 인덱싱: ENCOUNTER 목록 + 바이트오프셋, lru_cache)
GET /api/local-replay/{id}  (또는 신규 log-only id)
  └구간 seek → 파싱 → {actors, events, tracks:[{guid, class, points:[[t,x,y,facing],...]}], ui_map_id, bounds}
GET /api/replay-map/{uiMapID}
  └캐시 PNG (+ Region JSON은 상세 응답에 포함)
프런트: 맵 draw → t 슬라이더/영상 sync → 유닛별 이진탐색+선형보간 → canvas
```

### 4-3. 리스크와 대응

| 리스크 | 대응 |
|---|---|
| wago.tools 다운/포맷 변경 | 캐시 우선 + 위키 이미지 수동 대체 경로. 실패해도 지금처럼 "빈 배경 + 점" 폴백 |
| 축 방향 실수 (X/Y 스왑) | 구현 첫날 실데이터 캘리브레이션 항목으로 명시 (§3-2) |
| 1GB 아카이브 스캔 느림 | 바이트오프셋 인덱스 + 파일별 1회 lru_cache. 인덱싱도 ENCOUNTER 줄만 찾으므로 수 초 |
| 텔레포트/위상 전투(맵 전환) | 로그 uiMapID가 바뀌는 순간 맵도 전환 (이미 필드가 있으므로 공짜) |
| 좌표 없는 유닛(한 번도 이벤트 소스가 안 된 쫄) | 표시 대상에서 자연 제외 — WCL도 동일 한계 |

---

## 5. 스파이크 산출물 (완료)

| 파일 | 내용 |
|---|---|
| `tmp_replay_spike.html` (저장소 루트) | **의존성 0, 이 파일 하나로 동작.** 감시자 이리데우스 58.5초 풀, 6유닛 2,622좌표. 재생/배속/스크럽, 선형보간, 최근 6초 궤적, facing 표시. 브라우저 실행으로 동작 확인 완료(콘솔 에러 0) |
| scratchpad `measure_positions.py` / `spike_positions.json` | 밀도 실측 스크립트 + 추출 좌표(임시 산출물) |

스파이크가 증명한 것: 로그 좌표만으로 부드러운 유닛 이동 재현이 됨, 보간 전략이 유효함, 좌표계 방향(북=위) 처리 방식이 맞음. 남은 것은 배경에 실제 맵 PNG를 까는 것(§3-1 파이프라인)뿐이다.
