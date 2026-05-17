"""Per-spec comparison: DPS with vs without Power Infusion.

Reads the PI-enriched rankings CSV and produces a side-by-side table:
  - Samples with PI / without PI
  - Median DPS with PI / without PI
  - Absolute and percent uplift from PI

Sorted by %uplift descending: top = most PI-dependent.
Bottom = least PI-dependent (performs consistently regardless of PI).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CSV = Path(__file__).parent / "data" / "rankings_zone46_mythic_dps_top100_pi.csv"
MIN_SAMPLES_EACH = 20     # need at least 20 logs in BOTH groups for a fair compare

df = pd.read_csv(CSV)
df = df.dropna(subset=["pi_received"]).copy()
df["pi_received"] = df["pi_received"].astype(bool)

rows = []
for (cls, spec), g in df.groupby(["class", "spec"]):
    got = g[g["pi_received"]]
    nope = g[~g["pi_received"]]
    if len(got) < MIN_SAMPLES_EACH or len(nope) < MIN_SAMPLES_EACH:
        continue
    med_got = got["dps"].median()
    med_nope = nope["dps"].median()
    uplift_abs = med_got - med_nope
    uplift_pct = (uplift_abs / med_nope) * 100
    rows.append({
        "class": cls,
        "spec": spec,
        "n_with_pi": len(got),
        "n_without_pi": len(nope),
        "median_with_pi": int(round(med_got)),
        "median_without_pi": int(round(med_nope)),
        "uplift_abs": int(round(uplift_abs)),
        "uplift_pct": round(uplift_pct, 2),
    })

summary = pd.DataFrame(rows)

# overall PI rate (independent of uplift filter)
overall_rate = (
    df.groupby(["class", "spec"])["pi_received"].mean().mul(100).round(1).reset_index()
    .rename(columns={"pi_received": "pi_rate_pct"})
)
summary = summary.merge(overall_rate, on=["class", "spec"], how="left")

summary_sorted = summary.sort_values("uplift_pct", ascending=False)

print("=" * 95)
print("PI 영향 큰 순 (TOP = 의존 큼, BOTTOM = PI 없어도 잘하는 스펙)")
print(f"필터: PI 받음 >= {MIN_SAMPLES_EACH}건 AND PI 없음 >= {MIN_SAMPLES_EACH}건")
print("=" * 95)
cols = ["class", "spec", "pi_rate_pct", "n_with_pi", "n_without_pi",
        "median_with_pi", "median_without_pi", "uplift_abs", "uplift_pct"]
print(summary_sorted[cols].to_string(index=False))

out = Path(__file__).parent / "data" / "pi_impact.csv"
summary_sorted.to_csv(out, index=False)
print(f"\nSaved -> {out}")

# specs with not enough balance (always PI'd or never PI'd)
excluded = (
    df.groupby(["class", "spec"])["pi_received"]
    .agg(["count", "sum"])
    .reset_index()
    .rename(columns={"count": "total", "sum": "with_pi"})
)
excluded["without_pi"] = excluded["total"] - excluded["with_pi"]
excluded = excluded[(excluded["with_pi"] < MIN_SAMPLES_EACH) | (excluded["without_pi"] < MIN_SAMPLES_EACH)]
if len(excluded):
    print(f"\nExcluded from compare (imbalanced samples):")
    print(excluded.to_string(index=False))
