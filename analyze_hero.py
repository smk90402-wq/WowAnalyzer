"""Combined per (class, spec, hero_cluster) analysis.

Pulls three signals together:
  1) ease_score   : low CV + high median/top => easier to pull numbers
  2) pi_uplift_pct: median(with PI) vs median(without PI); high = PI-dependent
  3) sample size  : sanity guardrail

Hero clusters are the output of classify_talents.py (KMeans on talent-pick
vectors). Clusters are unnamed integers (0/1) -- the signature-talent CSV
(hero_cluster_map.csv) lets the user label them manually.
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
PI = DATA / "rankings_zone46_mythic_dps_top100_pi.csv"

MIN_N_PER_BOSS = 15
MIN_BOSSES = 2
MIN_PI_EACH = 10


def main() -> None:
    rt = pd.read_csv(RANKS)
    pi = pd.read_csv(PI)

    rt["report_id"] = rt["report_id"].astype(str)
    rt["fight_id"] = rt["fight_id"].astype(int)
    pi["report_id"] = pi["report_id"].astype(str)
    pi["fight_id"] = pi["fight_id"].astype(int)

    # Merge PI info onto the talent-labelled rankings
    merged = rt.merge(
        pi[["report_id", "fight_id", "character", "pi_received"]],
        on=["report_id", "fight_id", "character"],
        how="left",
    )
    merged = merged[merged["hero_cluster"] >= 0].copy()
    print(f"Rows with both hero cluster and PI data: "
          f"{merged['pi_received'].notna().sum()}/{len(merged)}")

    # --- ease score per (class, spec, hero_cluster) ---
    stats = (
        merged.groupby(["encounter_name", "class", "spec", "hero_cluster"])["dps"]
        .agg(n="count", mean="mean", std="std", median="median", top="max")
        .reset_index()
    )
    stats["cv"] = stats["std"] / stats["mean"]
    stats["median_to_top"] = stats["median"] / stats["top"]
    stats = stats[stats["n"] >= MIN_N_PER_BOSS].copy()

    def wmean(values, weights):
        return (values * weights).sum() / weights.sum()

    rows = []
    for (cls, spec, hc), g in stats.groupby(["class", "spec", "hero_cluster"]):
        if len(g) < MIN_BOSSES:
            continue
        w = g["n"]
        rows.append({
            "class": cls,
            "spec": spec,
            "hero_cluster": int(hc),
            "bosses": len(g),
            "total_n": int(w.sum()),
            "avg_cv": wmean(g["cv"], w),
            "avg_median_to_top": wmean(g["median_to_top"], w),
        })
    ease = pd.DataFrame(rows)
    if not ease.empty:
        def norm(s, invert=False):
            lo, hi = s.min(), s.max()
            if hi == lo:
                return pd.Series([0.5] * len(s), index=s.index)
            n = (s - lo) / (hi - lo)
            return 1 - n if invert else n
        ease["score_cv"] = norm(ease["avg_cv"], invert=True)
        ease["score_mtt"] = norm(ease["avg_median_to_top"])
        ease["ease_score"] = (ease["score_cv"] + ease["score_mtt"]) / 2

    # --- PI uplift per (class, spec, hero_cluster) ---
    pi_rows = []
    sub = merged.dropna(subset=["pi_received"]).copy()
    sub["pi_received"] = sub["pi_received"].astype(bool)
    for (cls, spec, hc), g in sub.groupby(["class", "spec", "hero_cluster"]):
        got = g[g["pi_received"]]
        nope = g[~g["pi_received"]]
        if len(got) < MIN_PI_EACH or len(nope) < MIN_PI_EACH:
            continue
        med_got = got["dps"].median()
        med_nope = nope["dps"].median()
        pi_rows.append({
            "class": cls,
            "spec": spec,
            "hero_cluster": int(hc),
            "n_with_pi": len(got),
            "n_without_pi": len(nope),
            "median_with_pi": int(round(med_got)),
            "median_without_pi": int(round(med_nope)),
            "uplift_pct": round((med_got - med_nope) / med_nope * 100, 2),
        })
    pi_df = pd.DataFrame(pi_rows)

    # --- combine ---
    if not ease.empty:
        out = ease.merge(pi_df, on=["class", "spec", "hero_cluster"], how="left")
    else:
        out = pi_df
    out = out.sort_values(["class", "spec", "hero_cluster"]).reset_index(drop=True)

    display_cols = [c for c in [
        "class", "spec", "hero_cluster", "bosses", "total_n",
        "avg_cv", "avg_median_to_top", "ease_score",
        "n_with_pi", "n_without_pi", "median_with_pi", "median_without_pi",
        "uplift_pct",
    ] if c in out.columns]
    show = out[display_cols].copy()
    for c in ("avg_cv", "avg_median_to_top", "ease_score"):
        if c in show.columns:
            show[c] = show[c].round(3)

    print("\n=== Per (class, spec, hero_cluster) ===")
    print(show.to_string(index=False))

    out_path = DATA / "hero_analysis.csv"
    out.to_csv(out_path, index=False)
    print(f"\nSaved -> {out_path}")

    # Bonus: flag specs where hero_cluster choice changes ease or PI meaningfully
    print("\n=== Biggest within-spec gaps by hero_cluster ===")
    if "ease_score" in out.columns:
        spec_gaps = (
            out.groupby(["class", "spec"])
            .agg(n_clusters=("hero_cluster", "nunique"),
                 ease_gap=("ease_score", lambda s: s.max() - s.min()),
                 uplift_gap=("uplift_pct", lambda s: (s.max() - s.min()) if s.notna().sum() >= 2 else float("nan")))
            .reset_index()
        )
        spec_gaps = spec_gaps[spec_gaps["n_clusters"] >= 2].sort_values("ease_gap", ascending=False)
        print(spec_gaps.to_string(index=False))


if __name__ == "__main__":
    main()
