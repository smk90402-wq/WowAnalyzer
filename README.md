# 한밤 레이드 로그 분석기

WoW 한밤(Midnight) 확장 첫 레이드의 WarcraftLogs 톱100 로그를 긁어와
스펙별/보스별로 **상황별 딜사이클**(쿨다운 · 물약 · 생존기 · 프록 · 추적버프)을
공부하기 위한 도구.

> **상태 (2026-05-22)**: serve.py (FastAPI + pywebview) 기반 SPA.
> 데이터 백필 완료, 빌드/실행 안정. 새 PC 셋업은 `bootstrap_dev.py` 한 방.

---

## 새 PC 에서 셋업 (회사 PC 등에서 pull 후)

```bash
git clone https://github.com/smk90402-wq/WowAnalyzer
cd WowAnalyzer
python bootstrap_dev.py
```

`bootstrap_dev.py` 가 자동으로:
1. `git lfs install` + `git lfs pull` — `data/v2_cache_*.json` (380MB+) 받기
2. `pip install -r requirements.txt`
3. `.env` 없으면 `.env.example` 복사 (4개 키 수동 입력 필요)
4. `dist/LogAnalyze` 존재 시 data junction + .env 복사

`.env` 키 4개 (메인 PC 의 `keys_local.txt` 그대로 옮김):
- `WCL_V2_CLIENT_ID`, `WCL_V2_CLIENT_SECRET` — WarcraftLogs V2 GraphQL
- `BLIZZARD_CLIENT_ID`, `BLIZZARD_CLIENT_SECRET` — Blizzard Game Data (한글 메타)

## 빌드 & 실행

```
build.bat                          # PyInstaller slim build → dist\LogAnalyze\LogAnalyze.exe
run.bat                            # 빌드된 .exe 있으면 그거, 없으면 python serve.py
```

직접:
```
python serve.py                    # GUI 윈도우 + FastAPI 백엔드 (port 9876)
python serve.py --api-only         # 백엔드만 (브라우저 devtools 디버그 용)
```

## 데이터 파이프라인

```
fetch_rankings_v2.py    →  data/rankings_zone46_{heroic,mythic}_dps_top100.csv
                          (랭킹 + class/spec/dps/server/ilvl/report_id/fight_id)

backfill_v2.py          →  data/v2_cache_player_fight.json  (talents/gear/stats)
                          data/v2_cache_events.json         (casts/buffs — 380MB LFS)
                          data/v2_cache_report_meta.json    (fight 메타)

prefetch_prepull.py     →  data/v2_cache_prepull_buffs.json (음식/영약/오일/숫돌)
fetch_pi_received.py    →  data/v2_cache_pi_received.json   (사제 PI 수령)
fetch_talent_trees.py   →  data/talent_trees.json           (Blizzard 트리 구조)
enrich_spell_ko.py      →  data/spell_db.json               (한글 spell + 아이콘)

serve.py + app/         →  FastAPI + pywebview SPA (HTML/CSS/JS in app/static/)
```

각 스크립트 재실행 안전 — `data/v2_cache_*.json` 캐시로 페치 건너뜀.
`enrich_spell_ko.py` 는 `v2_cache_events.json` 도 source 로 스캔 (전사 등
누락 spell 자동 발견).

## API 자격증명

| 종류 | 용도 | 발급 위치 |
|---|---|---|
| `WCL_V2_CLIENT_ID` + `WCL_V2_CLIENT_SECRET` | WarcraftLogs V2 GraphQL | [api/clients](https://www.warcraftlogs.com/api/clients) |
| `BLIZZARD_CLIENT_ID` + `BLIZZARD_CLIENT_SECRET` | Blizzard Game Data — 한글 메타 | [develop.battle.net](https://develop.battle.net/access/clients) |

### WCL 구독 (선택 — rate limit 만 영향)

| 등급 | 가격/월 | 시간당 포인트 |
|---|---|---|
| Free | $0 | 3,600 |
| Gold | $5 | 9,000 (2.5x) |
| Platinum | $10 | 18,000 (5x) — 백필 워크로드 추천 |

## 스택

- **Python 3.10+**
- **FastAPI + uvicorn** — REST API (CSV → JSON, 캐시 lookup)
- **pywebview (EdgeChromium)** — 데스크탑 윈도우, 별도 브라우저 없음
- **vanilla JS SPA** — 프레임워크 없음, `app/static/`
- pandas / scikit-learn — 군집/통계
- requests / python-dotenv — API

## 디렉토리

```
app/                  FastAPI 백엔드 + 정적 SPA
  main.py             엔드포인트 정의 (/api/rankings, /api/character, ...)
  talent_tree.py      특성 트리 HTML 생성 (iframe srcdoc)
  timeline.py         딜사이클 HTML + JS (translate3d 드래그, clampTip 툴팁)
  static/             index.html / main.css / main.js
serve.py              엔트리 — uvicorn (백그라운드 스레드) + pywebview (메인)
wcl_v2.py             V2 GraphQL OAuth 클라이언트
wcl_v2_data.py        V2Data — 캐시 + 페치 통합
data/                 캐시 JSON, CSV (LFS)
memory/               feedback rules (Claude 가 turn 간 학습 내용)
```

## 라이선스 / 데이터 출처

- 로그: [WarcraftLogs](https://www.warcraftlogs.com/) V2 GraphQL
- 스펠: [WoWhead](https://ko.wowhead.com/) 한글 메타
- 코드: 본인 사용 목적, 별도 라이선스 미지정
