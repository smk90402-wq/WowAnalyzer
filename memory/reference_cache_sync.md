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
