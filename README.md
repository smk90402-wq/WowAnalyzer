# 한밤 레이드 로그 분석기

WoW 한밤(Midnight) 확장 첫 레이드의 WarcraftLogs 톱100 로그를 긁어와
스펙별/보스별로 **상황별 딜사이클**(쿨다운 · 물약 · 생존기 · 프록 · 추적버프)을
공부하기 위한 도구.

> **상태**: 데이터 파이프라인은 돌아감. GUI는 PySide6 스켈레톤 단계.
> 캐스트 이벤트 fetch 완료 후 한글 스펠 DB · 버프 이벤트 fetch ·
> 카이메루스 1조/2조 추론 · 타임라인 뷰가 차례로 붙는다.

---

## 파이프라인

```
fetch_rankings.py    →  data/rankings_zone46_mythic_dps_top100.csv
enrich_pi.py         →  data/rankings_..._pi.csv         (Power Infusion 수령 여부)
enrich_talents.py    →  data/cache_talents.json          (특성 ID)
classify_talents.py  →  data/rankings_with_talents.csv   (영웅특성 k-means 군집)
                       data/hero_cluster_map.csv         (군집별 시그니처 특성)

analyze_difficulty.py →  data/difficulty_ranking.csv     (CV 기반 스펙 쉬움도)
analyze_pi_impact.py  →  data/pi_impact.csv              (PI 받은 vs 안 받은 영향)
analyze_ramp.py       →  (램프/셋업 분석)
analyze_hero.py       →  data/hero_analysis.csv          (군집 × ease × PI 통합)

fetch_casts.py        →  data/cache_casts.json           (캐스트 이벤트)
                        data/cache_source_ids.json      (캐릭→소스ID 매핑)
                        data/spell_db_en.json            (영문 스펠 메타)
enrich_gear.py        →  data/cache_gear.json            (장비 슬롯·보석·마부·보너스)

analyze_builds.py     →  data/boss_build_counts.csv      (보스별 군집 카운트)
                        data/cluster_labels.csv          (사용자 라벨 템플릿)

gui.py                →  PySide6 GUI 메인 (PyInstaller 로 .exe 빌드)
build.bat             →  PyInstaller .exe 빌드
run.bat               →  .exe 있으면 그거, 없으면 python gui.py
```

## 설치

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Linux/macOS

pip install -r requirements.txt
cp .env.example .env              # 그 다음 .env 채우기 (아래 참고)
```

### API 자격증명

| 종류 | 용도 | 발급 위치 |
|---|---|---|
| `WCL_V1_KEY` | V1 (legacy) — 일부 enrich 호환 | [profile](https://www.warcraftlogs.com/profile) Web API |
| `WCL_V2_CLIENT_ID` + `WCL_V2_CLIENT_SECRET` | **V2 (메인)** — rdps 정상, 사이트와 일치 | [api/clients](https://www.warcraftlogs.com/api/clients) 에서 new client |

**V2 가 메인** — `metric=rdps` 가 V1 에선 500 server error 라 사이트 랭킹과 일치하지 않음.
V2 의 GraphQL `worldData.encounter.characterRankings` 가 정답.

### 구독 (선택 — rate limit 만 영향)

| 등급 | 가격/월 | 시간당 포인트 |
|---|---|---|
| Free | $0 | 3,600 |
| Gold | $5 | 9,000 (2.5x) |
| Platinum | $10 | 18,000 (5x) — 우리 워크로드 추천 |

Silver 는 API 혜택 없음.

## 실행

```bash
python fetch_rankings.py      # 랭킹 수집
python enrich_pi.py           # PI 버프 enrichment
python enrich_talents.py      # 특성 enrichment
python classify_talents.py    # 영웅특성 군집
python analyze_hero.py        # 통합 분석

python fetch_casts.py         # 타깃 3스펙의 모든 캐스트 이벤트
python gui.py                 # GUI 실행
```

각 스크립트는 `data/cache_*.json` 으로 재실행 안전 — Ctrl+C 중단해도
재기동하면 캐시된 만큼 건너뜀.

## 스택

- **Python 3.11+**
- **PySide6 (Qt 6.6+)** — RHI 백엔드(Windows D3D11) 로 위젯 GPU 가속
- **QtWebEngine** — Chromium 기반, WoWhead 한글 툴팁 위젯 임베드 예정
- pandas / scikit-learn (군집/통계)
- requests / python-dotenv (API)

## 라이선스 / 데이터 출처

- 로그 데이터: [WarcraftLogs](https://www.warcraftlogs.com/) V1 API
- 스펠 메타: [WoWhead](https://ko.wowhead.com/) (한글 이름·아이콘·툴팁 위젯)
- 코드: 본인 사용 목적, 별도 라이선스 미지정
