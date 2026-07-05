"""고통 흑마법사 보스별 장신구 추천 분석.

냉법 버전(analyze_frost_trinket_recommendations.py)과 같은 방식이되,
랭킹을 API 로 다시 받지 않고 오늘자 rankings_zone46_mythic_dps_top100.csv 로
필터한다 — pf 캐시와 명단이 정확히 맞아떨어지게(캐시-명단 정합).

장신구 ID 는 하드코딩하지 않는다 — 고통 흑마 상위권 장비(v2 player_fight
캐시의 gear 슬롯 12/13)에 실제로 등장한 것만 집계.
이름은 data/item_db.json 의 한글명 → 착용자 gear 의 영문명 → "item {id}" 순.
"""
from __future__ import annotations

import argparse
import csv
import json
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


DATA = Path(__file__).parent / "data"
RANKINGS_CSV = DATA / "rankings_zone46_mythic_dps_top100.csv"
OUT_JSON = DATA / "aff_trinket_recommendations.json"
TALENT_TREES = DATA / "talent_trees.json"
SPEC_KEY = "Warlock|Affliction"
CLASS_NAME = "Warlock"
SPEC_NAME = "Affliction"
TREE_KEY = "Warlock/Affliction"
ZONE_ID = 46

BOSS_KR = {
    3176: "전제군주 아베르지안",
    3177: "보라시우스",
    3178: "바엘고어와 에조라크",
    3179: "몰락왕 살라다르",
    3180: "빛눈먼 선봉대",
    3181: "우주의 왕관",
    3182: "벨로렌",
    3183: "한밤의 도래",
    3306: "카이메루스",
}


def pct(num: int, den: int) -> int:
    return round(num / den * 100) if den else 0


def mean(values: list[float]) -> float | None:
    return round(float(statistics.mean(values)), 1) if values else None


def median(values: list[float]) -> float | None:
    return round(float(statistics.median(values)), 1) if values else None


def residual_by_ilvl_and_duration(rows: list[dict]) -> dict[int, float]:
    if len(rows) < 6:
        avg = statistics.mean(r["dps"] for r in rows)
        return {id(r): r["dps"] - avg for r in rows}
    y = np.array([r["dps"] for r in rows], dtype=float)
    x = np.array([[1.0, r["ilvl"], r["duration_s"]] for r in rows], dtype=float)
    try:
        beta, *_ = np.linalg.lstsq(x, y, rcond=None)
        pred = x @ beta
        return {id(r): float(y[i] - pred[i]) for i, r in enumerate(rows)}
    except Exception:
        avg = float(np.mean(y))
        return {id(r): r["dps"] - avg for r in rows}


