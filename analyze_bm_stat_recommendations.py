"""BM Pack Leader boss-by-boss stat recommendation generator.

Reads current Mythic top100 ranking snapshots plus player_fight stat cache, then
writes data/bm_stat_recommendations.json for the stats tab.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

from wcl_v2_data import V2Data


DATA_DIR = Path("data")
RANKINGS_CSV = DATA_DIR / "rankings_zone46_mythic_dps_top100.csv"
OUT_JSON = DATA_DIR / "bm_stat_recommendations.json"
SPEC_KEY = "Hunter|Beast Mastery"
DR_MARKER = 466930


STAT_FIELDS = {
    "crit": "Crit",
    "haste": "Haste",
    "mastery": "Mastery",
    "vers": "Versatility",
}
STAT_KR = {
    "crit": "치명",
    "haste": "가속",
    "mastery": "특화",
    "vers": "유연",
}


def pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3 or len(xs) != len(ys):
        return 0.0
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return cov / (sx * sy) if sx and sy else 0.0


def dps_residuals(rows: list[dict]) -> list[float]:
    """Remove the linear effect of ilvl and fight duration from raw DPS."""
    if len(rows) < 5:
        mean_dps = statistics.mean(r["dps"] for r in rows)
        return [r["dps"] - mean_dps for r in rows]
    y = np.array([r["dps"] for r in rows], dtype=float)
    x = np.array([[1.0, r["ilvl"], r["duration_s"]] for r in rows], dtype=float)
    try:
        beta, *_ = np.linalg.lstsq(x, y, rcond=None)
        pred = x @ beta
        return [float(v) for v in (y - pred)]
    except Exception:
        mean_dps = float(np.mean(y))
        return [float(v - mean_dps) for v in y]


def avg(rows: list[dict], key: str) -> int:
    return round(statistics.mean(r[key] for r in rows))


def stat_ratio(num: int, den: int) -> float:
    return round((num / den * 100), 1) if den else 0.0


def recommend(mean: dict[str, int], adj: dict[str, float]) -> tuple[str, str, str, str]:
    cm = stat_ratio(mean["crit"], mean["mastery"])
    crit = adj.get("crit", 0.0)
    haste = adj.get("haste", 0.0)
    mastery = adj.get("mastery", 0.0)

    if cm >= 92 and crit >= mastery - 0.08:
        plume = "치명 꽁지깃"
    elif cm <= 78 or mastery >= crit + 0.08:
        plume = "특화 꽁지깃"
    else:
        plume = "보유템 우선"

    if cm >= 92:
        shape = "특화+치명"
    elif haste >= crit + 0.07:
        shape = "특화+가속"
    elif crit >= haste + 0.07:
        shape = "특화+치명"
    else:
        shape = "특화 중심, 치/가 균형"

    if cm >= 92:
        profile = "광/쫄 비중 높음"
    elif cm <= 78:
        profile = "단일·펫딜 비중 높음"
    else:
        profile = "혼합형"

    confidence = "높음" if abs(crit - haste) >= 0.12 or abs(crit - mastery) >= 0.12 else "보통"
    return shape, plume, profile, confidence


def load_rows(topn: int) -> dict[str, list[dict]]:
    with RANKINGS_CSV.open(encoding="utf-8", newline="") as f:
        rows = [
            r for r in csv.DictReader(f)
            if r.get("class") == "Hunter"
            and r.get("spec") == "Beast Mastery"
            and (r.get("dps") or "").strip()
        ]
    rows.sort(key=lambda r: (r["encounter_id"], -float(r["dps"])))
    by_boss: dict[str, list[dict]] = {}
    for r in rows:
        bucket = by_boss.setdefault(r["encounter_id"], [])
        if len(bucket) < topn:
            bucket.append(r)
    return by_boss


def collect_boss_samples(raw_rows: list[dict], v2: V2Data) -> tuple[list[dict], Counter]:
    samples: list[dict] = []
    heroes: Counter = Counter()
    for r in raw_rows:
        try:
            pf = v2.player_fight(r["report_id"], int(r["fight_id"]), r["character"])
        except Exception:
            continue
        if not isinstance(pf, dict):
            continue
        stats = pf.get("stats") or {}
        if not stats:
            continue
        talents = set(pf.get("talents") or [])
        hero = "DarkRanger" if DR_MARKER in talents else "PackLeader"
        heroes[hero] += 1
        if hero != "PackLeader":
            continue
        row = {
            "rank": int(r.get("rank") or 0),
            "dps": float(r["dps"]),
            "ilvl": float(r.get("item_level") or stats.get("Item Level") or 0),
            "duration_s": float(r.get("duration_ms") or 0) / 1000.0,
        }
        for key, stat_name in STAT_FIELDS.items():
            row[key] = int(stats.get(stat_name) or 0)
        samples.append(row)
    return samples, heroes


def build_recommendation(samples: list[dict], heroes: Counter) -> dict | None:
    if len(samples) < 5:
        return None
    residual = dps_residuals(samples)
    mean = {k: avg(samples, k) for k in STAT_FIELDS}
    raw_corr = {k: round(pearson([r[k] for r in samples], [r["dps"] for r in samples]), 3) for k in STAT_FIELDS}
    adj_corr = {k: round(pearson([r[k] for r in samples], residual), 3) for k in STAT_FIELDS}
    shape, plume, profile, confidence = recommend(mean, adj_corr)
    cm_ratio = stat_ratio(mean["crit"], mean["mastery"])
    hc_ratio = stat_ratio(mean["haste"], mean["crit"])
    return {
        "sample_n": len(samples),
        "hero_counts": dict(heroes),
        "mean": mean,
        "crit_mastery_pct": cm_ratio,
        "haste_crit_pct": hc_ratio,
        "raw_corr": raw_corr,
        "adjusted_corr": adj_corr,
        "adjustment": "DPS에서 ilvl과 전투시간의 선형 효과를 제거한 잔차 기준",
        "shape": shape,
        "plume": plume,
        "profile": profile,
        "confidence": confidence,
        "basis": (
            f"상위 {len(samples)}개 Pack Leader 표본 평균: "
            f"특화 {mean['mastery']}, 치명 {mean['crit']}, 가속 {mean['haste']} "
            f"(치/특 {cm_ratio}%). 보정 후 상관: "
            f"치명 {adj_corr['crit']:+.2f}, 가속 {adj_corr['haste']:+.2f}, 특화 {adj_corr['mastery']:+.2f}."
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topn", type=int, default=40)
    args = ap.parse_args()

    v2 = V2Data(data_dir=DATA_DIR)
    out = {
        "_meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source": str(RANKINGS_CSV),
            "topn": args.topn,
            "spec": SPEC_KEY,
        },
        SPEC_KEY: {},
    }
    by_boss = load_rows(args.topn)
    for boss_id, raw_rows in sorted(by_boss.items(), key=lambda x: int(x[0])):
        samples, heroes = collect_boss_samples(raw_rows, v2)
        rec = build_recommendation(samples, heroes)
        if rec:
            out[SPEC_KEY][boss_id] = rec
            print(
                boss_id,
                rec["shape"],
                rec["plume"],
                f"n={rec['sample_n']}",
                f"c/m={rec['crit_mastery_pct']}%",
                rec["adjusted_corr"],
            )
        else:
            print(boss_id, "skip", len(samples))

    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT_JSON)


if __name__ == "__main__":
    main()
