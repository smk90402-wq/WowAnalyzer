"""캐시 매니페스트 재생성 — PC 간 동기화 계약서.

원칙: 분석 결과물·코드는 git 커밋 / 재생성 가능한 대용량 캐시는 여기 명시(재생성 명령 포함).
다른 PC에서 pull 후 이 파일을 보고 어떤 캐시를 어떻게 채울지 판단.

실행: python make_cache_manifest.py   (캐시 변경 후 커밋 전에)
"""
from __future__ import annotations
import sys, json, time, socket
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

# frozen exe 에선 exe 옆 data 정션, 아니면 프로젝트 루트 data (main.py DATA_DIR 와 동일 규칙)
if getattr(sys, "frozen", False):
    DATA = Path(sys.executable).parent / "data"
else:
    DATA = Path(__file__).parent / "data"


def keys_of(fname, data_dir=None):
    p = (data_dir or DATA) / fname
    if not p.exists():
        return []
    try:
        return sorted(json.loads(p.read_text(encoding="utf-8")).keys())
    except Exception:
        return []


def build_manifest(data_dir=None) -> dict:
    """디스크의 캐시 파일을 읽어 매니페스트 dict 생성 — 앱 atexit/standalone 공용 단일 소스."""
    dd = data_dir or DATA
    m = {
        "generated_at": time.time(),
        "host": socket.gethostname(),
        "pfight_keys": keys_of("v2_cache_player_fight.json", dd),
        "events_keys": keys_of("v2_cache_events.json", dd),
        "report_meta_rids": keys_of("v2_cache_report_meta.json", dd),
        "pi_fight_keys": keys_of("v2_cache_pi_fight.json", dd),
        "kr_roster_keys": keys_of("v2_cache_kr_roster.json", dd),
        # 커밋 안 하는 대용량 파일 — 다른 PC에서 아래 명령으로 재생성 (전부 캐시 재개형이라 안전)
        "uncommitted_large_files": {
            "kr_mythic_rankings.json": {
                "desc": "KR 신화 27스펙×9보스 전수 랭킹 (막공 환영도 v2 원시)",
                "regen": "python fetch_kr_pug_market.py  # step1, 캐시 재개형",
            },
            "v2_cache_kr_roster.json": {
                "desc": "KR 신화 킬공대 로스터 1,316전투 (보스당 150 표본)",
                "regen": "python fetch_kr_pug_market.py  # step3, 캐시 재개형",
            },
            "tmp_mm_events.json": {
                "desc": "MM 433명 캐스트/버프 추출본 (어둠순찰자 분석용)",
                "regen": "python analyze_mm_dr_cycle.py  # v2_cache_events.json 에서 추출, 1~3분",
            },
            "tmp_caster_events.json": {
                "desc": "정기·악마 상위 표본 캐스트/버프 추출본 (딜사이클 버튼·유틸 분석용)",
                "regen": "python analyze_caster_cycle.py  # v2_cache_events.json 에서 추출, 1~3분",
            },
            "v2_cache_events.json / v2_cache_player_fight.json / v2_cache_report_meta.json / v2_cache_pi_fight.json": {
                "desc": "WCL 원시 캐시 (LFS 트래킹, push 회피 정책)",
                "regen": "backfill_v2.py / fetch_pi_all.py — 위 *_keys 목록과 대조해 부족분만",
            },
        },
        # 커밋되는 분석 결과물 (참고 — 이건 pull 만 하면 됨)
        "committed_results": [
            "kr_pug_market.json", "kr_heroic_pop.json", "pug_demand_inven.json", "pug_welcome_analysis.json",
            "boss_stats.json", "stat_dr.json", "talent_trees.json", "rotation_data.json", "spec_guide.json",
            "tmp_mm_builds.csv", "tmp_mm_cycle.json", "tmp_mm_dr_targets.json",
            "tmp_mm_situations.json", "tmp_mm_hp_windows.json", "tmp_caster_cycle.json",
        ],
    }
    return m


def write_manifest(data_dir=None) -> dict:
    """build_manifest() → data/cache_manifest.json 저장. 앱 atexit·standalone 공용."""
    dd = data_dir or DATA
    m = build_manifest(dd)
    (dd / "cache_manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return m


def main():
    m = write_manifest()
    print(f"매니페스트 갱신: pfight {len(m['pfight_keys'])} · events {len(m['events_keys'])} · "
          f"meta {len(m['report_meta_rids'])} · pi {len(m['pi_fight_keys'])} · kr_roster {len(m['kr_roster_keys'])}")


if __name__ == "__main__":
    main()