def load_item_names() -> dict[int, str]:
    """item_db.json 의 한글명 (있는 것만)."""
    try:
        db = json.loads((DATA / "item_db.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[int, str] = {}
    for k, v in db.items():
        if isinstance(v, dict) and v.get("name_ko"):
            try:
                out[int(k)] = str(v["name_ko"])
            except (TypeError, ValueError):
                continue
    return out


def load_hero_nodes() -> dict[str, set[int]]:
    """talent_trees.json 의 Warlock/Affliction 영웅트리 {이름: 노드셋}."""
    try:
        tt = json.loads(TALENT_TREES.read_text(encoding="utf-8"))
    except Exception:
        return {}
    hero = (tt.get(TREE_KEY) or {}).get("hero") or {}
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


def trinket_entries(pfight: dict) -> list[tuple[int, str]]:
    """gear 슬롯 12/13 의 (아이템 ID, 영문명)."""
    out = []
    for g in pfight.get("gear") or []:
        if isinstance(g, dict) and g.get("slot") in (12, 13) and isinstance(g.get("id"), int):
            out.append((g["id"], str(g.get("name") or "")))
    return out


def group_stats(rows: list[dict], pred) -> dict:
    yes = [r for r in rows if pred(r)]
    no = [r for r in rows if not pred(r)]
    return {
        "n": len(yes),
        "pct": pct(len(yes), len(rows)),
        "avg_rank": mean([r["rank"] for r in yes]),
        "avg_dps": mean([r["dps"] for r in yes]),
        "avg_adjusted_dps": mean([r["adjusted_dps"] for r in yes]) if len(yes) >= 2 else None,
        "others_adjusted_dps": mean([r["adjusted_dps"] for r in no]) if len(no) >= 2 else None,
    }


def recommendation(summary: dict) -> dict:
    combos = summary["top_combos"]
    groups = summary["groups"]
    if not combos:
        return {
            "pick": "표본 부족",
            "risk_profile": "판단 보류",
            "reason": "장신구를 확인할 수 있는 상위권 표본이 부족합니다. 캐시 백필 후 다시 돌리세요.",
            "top_adjusted_delta": None,
        }
    best = combos[0]
    second = combos[1] if len(combos) > 1 else None

    # 채택 1위 장신구의 보정 딜 차이 (표본이 작아 참고치)
    top_group = max(groups.values(), key=lambda g: g["n"]) if groups else None
    delta = None
    if (
        top_group
        and top_group.get("avg_adjusted_dps") is not None
        and top_group.get("others_adjusted_dps") is not None
    ):
        delta = round(top_group["avg_adjusted_dps"] - top_group["others_adjusted_dps"], 1)

    if best["pct"] >= 60:
        pick = best["combo"]
        risk = "대세 세팅"
        reason = (
            f"상위권 {best['pct']}%가 같은 조합을 씁니다. "
            "특별한 이유가 없으면 같이 가는 게 99 확률에 유리합니다."
        )
    elif best["pct"] >= 40:
        pick = best["combo"]
        risk = "우세 세팅"
        reason = f"상위권에서 제일 많이 쓰는 조합({best['pct']}%)입니다."
        if second:
            reason += f" 차선은 {second['combo']}({second['pct']}%)입니다."
    else:
        pick = "보유 고템렙 우선"
        risk = "혼합"
        reason = (
            "상위권 세팅이 갈립니다. 킬마다 딜이 들쭉날쭉한 표본이라 작은 차이는 "
            "무시하고, 보유한 장신구 중 템렙 높은 쪽을 먼저 쓰세요."
        )
        if second:
            reason += f" 많이 보이는 조합은 {best['combo']}({best['pct']}%), {second['combo']}({second['pct']}%)입니다."
    return {"pick": pick, "risk_profile": risk, "reason": reason, "top_adjusted_delta": delta}


def load_rankings_by_boss(topn: int) -> dict[int, list[dict]]:
    """오늘자 rankings CSV 에서 고통 흑마 행만 보스별로 (캐시-명단 정합)."""
    with RANKINGS_CSV.open(encoding="utf-8", newline="") as f:
        rows = [
            r for r in csv.DictReader(f)
            if r.get("class") == CLASS_NAME
            and r.get("spec") == SPEC_NAME
            and (r.get("dps") or "").strip()
        ]
    rows.sort(key=lambda r: (int(r["encounter_id"]), -float(r["dps"])))
    by_boss: dict[int, list[dict]] = {}
    for r in rows:
        bucket = by_boss.setdefault(int(r["encounter_id"]), [])
        if len(bucket) < topn:
            bucket.append(r)
    return by_boss


def analyze_boss(
    v2: V2Data,
    encounter_id: int,
    encounter_name: str,
    rankings: list[dict],
    top_band: int,
    max_fetch_misses: int,
    item_names: dict[int, str],
    hero_nodes: dict[str, set[int]],
) -> dict:
    samples = []
    hero_counts: Counter = Counter()
    gear_names: dict[int, str] = {}
    failures = 0
    cache_hits = 0
    live_fetches = 0
    skipped_uncached = 0
    for rank_i, row in enumerate(rankings, 1):
        rid = row.get("report_id")
        fid = row.get("fight_id")
        char = row.get("character")
        if not rid or not fid or not char:
            continue
        rank = int(row.get("rank") or rank_i)
        key = f"{rid}:{int(fid)}:{char}"
        try:
            if key in v2.pfight:
                cache_hits += 1
                pfight = v2.pfight.get(key)
            elif live_fetches < max_fetch_misses:
                live_fetches += 1
                print(f"  pf live {live_fetches}/{max_fetch_misses}: rank {rank} {char}", flush=True)
                pfight = v2.player_fight(rid, int(fid), char)
            else:
                skipped_uncached += 1
                continue
        except Exception:
            failures += 1
            continue
        if not isinstance(pfight, dict):
            failures += 1
            continue
        hero_counts[classify_hero(pfight.get("nodes"), hero_nodes)] += 1
        entries = trinket_entries(pfight)
        for iid, name in entries:
            if name and iid not in gear_names:
                gear_names[iid] = name
        stats = pfight.get("stats") or {}
        samples.append({
            "rank": rank,
            "char": char,
            "rid": rid,
            "fid": int(fid),
            "dps": float(row.get("dps") or 0),
            "ilvl": float(row.get("item_level") or stats.get("Item Level") or 0),
            "duration_s": float(row.get("duration_ms") or 0) / 1000.0,
            "trinkets": [iid for iid, _ in entries],
            "crit": int(stats.get("Crit") or 0),
            "haste": int(stats.get("Haste") or 0),
            "mastery": int(stats.get("Mastery") or 0),
            "vers": int(stats.get("Versatility") or 0),
        })
    samples.sort(key=lambda r: r["rank"])
    residuals = residual_by_ilvl_and_duration(samples) if samples else {}
    for row in samples:
        row["adjusted_dps"] = residuals.get(id(row), 0.0)
    top = samples[:min(top_band, len(samples))]

    def label_item(iid: int) -> str:
        return item_names.get(iid) or gear_names.get(iid) or f"item {iid}"

    # 장신구 풀 — 하드코딩 없이 표본에 실제 등장한 ID 전부
    wear_counts = Counter(iid for r in samples for iid in r["trinkets"])
    trinket_pool = [
        {"id": iid, "label": label_item(iid), "n": n}
        for iid, n in wear_counts.most_common()
    ]

    top_items: Counter = Counter()
    top_combos: Counter = Counter()
    for row in top:
        labels = [label_item(iid) for iid in row["trinkets"]]
        for label in labels:
            top_items[label] += 1
        top_combos[tuple(sorted(labels))] += 1
    top_item_pct = {label: pct(count, len(top)) for label, count in top_items.items()}

    # 착용자 3명 이상인 장신구만 그룹 비교 (그 밑은 노이즈)
    groups = {}
    for iid, n_wear in wear_counts.most_common():
        if n_wear < 3:
            continue
        groups[str(iid)] = {
            "label": label_item(iid),
            **group_stats(samples, lambda r, iid=iid: iid in r["trinkets"]),
        }

    summary = {
        "encounter_id": str(encounter_id),
        "boss": BOSS_KR.get(encounter_id, encounter_name),
        "encounter_name": encounter_name,
        "rankings_n": len(rankings),
        "sample_n": len(samples),
        "hero_counts": dict(hero_counts),
        "failures": failures,
        "cache_hits": cache_hits,
        "live_fetches": live_fetches,
        "skipped_uncached": skipped_uncached,
        "top_n": len(top),
        "top_kill_s": median([r["duration_s"] for r in top]),
        "top_ilvl": mean([r["ilvl"] for r in top]),
        "top_stats": {
            "crit": mean([r["crit"] for r in top]),
            "haste": mean([r["haste"] for r in top]),
            "mastery": mean([r["mastery"] for r in top]),
            "vers": mean([r["vers"] for r in top]),
        },
        "trinket_pool": trinket_pool,
        "top_items": top_items.most_common(10),
        "top_item_pct": top_item_pct,
        "top_combos": [
            {"combo": " + ".join(combo), "n": count, "pct": pct(count, len(top))}
            for combo, count in top_combos.most_common(8)
        ],
        "groups": groups,
    }
    summary["recommendation"] = recommendation(summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topn", type=int, default=100)
    parser.add_argument("--top-band", type=int, default=25)
    parser.add_argument("--max-fetch-misses", type=int, default=12)
    parser.add_argument("--flush-cache", action="store_true")
    args = parser.parse_args()

    v2 = V2Data(data_dir=DATA)
    item_names = load_item_names()
    hero_nodes = load_hero_nodes()
    by_boss = load_rankings_by_boss(args.topn)

    print(f"source={RANKINGS_CSV.name} topn={args.topn} bosses={len(by_boss)}")
    output = {
        "_meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "zone_id": ZONE_ID,
            "zone": "VS / DR / MQD",
            "difficulty": "mythic",
            "source": str(RANKINGS_CSV),
            "topn": args.topn,
            "top_band": args.top_band,
            "notes": [
                "DPS 보정값은 템렙과 전투시간 영향을 뺀 값 기준입니다.",
                "명단은 오늘자 랭킹 CSV 기준입니다 (pf 캐시와 정합).",
                "장신구 목록은 하드코딩 없이 고통 흑마 상위권 장비에 실제로 나온 것만 집계합니다.",
                "추천은 평균 딜보다 상위권 채택률을 더 크게 봅니다. 킬마다 딜이 들쭉날쭉한 표본이라 작은 차이는 무시하세요.",
            ],
        },
        SPEC_KEY: {},
    }

    order = sorted(by_boss, key=lambda e: e if e != 3306 else 3184)
    for eid in order:
        rankings = by_boss[eid]
        name_en = rankings[0].get("encounter_name") or str(eid)
        print(f"{eid} {BOSS_KR.get(eid, name_en)}: rankings={len(rankings)}")
        summary = analyze_boss(
            v2, eid, name_en, rankings, args.top_band, args.max_fetch_misses,
            item_names, hero_nodes,
        )
        output[SPEC_KEY][str(eid)] = summary
        rec = summary["recommendation"]
        print(
            f"{eid} {summary['boss']}: {rec['pick']} | top items={summary['top_items'][:4]}"
        )

    OUT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_JSON}")
    if args.flush_cache:
        v2.flush()

    try:
        from update_log import record
        record(
            action="analyze_aff_trinket_recommendations",
            params={"topn": args.topn, "top_band": args.top_band},
            result={"bosses": len(output[SPEC_KEY])},
            files=[str(OUT_JSON).replace("\\", "/")],
        )
    except Exception as exc:
        print(f"[update_log] skip: {exc}")


if __name__ == "__main__":
    main()
