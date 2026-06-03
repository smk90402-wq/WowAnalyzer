"""오버나잇 무인 파이프라인 — PI + casts 풀백필 → 한글화 → 4차원 종합.

각 단계 resumable (캐시 skip). 중간에 죽어도 재실행하면 이어서.
순차 subprocess (캐시 동시쓰기 회피). 한 단계 실패해도 다음 진행.

실행: python run_full_analysis.py   (백그라운드 권장)
산출:
  data/v2_cache_pi_fight.json, rankings_..._pi.csv   (PI)
  data/v2_cache_events.json (casts 전 스펙)
  data/spell_db.json (신규 스펠 한글)
  data/pi_impact.csv, rotation_difficulty.csv, parse_consistency.csv
  data/spec_meta_ranking.csv  ← 최종 4차원 종합
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).parent
PY = sys.executable

STEPS = [
    ("1. PI 풀백필 (mythic 전 fight)",      [PY, "fetch_pi_all.py", "5"]),
    # casts 는 스펙당 300 캡 — 로테 지표는 ~100 수렴, 풀 900은 동일값에 12h+ 낭비.
    # (PI 는 1단계서 풀. 로테/앱 타임라인엔 300이면 충분.)
    ("2. casts 백필 (전 스펙, 스펙당 300)", [PY, "backfill_v2.py", "--all", "--per-spec", "300"]),
    ("3. 신규 스펠 한글화",                [PY, "enrich_spell_ko.py"]),
    ("4. PI 영향 재계산",                 [PY, "analyze_pi_impact.py"]),
    ("5. 로테 난이도 (전 스펙)",          [PY, "rotation_difficulty.py", "mythic"]),
    ("6. 4차원 종합",                    [PY, "analyze_spec_meta.py"]),
]


def main() -> None:
    t0 = time.time()
    print(f"=== 오버나잇 파이프라인 시작 ({len(STEPS)} 단계) ===", flush=True)
    results = []
    for name, cmd in STEPS:
        print(f"\n{'='*64}\n>>> {name}\n{'='*64}", flush=True)
        ts = time.time()
        try:
            r = subprocess.run(cmd, cwd=ROOT)
            rc = r.returncode
        except Exception as e:
            print(f"  단계 예외: {e}", flush=True)
            rc = -1
        el = time.time() - ts
        print(f"<<< {name}  exit={rc}  ({el/60:.1f}분)", flush=True)
        results.append((name, rc, el))

    total = time.time() - t0
    print(f"\n{'='*64}\n=== 파이프라인 완료 ({total/3600:.1f}시간) ===\n{'='*64}", flush=True)
    for name, rc, el in results:
        mark = "OK" if rc == 0 else f"FAIL({rc})"
        print(f"  [{mark:>8}] {name}  {el/60:.1f}분", flush=True)

    try:
        from update_log import record
        record(action="run_full_analysis",
               params={"steps": len(STEPS)},
               result={"hours": round(total/3600, 2),
                       "fails": sum(1 for _, rc, _ in results if rc != 0)},
               files=["data/spec_meta_ranking.csv"])
    except Exception:
        pass


if __name__ == "__main__":
    main()
