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

# ── 보스별 통제 uplift ──────────────────────────────────────────────────────
# 보스마다 DPS 레벨(128k~219k)이 다르고 PI율도 다름(쫄파이 보스서 PI↑).
# 보스 무시하고 with/without 비교하면 PI 받음 그룹이 고DPS 보스로 쏠려 가짜 uplift.
# → 보스별로 uplift 계산 후 평균 (Simpson's paradox 회피).
MIN_PER_BOSS = 8   # 한 보스 그룹에 최소 with/without 각 8
rows = []
for (cls, spec), g in df.groupby(["class", "spec"]):
    per_boss = []
    for bid, gb in g.groupby("encounter_id"):
        got_b = gb[gb["pi_received"]]; nope_b = gb[~gb["pi_received"]]
        if len(got_b) < MIN_PER_BOSS or len(nope_b) < MIN_PER_BOSS:
            continue
        mb = nope_b["dps"].median()
        if mb > 0:
            per_boss.append((got_b["dps"].median() - mb) / mb * 100)
    got = g[g["pi_received"]]; nope = g[~g["pi_received"]]
    if len(per_boss) < 3:   # 통제 가능한 보스 3개 미만이면 신뢰 불가 → 스킵
        continue
    uplift_pct = sum(per_boss) / len(per_boss)
    rows.append({
        "class": cls,
        "spec": spec,
        "n_with_pi": len(got),
        "n_without_pi": len(nope),
        "bosses_used": len(per_boss),
        "median_with_pi": int(round(got["dps"].median())),
        "median_without_pi": int(round(nope["dps"].median())),
        "uplift_pct": round(uplift_pct, 2),  # 보스별 평균 (통제됨)
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
        "bosses_used", "uplift_pct"]
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
