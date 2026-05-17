"""네임드별 단일특/광특 빌드 분포 카운터.

`rankings_with_talents.csv` 의 `hero_cluster` (classify_talents.py 가 만든
KMeans 군집) 을 보스별로 세서 어떤 군집이 우세한지 본다.

군집 자체엔 "ST/AoE/Hybrid" 라벨이 없으므로:
  1) `data/cluster_labels.csv` 가 있으면 그 라벨을 적용해서 사람용 결과 출력
     (columns: class, spec, hero_cluster, label, note)
  2) 라벨 파일이 없으면 빈 템플릿을 생성하고 raw 카운트만 출력 — 사용자가
     `data/hero_cluster_map.csv` 의 시그니처 특성을 보고 직접 채우면 됨.

타깃 스펙(현재 비전): 악마흑마, 조화드루, 야수냥꾼.
다른 스펙도 같이 처리하지만 출력은 타깃을 위로 끌어올림.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path(__file__).parent / "data"
RANKS = DATA / "rankings_with_talents.csv"
LABELS = DATA / "cluster_labels.csv"
OUT_COUNTS = DATA / "boss_build_counts.csv"
OUT_LABELED = DATA / "boss_build_labeled.csv"

TARGETS = [
    ("Warlock", "Demonology"),
    ("Druid",   "Balance"),
    ("Hunter",  "Beast Mastery"),
    ("Warrior", "Arms"),
    ("Warrior", "Fury"),
]


def ensure_label_template(clusters: pd.DataFrame) -> None:
    """라벨 CSV 가 없으면 빈 템플릿을 생성."""
    if LABELS.exists():
        return
    tmpl = clusters[["class", "spec", "hero_cluster"]].drop_duplicates().sort_values(
        ["class", "spec", "hero_cluster"]
    )
    tmpl["label"] = ""
    tmpl["note"] = ""
    tmpl.to_csv(LABELS, index=False, encoding="utf-8-sig")
    print(f"\n라벨 템플릿 생성 → {LABELS}")
    print("  label 컬럼에 ST / AoE / Hybrid 등 직접 채워넣고 다시 실행하면")
    print("  보스별 ST/광 분포가 출력됨.")
    print("  시그니처 특성 참고: data/hero_cluster_map.csv")


def main() -> None:
    if not RANKS.exists():
        sys.exit(f"입력 없음: {RANKS}\nclassify_talents.py 를 먼저 돌려.")

    df = pd.read_csv(RANKS)
    df = df[df["hero_cluster"] >= 0].copy()
    df["hero_cluster"] = df["hero_cluster"].astype(int)

    # 보스 × 직업 × 스펙 × 군집 카운트
    counts = (
        df.groupby(["encounter_name", "class", "spec", "hero_cluster"])
        .size()
        .rename("n")
        .reset_index()
    )
    counts.to_csv(OUT_COUNTS, index=False)

    # 라벨 적용
    ensure_label_template(counts)
    labels = pd.read_csv(LABELS) if LABELS.exists() else pd.DataFrame()

    if labels.empty or labels["label"].dropna().eq("").all():
        # 라벨 미작성 → raw 카운트만 보여줌 (타깃 위주)
        print("\n=== 보스별 군집 분포 (raw — 라벨 미적용) ===")
        for cls, spec in TARGETS:
            sub = counts[(counts["class"] == cls) & (counts["spec"] == spec)]
            if sub.empty:
                continue
            piv = sub.pivot_table(
                index="encounter_name", columns="hero_cluster", values="n", fill_value=0
            )
            print(f"\n[{cls} / {spec}]")
            print(piv.to_string())
        return

    # 라벨 매핑
    merged = counts.merge(labels[["class", "spec", "hero_cluster", "label"]],
                          on=["class", "spec", "hero_cluster"], how="left")
    merged["label"] = merged["label"].fillna("").astype(str).str.strip()
    merged.to_csv(OUT_LABELED, index=False)

    print("\n=== 보스별 단일/광 빌드 분포 (라벨 적용) ===")
    for cls, spec in TARGETS:
        sub = merged[(merged["class"] == cls) & (merged["spec"] == spec)]
        if sub.empty:
            continue
        piv = sub.pivot_table(
            index="encounter_name", columns="label", values="n",
            aggfunc="sum", fill_value=0,
        )
        if piv.empty:
            continue
        piv["total"] = piv.sum(axis=1)
        for col in piv.columns:
            if col == "total":
                continue
            piv[f"{col}_%"] = (piv[col] / piv["total"] * 100).round(1)
        print(f"\n[{cls} / {spec}]")
        print(piv.to_string())

    print(f"\n저장: {OUT_COUNTS}")
    if OUT_LABELED.exists():
        print(f"저장: {OUT_LABELED}")


if __name__ == "__main__":
    main()
