# TODO

## BM 장신구 심층 분석 캐시 이어받기

현재 저장 상태:
- `data/v2_cache_player_fight.json`: BM top100 기준 740/900 playerDetails, gear, stats 캐시 완료
- `data/bm_trinket_deep_cache.json`: BM top25 기준 197/225 full ability/target damage table 캐시 완료
- `data/v2_cache_damage.json`: BM full-fight DamageDone ability table 일부 추가 저장 완료
- `data/bm_trinket_deep_cache.json`의 20초 윈도우 damage table은 smoke test용 18개 row만 있음

남은 작업:
- BM top100 나머지 160개 playerDetails/gear/stats 캐시 이어받기
- BM top25 나머지 28개 full ability/target damage table 이어받기
- 보스별 `알른 응시 + 상자` vs `알른 응시 + 특화 꽁지깃` vs `알른 응시 + 치명 꽁지깃` 비교표 재계산
- 상자/BW 20초 윈도우 damage table은 전체 top25에 바로 돌리지 말고, 우선 보스별 대표 표본만 제한해서 수집
- `DamageDone viewBy: Ability/Target` 기반으로 상자 선택자가 실제로 살상 명령, 쇄도, 마구잡이 난타, 펫딜, 쫄 타겟 피해에서 어떤 차이를 내는지 분석
- 분석 결과를 `data/bm_trinket_recommendations.json`과 UI 장신구 추천 설명에 반영

집에서 이어받기 권장 순서:

```powershell
git pull
git lfs pull

# 남은 playerDetails/full-fight damage cache 이어받기
$env:PYTHONIOENCODING='utf-8'
python .\prefetch_bm_trinket_deep_cache.py --player-topn 100 --deep-topn 25 --no-windows --flush-every 10

# 이후 필요한 대표 표본만 window damage 수집
python .\prefetch_bm_trinket_deep_cache.py --player-topn 100 --deep-topn 25 --max-box-windows 2 --max-bw-windows 2 --flush-every 10
```

주의:
- `serve.py --api-only --host 0.0.0.0 --port 424` 서버 프로세스는 유지해도 됨
- 프리패치 중단 시 `Get-CimInstance Win32_Process -Filter "name = 'python.exe'"`로 `prefetch_bm_trinket_deep_cache.py`만 확인하고 중지
- WCL v2는 집계 분석에 raw events보다 `table(DamageDone)`을 우선 사용

---

## 인프라: git 용량 정리 + 서버 구축 (2026-07-06 논의, 나중에)

### 1. `.git` 저장소 비대 정리 (현재 3.1GB)
- **현황**: `data/` 실물 1.9GB 중 대부분은 WCL 원본 캐시(`v2_cache_events.json` 1.48GB·`report_meta` 248MB·`player_fight` 134MB) — `.gitignore`의 `data/v2_cache_*.json`로 **git 제외돼 히스토리에 없음(확인 완료, 가장 큰 blob은 17MB짜리 rankings)**. github에는 분석 산출물만(97파일 21.8MB) 올라감.
- **문제 원인**: 매일 갱신되는 중간 파일들(rankings CSV 3.3MB, `kr_mythic_rankings.json` 17MB, `rotation_data.json`, `talent_trees.json`)이 수십 커밋에 걸쳐 통째로 재커밋되며 히스토리 누적. gitignore는 새 커밋만 막지 과거는 안 줄임.
- **할 일**:
  - [ ] `git gc --aggressive --prune=now`로 우선 압축 (얼마나 줄지 확인)
  - [ ] 그래도 크면: 자주 바뀌는 대용량 CSV(`rankings_*`, `kr_mythic_rankings.json`)를 Git LFS로 이전하거나 gitignore에 넣고 산출물만 추적 (히스토리 재작성 = `git filter-repo`, 백업 후)
  - [ ] 결정: rankings/talent_trees 같은 "매일 갱신되는 원본"을 git에 계속 둘지, 로컬/LFS로 뺄지

### 2. 서버 구축 (목적·예산 미정 — 정하면 착수)
- **전제**: pywebview(데스크톱 창)만 빼면 `serve.py --api-only --host 0.0.0.0 --port <p>`로 이미 FastAPI 서버로 뜸. 코드 변경 최소.
- **후보 3안**:
  - **A. 클라우드 VPS** (월 $5~20): serve.py + WCL 백필을 24시간 상시. 캐시도 VM 디스크(1.5GB 이전 필요). PC 자유·어디서나 접속. 인증/방화벽 세팅 필요.
  - **B. 집 PC 서버** (무료): exe 대신 serve.py 상시 실행 + Cloudflare Tunnel 외부 접속. 캐시 그대로. PC 켜놔야 함·보안 신경.
  - **C. 결과만 배포** (거의 공짜): 수집·분석은 로컬, 산출 JSON만 정적 호스팅(github pages 등) 읽기전용 웹. 실시간 수집 불가.
- **결정 필요**: ①주 목적(24시간 수집 / 어디서나 나만 접속 / 남도 공개 / 백업만) ②예산(무료 / 월 1만 / 월 2~4만) → 셋 중 택. 공개 시 인증·보안 설계 추가.
- **참고**: 위 §1(git 용량)과 연동 — 캐시를 서버로 옮기면 로컬 git 부담도 줄어듦.
