"""분노 전사 보스별 스탯 우선순위 생성기.

신화 top100 랭킹 스냅샷 + player_fight 스탯 캐시를 읽어
data/fury_stat_recommendations.json 을 만든다 (스탯 탭 소비용).

방법은 Frost 버전(analyze_frost_stat_recommendations.py)과 동일:
DPS 에서 템렙·전투시간 영향을 뺀 값과 스탯 수치의 상관을 보고,
보스별로 "상위권이 실제로 챙기는 스탯 순서" 를 뽑는다.
Fury 전용 개념은 없고, 1~20등 개별 스탯 + 21~100등 평균과
스탯 비중, 우선순위 추천만 낸다. 영웅특성(학살자/산왕/거신) 채택 인원도 같이 기록한다.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from wcl_v2_data import V2Data


DATA_DIR = Path(__file__).parent / "data"
RANKINGS_CSV = DATA_DIR / "rankings_zone46_mythic_dps_top100.csv"
TALENT_TREES = DATA_DIR / "talent_trees.json"
OUT_JSON = DATA_DIR / "fury_stat_recommendations.json"
SPEC_KEY = "Warrior|Fury"
CLASS_NAME = "Warrior"
SPEC_NAME = "Fury"
TOP_BAND = 20   # 1~20등 개별 표시 + 우선순위 판단 기준


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
    """DPS 에서 템렙과 전투시간의 선형 영향을 뺀 값."""
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


def load_hero_nodes() -> dict[str, set[int]]:
    """talent_trees.json 에 Warrior/Fury 영웅트리가 있으면 {이름: 노드셋} 반환.

    현재 talent_trees.json 에 없으면 {} — 영웅 구분 없이 전체 집계.
    """
    try:
        tt = json.loads(TALENT_TREES.read_text(encoding="utf-8"))
    except Exception:
        return {}
    hero = (tt.get("Warrior/Fury") or {}).get("hero") or {}
    out: dict[str, set[int]] = {}
    for name, v in hero.items():
        if isinstance(v, dict):
            out[name] = {n["id"] for n in (v.get("nodes") or []) if isinstance(n, dict) and "id" in n}
    return out


def classify_hero(nodes: list[int] | None, hero_nodes: dict[str, set[int]]) -> str:
    """노드 교집합(>=3)으로 영웅특성 판별. 트리 정보 없으면 'unknown'."""
    ns = set(nodes or [])
    best, best_n = "unknown", 0
    for name, ids in hero_nodes.items():
        k = len(ns & ids)
        if k >= 3 and k > best_n:
            best, best_n = name, k
    return best


def load_rows(topn: int) -> dict[str, list[dict]]:
    with RANKINGS_CSV.open(encoding="utf-8", newline="") as f:
        rows = [
            r for r in csv.DictReader(f)
            if r.get("class") == CLASS_NAME
            and r.get("spec") == SPEC_NAME
            and (r.get("dps") or "").strip()
        ]
    rows.sort(key=lambda r: (r["encounter_id"], -float(r["dps"])))
    by_boss: dict[str, list[dict]] = {}
    for r in rows:
        bucket = by_boss.setdefault(r["encounter_id"], [])
        if len(bucket) < topn:
            bucket.append(r)
    return by_boss


def collect_boss_samples(
    raw_rows: list[dict], v2: V2Data, hero_nodes: dict[str, set[int]]
) -> tuple[list[dict], Counter]:
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
        heroes[classify_hero(pf.get("nodes"), hero_nodes)] += 1
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
    samples = sorted(samples, key=lambda r: r["rank"])
    top = [r for r in samples if r["rank"] and r["rank"] <= TOP_BAND] or samples[:TOP_BAND]
    top_ids = {id(r) for r in top}
    rest = [r for r in samples if id(r) not in top_ids]
    residual = dps_residuals(samples)
    mean_top = {k: avg(top, k) for k in STAT_FIELDS}
    total = sum(mean_top.values()) or 1
    stat_pct = {k: round(v / total * 100, 1) for k, v in mean_top.items()}
    raw_corr = {k: round(pearson([r[k] for r in samples], [r["dps"] for r in samples]), 3) for k in STAT_FIELDS}
    adj_corr = {k: round(pearson([r[k] for r in samples], residual), 3) for k in STAT_FIELDS}

    # 우선순위: 상위 밴드 평균 수치가 큰 순서. 상관은 참고치로만 병기.
    order = sorted(STAT_FIELDS, key=lambda k: -mean_top[k])
    priority = " > ".join(STAT_KR[k] for k in order)
    gap = stat_pct[order[0]] - stat_pct[order[1]]
    confidence = "높음" if gap >= 5 else "보통"
    corr_txt = ", ".join(f"{STAT_KR[k]} {adj_corr[k]:+.2f}" for k in order)
    basis = (
        f"상위 {len(top)}명 평균: "
        + ", ".join(f"{STAT_KR[k]} {mean_top[k]}" for k in order)
        + ". 수치가 큰 순서대로 우선순위를 정했습니다. "
        + f"템렙·전투시간 영향을 뺀 뒤 딜과 같이 움직인 정도: {corr_txt}."
    )
    return {
        "sample_n": len(samples),
        "hero_counts": dict(heroes),
        "mean": mean_top,
        "stat_pct": stat_pct,
        "crit_mastery_pct": stat_ratio(mean_top["crit"], mean_top["mastery"]),
        "haste_crit_pct": stat_ratio(mean_top["haste"], mean_top["crit"]),
        "top20": [
            {"rank": r["rank"], "dps": round(r["dps"], 1), "ilvl": r["ilvl"],
             **{k: r[k] for k in STAT_FIELDS}}
            for r in top
        ],
        "rest_avg": (
            {"n": len(rest), **{k: avg(rest, k) for k in STAT_FIELDS}}
            if len(rest) >= 2 else None
        ),
        "raw_corr": raw_corr,
        "adjusted_corr": adj_corr,
        "adjustment": "DPS에서 템렙과 전투시간 영향을 뺀 값 기준",
        "priority": priority,
        "confidence": confidence,
        "basis": basis,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topn", type=int, default=100)
    args = ap.parse_args()

    v2 = V2Data(data_dir=DATA_DIR)
    hero_nodes = load_hero_nodes()
    out = {
        "_meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source": str(RANKINGS_CSV),
            "topn": args.topn,
            "top_band": TOP_BAND,
            "spec": SPEC_KEY,
        },
        SPEC_KEY: {},
    }
    by_boss = load_rows(args.topn)
    for boss_id, raw_rows in sorted(by_boss.items(), key=lambda x: int(x[0])):
        samples, heroes = collect_boss_samples(raw_rows, v2, hero_nodes)
        rec = build_recommendation(samples, heroes)
        if rec:
            out[SPEC_KEY][boss_id] = rec
            print(
                boss_id,
                rec["priority"],
                f"n={rec['sample_n']}",
                rec["adjusted_corr"],
                rec["hero_counts"],
            )
        else:
            print(boss_id, "skip", len(samples))

    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT_JSON)

    try:
        from update_log import record
        record(
            action="analyze_fury_stat_recommendations",
            params={"topn": args.topn, "top_band": TOP_BAND},
            result={"bosses": len(out[SPEC_KEY])},
            files=[str(OUT_JSON).replace("\\", "/")],
        )
    except Exception as exc:
        print(f"[update_log] skip: {exc}")


if __name__ == "__main__":
    main()
