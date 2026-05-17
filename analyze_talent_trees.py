"""특성 ID 를 3-tree (공용 / 전문화 / 영웅) 로 분류 — 데이터 기반.

WCL `/summary` 가 tree 구분 정보를 안 줘서 외부 데이터(블리자드 API) 없이
같은 클래스의 다른 DPS 스펙들이 같은 talent ID 를 얼마나 공유하는지로
역추정한다.

규칙:
  - 같은 class 안에 N >= 2 DPS 스펙이 있을 때만 의미 있음
  - 모든 스펙(=N개) 에서 평균 픽률이 >= threshold 면 → 공용 (class tree)
  - 한 스펙에서만 거의 모든 사람이 픽 (>= 0.5), 다른 스펙은 거의 안 픽 (< 0.1)
    → 전문화 (spec tree)
  - 일부 (2~N-1) 스펙에서 함께 픽되면 → 영웅 (hero tree) 후보
  - 위 어디에도 안 맞으면 → 미분류

DPS 스펙이 1개뿐인 클래스 (Paladin Retri, Monk Windwalker 등):
  내부 분리 불가 → 일단 "spec" 라벨로 통합

산출: data/talent_tree_classification.csv
  columns: class, spec, talent_id, tree, pick_rate, pick_rate_others
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path(__file__).parent / "data"
CSV_IN = DATA / "rankings_with_talents.csv"
CACHE = DATA / "cache_talents.json"
OUT = DATA / "talent_tree_classification.csv"

CLASS_TREE_THRESHOLD = 0.7   # 다른 스펙 평균 픽률 >= 0.7 면 공용
SPEC_TREE_OWN_MIN   = 0.5    # 본 스펙 픽률 >= 0.5
SPEC_TREE_OTHER_MAX = 0.10   # 다른 스펙 평균 픽률 < 0.10 이면 전문화 단독
HERO_OTHER_MIN      = 0.20   # 다른 스펙에서 일부 공유 (영웅트리 후보)


def main() -> None:
    df = pd.read_csv(CSV_IN)
    df["report_id"] = df["report_id"].astype(str)
    df["fight_id"] = df["fight_id"].astype(int)

    talents_cache = json.loads(CACHE.read_text(encoding="utf-8"))

    # (class, spec) -> talent_id -> 픽한 사람 수
    pick_counts: dict[tuple[str, str], dict[int, int]] = {}
    sample_counts: dict[tuple[str, str], int] = {}

    for _, row in df.iterrows():
        cls = row["class"]; spec = row["spec"]
        rid = row["report_id"]; fid = int(row["fight_id"])
        char = row["character"]
        entry = talents_cache.get(f"{rid}:{fid}")
        if not isinstance(entry, dict):
            continue
        picks = entry.get(char)
        if not isinstance(picks, list):
            continue
        key = (cls, spec)
        sample_counts[key] = sample_counts.get(key, 0) + 1
        bucket = pick_counts.setdefault(key, {})
        for tid in picks:
            try:
                tid_i = int(tid)
            except (TypeError, ValueError):
                continue
            bucket[tid_i] = bucket.get(tid_i, 0) + 1

    # 클래스별 DPS 스펙 목록 (현 데이터 기반)
    class_specs: dict[str, list[str]] = {}
    for cls, spec in pick_counts.keys():
        class_specs.setdefault(cls, []).append(spec)

    # 픽률 변환
    pick_rate: dict[tuple[str, str], dict[int, float]] = {}
    for key, bucket in pick_counts.items():
        n = sample_counts.get(key, 1)
        pick_rate[key] = {tid: c / n for tid, c in bucket.items()}

    rows = []
    for (cls, spec), my_rates in pick_rate.items():
        others = [s for s in class_specs.get(cls, []) if s != spec]
        for tid, my_r in my_rates.items():
            # 다른 스펙들에서의 평균 픽률
            if others:
                other_rates = [pick_rate.get((cls, s), {}).get(tid, 0.0)
                               for s in others]
                other_avg = sum(other_rates) / len(other_rates)
                other_specs_with_pick = sum(1 for r in other_rates if r >= 0.30)
            else:
                other_avg = 0.0
                other_specs_with_pick = 0

            # 분류
            if not others:
                tree = "spec?"   # 비교 못함
            elif other_avg >= CLASS_TREE_THRESHOLD:
                tree = "공용"
            elif my_r >= SPEC_TREE_OWN_MIN and other_avg < SPEC_TREE_OTHER_MAX:
                tree = "전문화"
            elif my_r >= SPEC_TREE_OWN_MIN and other_specs_with_pick >= 1:
                tree = "영웅"
            elif other_avg >= HERO_OTHER_MIN and other_specs_with_pick >= 1:
                tree = "영웅"
            else:
                tree = "미분류"

            rows.append({
                "class": cls, "spec": spec, "talent_id": tid,
                "tree": tree,
                "pick_rate": round(my_r, 3),
                "pick_rate_others": round(other_avg, 3),
            })

    out_df = pd.DataFrame(rows).sort_values(
        ["class", "spec", "tree", "pick_rate"], ascending=[True, True, True, False]
    )
    out_df.to_csv(OUT, index=False)
    print(f"saved: {OUT}")

    # 요약
    print("\n=== 트리별 talent_id 수 (스펙별) ===")
    pivot = out_df.groupby(["class", "spec", "tree"]).size().unstack(fill_value=0)
    print(pivot.to_string())


if __name__ == "__main__":
    main()
