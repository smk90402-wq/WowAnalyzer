---
name: PC 간 캐시 sync 방법 (LFS 회피)
description: data/cache_manifest.json 으로 어떤 캐시가 있어야 하는지 명시. 다른 PC 가 알아보고 페치.
type: reference
---

**상황**: v2_cache_*.json (380MB+ events) 는 Git LFS 로 트래킹되지만 push 시 LFS bandwidth 부담 큼. 사용자 의도: "push 안 해도 돼, 리소스 많이 먹는다며".

**대신**: `data/cache_manifest.json` (~500KB, 일반 git) 에 캐시된 키 목록만 박아 push. 다른 PC 가 받으면 어떤 캐릭/fight 가 페치돼있어야 하는지 알 수 있음.

## manifest 구조

```json
{
  "generated_at": 1779775046.98,
  "host": "RTVMKSEO",
  "pfight_keys": ["zLtf3ZHjDRPqG4Xb:27:Mykimwarlock", ...],
  "events_keys": ["zLtf3ZHjDRPqG4Xb:27:43", ...],
  "report_meta_rids": ["zLtf3ZHjDRPqG4Xb", ...]
}
```

## 자동 갱신 시점

- `app/main.py` 의 `/api/character/{rid}/{fid}/{char}` endpoint 호출 후
- `atexit` 등록 — 정상 종료 시 (force-kill 은 잡지 못함)

## 다른 PC 에서 활용 (사용자 PC 가 작업)

1. `git pull` — cache_manifest.json 받음
2. 본인 PC 의 v2_cache_*.json 과 diff 비교 (누락된 키 식별)
3. 누락 키 페치:
   - 가장 단순: 사용자가 비교 탭에서 등록 캐릭 클릭 → recent reports 클릭 → 자동 V2 페치
   - 또는 backfill_v2.py 같은 스크립트로 일괄
4. 페치 후 본인 PC 의 manifest 도 갱신됨

## 우선순위 큰 캐릭

manifest 의 pfight_keys / events_keys 중 **등록 캐릭** (data/user_characters.json) 의 entries 를 우선 채워야 비교 분석 탭이 정상 동작.

키 패턴: `pfight_keys` 가 `{rid}:{fid}:{name}` 형식이므로 name 으로 필터링 가능.

## Why LFS 회피

- V2 cache 가 fight 늘 때마다 누적 → 수십 MB / 수백 MB
- 매 commit 마다 LFS bandwidth quota 소모 (GitHub LFS 무료 1GB/month)
- 의도: 캐시는 로컬, 메타데이터 (manifest, registered chars, spell_db, talent_trees) 만 sync

## 다음 단계 (미구현)

- `sync_cache_from_manifest.py` — manifest 보고 등록 캐릭의 누락 페치 자동
- 또는 .exe UI 에 "캐시 동기화" 버튼

## 2026-06-12 확장 — make_cache_manifest.py (재사용 생성 스크립트)

매니페스트 생성이 인라인뿐이어서 `make_cache_manifest.py` 신설 (캐시 변경 후 커밋 전에 실행).
구조 확장: `pi_fight_keys`·`kr_roster_keys` 추가 + **`uncommitted_large_files`**(커밋 안 하는 대용량의
재생성 명령 명시 — kr_mythic_rankings 18MB는 `fetch_kr_pug_market.py`, tmp_mm_events 25MB는
`analyze_mm_dr_cycle.py`, 전부 캐시 재개형) + `committed_results`(pull만 하면 되는 결과물 목록).
동기화 계약: **결과물·코드 = git / 재생성 가능 캐시 = manifest에 명령 명시**. 사용자 지시(2026-06-12):
"어떤 PC에는 데이터 있고 어떤 PC에는 없고 이런 일 없게" — 새 캐시 만들면 반드시 manifest에 등록할 것.

---

## update_log.json — 데이터 갱신 history (PC 간 sync)

`cache_manifest.json` 이 "어떤 캐시가 있나" 를 보여준다면, `update_log.json` 은
**"언제/어디서/뭐 갱신했는지"** history.

- 스키마: `{"entries": [{ts, host, action, params, result, files}, ...]}`
- 위치: `data/update_log.json` (~수십KB, 일반 git 트래킹)
- 최대 500 entries (오래된 건 자동 prune)

**자동 기록되는 작업:**
- `fetch_rankings_v2` — heroic/mythic 랭킹 CSV
- `backfill_v2` — pfight/events 캐시
- `prefetch_prepull` — 전투 직전 버프
- `enrich_kr` — spell_db / item_db 한글화
- `fetch_talent_trees` — Blizzard 트리 구조

각 스크립트 끝에 `from update_log import record` + `record(...)` 한 줄.
실패해도 silent skip (본 작업 결과 보호).

**CLI 조회:**
```
python update_log.py show       # 최근 20
python update_log.py show 50    # 최근 50
```

**활용 흐름:**
1. 집 PC 에서 `python fetch_rankings_v2.py 5` → update_log 자동 갱신
2. `git commit + push` (update_log.json + 갱신된 csv 포함)
3. 회사 PC 에서 `git pull` → `python update_log.py show` 로 "아 어젯밤
   집 PC 에서 mythic 랭킹 22948 rows 갱신됐네" 확인
