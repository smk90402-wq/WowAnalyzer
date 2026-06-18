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
