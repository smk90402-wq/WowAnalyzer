---
name: Git LFS 로 v2_cache PC 간 sync
description: backfill 캐시 (특히 ~380MB events.json) 는 GitHub 100MB 한도 초과 → LFS 사용. 다른 PC 에서 이어받기 위한 셋업.
type: reference
---

**상황:** `data/v2_cache_*.json` 4개 (~430MB 총합, events.json 만 ~380MB) 는 GitHub 일반 파일 한도 (100MB/파일) 초과. 그래서 Git LFS 로 트래킹 (.gitattributes 에 등록됨).

**트래킹 패턴:** `data/v2_cache_*.json` — 4개 캐시 파일 모두 LFS 거침
**제외:** `data/cache.db` (사용 안 함), `data/spell_db_en.json` (지금 없음), `data/cache_*.json` (옛 V1, 사용 안 함), `data/user_settings.json` (PC 별), `data/backfill.log` (런타임)

**새 PC 셋업 절차 (집 PC 등):**

```bash
# 1. Git LFS 설치 — Git for Windows 최신은 기본 포함, 아니면 git-lfs.github.com
# 2. 레포 클론 (or pull) + LFS 활성화
git clone https://github.com/smk90402-wq/WowAnalyzer.git
cd WowAnalyzer
git lfs install   # one-time per PC

# 3. LFS 파일들 가져오기 — clone/pull 시 자동이지만 확인용
git lfs pull
ls -la data/v2_cache_events.json   # ~380MB 면 정상

# 4. pip + .env 세팅 (별도 — keys_local.txt 참고)
# 5. backfill 이어서
python backfill_v2.py
```

**Why:**
- backfill 캐시는 시간/포인트 비싸서 (~3시간, ~57000 pts) 한 번 받으면 PC 간 sync 가치 큼
- LFS 가 GitHub 100MB 한도 우회 + bandwidth 효율적 (변경분만 전송)
- 1GB storage / 1GB bandwidth/월 free tier — 풀백필 1회 + 가끔 갱신이면 충분

**How to apply:**
- backfill 완료된 후 한 번만 push 권장 (LFS bandwidth 절약)
- 작업 중 자주 push 하면 LFS storage 한도 차오름 — old version 들이 누적됨
- 한도 차면 추가 데이터 팩 ($5/월/50GB)
- `git pull` 만 해도 LFS smudge 자동 실행됨 — 별도 `git lfs pull` 필요 시 LFS 가 누락된 파일만 받아옴
