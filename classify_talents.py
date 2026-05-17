"""Identify hero talent clusters per (class, spec) from raw talent picks.

Every Midnight spec has exactly 2 hero talent trees. If we k-means on the
binary pick matrix of each spec (rows = players, cols = talent IDs), the
two dominant hero trees should fall out as 2 clean clusters because their
nodes are mutually exclusive.

We also surface the signature talent IDs per cluster (high pick rate in one
cluster, low in the other) so the user can name each cluster by pasting
those IDs into Wowhead / Icy-Veins.

Output:
  data/hero_cluster_map.csv      rows: class, spec, cluster_id, talent_id, pick_rate_in_cluster, pick_rate_other
  data/rankings_with_talents.csv rankings enriched with hero_cluster (0/1/-1)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path(__file__).parent / "data"
CSV_IN = DATA / "rankings_zone46_mythic_dps_top100.csv"
CACHE_TALENTS = DATA / "cache_talents.json"

MIN_PLAYERS_PER_SPEC = 20        # need enough samples per spec to cluster
DIFF_LOWER, DIFF_UPPER = 0.15, 0.85  # "differentiating" pick rate window


def load_talents() -> dict:
    return json.loads(CACHE_TALENTS.read_text(encoding="utf-8"))


def main() -> None:
    df = pd.read_csv(CSV_IN)
    df["report_id"] = df["report_id"].astype(str)
    df["fight_id"] = df["fight_id"].astype(int)

    talents_by_fight = load_talents()

    # Attach talent set to each row (dedup per character since same player
    # can appear on multiple bosses -- but their talents may differ per log,
    # so we key on report+fight+char).
    def talents_for(row):
        entry = talents_by_fight.get(f"{row['report_id']}:{row['fight_id']}")
        if not entry:
            return None
        return entry.get(row["character"])

    df["talent_ids"] = df.apply(talents_for, axis=1)
    have = df["talent_ids"].notna()
    print(f"Rows with talents: {have.sum()}/{len(df)} ({100*have.mean():.1f}%)")

    cluster_map_rows = []
    player_cluster_rows = []  # (index_in_df, cluster_id)

    for (cls, spec), g in df[have].groupby(["class", "spec"]):
        n = len(g)
        if n < MIN_PLAYERS_PER_SPEC:
            continue

        # Build binary pick matrix over union of talent IDs seen in this spec
        all_ids = sorted({tid for lst in g["talent_ids"] for tid in lst})
        X = np.zeros((n, len(all_ids)), dtype=np.int8)
        id_to_col = {tid: i for i, tid in enumerate(all_ids)}
        for row_i, (_, r) in enumerate(g.iterrows()):
            for tid in r["talent_ids"]:
                X[row_i, id_to_col[tid]] = 1

        # Focus clustering on differentiating talents (mid pick rate).
        rate = X.mean(axis=0)
        diff_cols = np.where((rate >= DIFF_LOWER) & (rate <= DIFF_UPPER))[0]
        if len(diff_cols) < 3:
            # degenerate: almost everyone picks the same talents
            # (maybe only one hero tree viable). mark all as cluster 0.
            for orig_idx in g.index:
                player_cluster_rows.append((orig_idx, 0))
            continue

        Xd = X[:, diff_cols]
        km = KMeans(n_clusters=2, random_state=0, n_init=10).fit(Xd)
        labels = km.labels_

        for orig_idx, lab in zip(g.index, labels):
            player_cluster_rows.append((orig_idx, int(lab)))

        # Signature talents per cluster
        for cid in (0, 1):
            mask = labels == cid
            if not mask.any():
                continue
            in_rate = X[mask].mean(axis=0)
            out_rate = X[~mask].mean(axis=0) if (~mask).any() else np.zeros(X.shape[1])
            gap = in_rate - out_rate
            # top-10 most distinctive for this cluster
            top = np.argsort(-gap)[:10]
            for col in top:
                if gap[col] < 0.30:
                    continue  # not distinctive enough
                cluster_map_rows.append({
                    "class": cls,
                    "spec": spec,
                    "cluster": cid,
                    "n_players": int(mask.sum()),
                    "talent_id": int(all_ids[col]),
                    "pick_rate_in_cluster": round(float(in_rate[col]), 3),
                    "pick_rate_other": round(float(out_rate[col]), 3),
                    "gap": round(float(gap[col]), 3),
                })

    # Assign cluster column back to df (-1 for rows we couldn't cluster)
    df["hero_cluster"] = -1
    for orig_idx, lab in player_cluster_rows:
        df.at[orig_idx, "hero_cluster"] = lab

    # Write outputs
    out_ranks = DATA / "rankings_with_talents.csv"
    df.drop(columns=["talent_ids"]).to_csv(out_ranks, index=False)
    print(f"Wrote {out_ranks}")

    cmap = pd.DataFrame(cluster_map_rows)
    cmap = cmap.sort_values(["class", "spec", "cluster", "gap"], ascending=[True, True, True, False])
    out_cmap = DATA / "hero_cluster_map.csv"
    cmap.to_csv(out_cmap, index=False)
    print(f"Wrote {out_cmap}")

    # Per-spec cluster breakdown
    print("\n=== Cluster sizes per spec ===")
    counts = (
        df[df["hero_cluster"] >= 0]
        .groupby(["class", "spec", "hero_cluster"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
    counts.columns.name = None
    if 0 in counts.columns and 1 in counts.columns:
        counts = counts.rename(columns={0: "cluster_0", 1: "cluster_1"})
        counts["total"] = counts["cluster_0"] + counts["cluster_1"]
        counts["split"] = (counts["cluster_0"] / counts["total"]).round(2)
    print(counts.to_string(index=False))


if __name__ == "__main__":
    main()
