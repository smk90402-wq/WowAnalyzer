"""Per-spec 'skill floor' ranking.

Proxies for "easy to pull high numbers without mastery":
  - CV (std/mean) of top-100 DPS per boss: lower = more consistent = easier
  - median/top ratio per boss: higher = median log is close to the peak = lower ceiling penalty
Combines both into an ease_score (higher = easier).
Weights each (boss, spec) by sample count so sparse data doesn't skew.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CSV = Path(__file__).parent / "data" / "rankings_zone46_mythic_dps_top100.csv"
MIN_N_PER_BOSS = 30          # require at least 30 logs of a spec on a boss
MIN_BOSSES = 3               # spec must appear on at least 3 bosses to rank

df = pd.read_csv(CSV)

# per-(boss, spec) distribution stats
stats = (
    df.groupby(["encounter_name", "class", "spec"])["dps"]
    .agg(
        n="count",
        mean="mean",
        std="std",
        median="median",
        top="max",
        p10=lambda s: s.quantile(0.10),
        p90=lambda s: s.quantile(0.90),
    )
    .reset_index()
)
stats["cv"] = stats["std"] / stats["mean"]
stats["median_to_top"] = stats["median"] / stats["top"]
stats["p90_to_p10"] = stats["p90"] / stats["p10"]

stats = stats[stats["n"] >= MIN_N_PER_BOSS].copy()


# weighted averages across bosses per spec
def weighted_mean(values, weights):
    return (values * weights).sum() / weights.sum()


rows = []
for (cls, spec), g in stats.groupby(["class", "spec"]):
    if len(g) < MIN_BOSSES:
        continue
    w = g["n"]
    rows.append({
        "class": cls,
        "spec": spec,
        "bosses": len(g),
        "total_n": int(w.sum()),
        "avg_cv": weighted_mean(g["cv"], w),
        "avg_median_to_top": weighted_mean(g["median_to_top"], w),
        "avg_p90_to_p10": weighted_mean(g["p90_to_p10"], w),
    })
summary = pd.DataFrame(rows)

# Ease score: low CV is good (invert), high median_to_top is good
# Normalize each to [0,1] then combine.
def norm(s, invert=False):
    lo, hi = s.min(), s.max()
    if hi == lo:
        return pd.Series([0.5] * len(s), index=s.index)
    n = (s - lo) / (hi - lo)
    return 1 - n if invert else n

summary["score_cv"] = norm(summary["avg_cv"], invert=True)
summary["score_mtt"] = norm(summary["avg_median_to_top"])
summary["ease_score"] = (summary["score_cv"] + summary["score_mtt"]) / 2
summary = summary.sort_values("ease_score", ascending=False)

print(f"Specs ranked by ease_score (higher = lower skill floor, more forgiving)\n"
      f"Filters: >= {MIN_N_PER_BOSS} logs/boss, >= {MIN_BOSSES} bosses covered\n")

display = summary[["class", "spec", "bosses", "total_n", "avg_cv",
                   "avg_median_to_top", "ease_score"]].copy()
display["avg_cv"] = (display["avg_cv"] * 100).round(2).astype(str) + "%"
display["avg_median_to_top"] = display["avg_median_to_top"].round(3)
display["ease_score"] = display["ease_score"].round(3)
print(display.to_string(index=False))

out = Path(__file__).parent / "data" / "difficulty_ranking.csv"
summary.to_csv(out, index=False)
print(f"\nSaved -> {out}")
