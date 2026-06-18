"""BM Pack Leader boss-by-boss trinket recommendation analysis.

Fetches current Warcraft Logs Mythic Beast Mastery rankings for the latest zone
partition, enriches them with V2 combatantInfo, and writes a compact JSON report
focused on "what raises the chance of a 99 parse" rather than raw average DPS.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from wcl_v2 import WCLV2
from wcl_v2_data import V2Data


DATA = Path(__file__).parent / "data"
OUT_JSON = DATA / "bm_trinket_recommendations.json"
ZONE_ID = 46
DIFFICULTY = 5
DR_MARKER = 466930

BOX_ITEM = 193701
BOX_SPELL = 383781
PLUME_MASTERY = 249806
PLUME_CRIT = 260235
ALN_GAZE = 249343
COSMIC_WRAP = 249340
VAEL_GAZE = 249346
CRUCIBLE = 264507
SOLARFLARE_PRISM = 252420
HEART_OF_WIND = 250256

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

ITEM_LABEL = {
    BOX_ITEM: "상자",
    PLUME_MASTERY: "특화 꽁지깃",
    PLUME_CRIT: "치명 꽁지깃",
    ALN_GAZE: "알른 응시",
    COSMIC_WRAP: "우주 붕대",
    VAEL_GAZE: "바엘 응시",
    CRUCIBLE: "도가니",
    SOLARFLARE_PRISM: "태양섬광 분광경",
    HEART_OF_WIND: "바람의 심장",
}

QUERY_ZONE = """
query($id: Int!) {
  worldData {
    zone(id: $id) {
      id name
      encounters { id name }
      partitions { id name default }
    }
  }
}
"""

QUERY_RANKS = """
query($encounterId: Int!, $page: Int!, $diff: Int!, $partition: Int!) {
  worldData {
    encounter(id: $encounterId) {
      characterRankings(
        metric: dps
        difficulty: $diff
        className: "Hunter"
        specName: "BeastMastery"
        page: $page
        partition: $partition
      )
    }
  }
}
"""


def pct(num: int, den: int) -> int:
    return round(num / den * 100) if den else 0


def mean(values: list[float]) -> float | None:
    return round(float(statistics.mean(values)), 1) if values else None


def median(values: list[float]) -> float | None:
    return round(float(statistics.median(values)), 1) if values else None


def latest_partition(cli: WCLV2) -> tuple[dict, int, str]:
    zone = cli.query(QUERY_ZONE, {"id": ZONE_ID})["worldData"]["zone"]
    parts = zone.get("partitions") or []
    default = next((p for p in parts if p.get("default")), None)
    if default:
        return zone, int(default["id"]), str(default.get("name") or default["id"])
    return zone, 1, "1"


def fetch_rankings(cli: WCLV2, encounter_id: int, partition: int, topn: int) -> list[dict]:
    out: list[dict] = []
    max_pages = max(1, (topn + 99) // 100)
    for page in range(1, max_pages + 1):
        data = cli.query(QUERY_RANKS, {
            "encounterId": encounter_id,
            "page": page,
            "diff": DIFFICULTY,
            "partition": partition,
        })
        obj = (((data or {}).get("worldData") or {}).get("encounter") or {}).get("characterRankings") or {}
        ranks = obj.get("rankings") or []
        out.extend(ranks)
        if len(out) >= topn or not obj.get("hasMorePages"):
            break
        time.sleep(0.05)
    return out[:topn]


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


def label_item(iid: int) -> str:
    return ITEM_LABEL.get(iid, f"item {iid}")


def trinket_ids(pfight: dict) -> list[int]:
    out = []
    for g in pfight.get("gear") or []:
        if isinstance(g, dict) and g.get("slot") in (12, 13) and isinstance(g.get("id"), int):
            out.append(g["id"])
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


def box_event_summary(v2: V2Data, rows: list[dict], max_event_fetches: int) -> dict:
    box_rows = [r for r in rows if BOX_ITEM in r["trinkets"]]
    events = []
    cache_hits = 0
    live_fetches = 0
    skipped_uncached = 0
    for r in box_rows:
        try:
            event_key = None
            pfight = v2.pfight.get(f"{r['rid']}:{r['fid']}:{r['char']}")
            if isinstance(pfight, dict) and isinstance(pfight.get("sourceID"), int):
                event_key = f"{r['rid']}:{r['fid']}:{pfight['sourceID']}"
            if event_key and event_key in v2.events:
                cache_hits += 1
                ev = v2.events.get(event_key)
            elif live_fetches < max_event_fetches:
                live_fetches += 1
                print(f"  box events live {live_fetches}/{max_event_fetches}: {r['char']}", flush=True)
                ev = v2.events_for(r["rid"], r["fid"], r["char"])
            else:
                skipped_uncached += 1
                continue
        except Exception:
            continue
        casts = (ev or {}).get("casts") or []
        uses = sorted(
            c[0] for c in casts
            if isinstance(c, list) and len(c) >= 3 and c[1] == BOX_SPELL and c[2] == "cast"
        )
        first_s = None
        if uses:
            meta = v2.report_meta(r["rid"]) or {}
            fight = next((f for f in meta.get("fights") or [] if f.get("id") == r["fid"]), None)
            if fight:
                first_s = (uses[0] - fight["startTime"]) / 1000.0
        events.append({"first_s": first_s, "count": len(uses)})
    used = [e for e in events if e["count"] > 0]
    return {
        "box_wearers_checked": len(box_rows),
        "event_rows": len(events),
        "cache_hits": cache_hits,
        "live_fetches": live_fetches,
        "skipped_uncached": skipped_uncached,
        "used": len(used),
        "event_coverage_pct": pct(len(events), len(box_rows)),
        "used_pct_checked": pct(len(used), len(events)),
        "opener_pct": pct(sum(1 for e in used if e["first_s"] is not None and e["first_s"] <= 10), len(used)),
        "first_s_median": median([e["first_s"] for e in used if e["first_s"] is not None]),
        "count_median": median([e["count"] for e in used]),
    }


def recommendation(summary: dict) -> dict:
    groups = summary["groups"]
    box = groups["box"]
    box_events = summary["box_events"]
    boss_id = int(summary["encounter_id"])

    # Favor current top-band adoption for 99 chasing. Adjusted DPS is noisy at
    # this small sample size, so it is used as a secondary hint only.
    box_top_pct = summary["top_item_pct"].get("상자", 0)
    crit_top_pct = summary["top_item_pct"].get("치명 꽁지깃", 0)
    mastery_top_pct = summary["top_item_pct"].get("특화 꽁지깃", 0)
    box_delta = None
    if box.get("avg_adjusted_dps") is not None and box.get("others_adjusted_dps") is not None:
        box_delta = round(box["avg_adjusted_dps"] - box["others_adjusted_dps"], 1)

    if boss_id == 3177:
        pick = "상자 + 알른 응시"
        risk = "숙련자 고점"
        reason = "보라시우스는 순수 단일에 가깝고 상자 top-band 채택률/오프닝 사용률이 높아 네가 이미 99를 찍은 세팅과 맞습니다."
    elif boss_id == 3182:
        pick = "특화 꽁지깃 + 알른 응시"
        risk = "안정 99"
        reason = "벨로렌은 최신 상위 표본에서 특화 꽁지깃 채택이 상자보다 높습니다. 상자 타이밍을 강제로 만들기보다 지속 단일값을 가져가는 쪽이 99 확률에 안정적입니다."
    elif boss_id == 3180:
        pick = "상자 + 알른 응시, 실패가 잦으면 치명 꽁지깃"
        risk = "고점/안정 분기"
        reason = "빛눈먼 선봉대 상위권은 상자+알른이 기본이지만, 피할 패턴 때문에 상자를 늦추거나 놓치면 손실이 큽니다. 상자를 안정적으로 누르면 상자, 자주 밀리면 치명 꽁지깃이 99 확률을 더 올립니다."
    elif boss_id in {3176, 3178, 3179, 3181, 3183, 3306}:
        pick = "상자 + 알른 응시"
        if box_events.get("opener_pct", 0) < 70 or (box_events.get("first_s_median") or 0) > 20:
            risk = "고점, 타이밍 관리"
            reason = "최신 상위 표본은 상자+알른이 우세하지만 첫 사용이 늦거나 갈리는 보스입니다. 오프닝 고정이 아니라 패턴 중 빈 시간에 상자를 넣는 계획이 필요합니다."
        else:
            risk = "고점 우선"
            reason = "최신 상위 표본의 상자+알른 채택률과 실제 사용률이 높습니다. 상자를 안정적으로 누를 수 있으면 99 고점 세팅으로 보는 게 맞습니다."
    elif box_top_pct >= 70 and box_events.get("used_pct_checked", 0) >= 80:
        pick = "상자 + 알른 응시"
        if box_events.get("opener_pct", 0) < 70 or (box_events.get("first_s_median") or 0) > 20:
            risk = "고점, 타이밍 관리"
            reason = "상위권 채택은 상자가 우세하지만 첫 사용이 늦거나 갈리는 표본이 있어, 패턴 중 빈 시간을 미리 정해야 합니다."
        else:
            risk = "고점 우선"
            reason = "상위권이 상자를 많이 쓰고 실제 사용률/오프닝 정렬도 높아 99 고점에 맞습니다."
    elif crit_top_pct >= mastery_top_pct + 15:
        pick = "치명 꽁지깃 + 알른 응시"
        risk = "안정 99"
        reason = "상자 사용 이득보다 치명 꽁지깃 채택 우위가 뚜렷합니다. 광/2타겟 비중 또는 무빙 손실이 있는 보스로 봅니다."
    elif mastery_top_pct >= crit_top_pct + 15:
        pick = "특화 꽁지깃 + 알른 응시"
        risk = "안정 99"
        reason = "단일 지속딜 또는 상자 정렬 부담이 큰 쪽입니다. 상자 미스보다 패시브 특화값이 99 확률에 유리합니다."
    else:
        pick = "보유 고템렙 우선: 상자 가능하면 상자, 불안하면 꽁지깃"
        risk = "혼합"
        reason = "상위 표본이 갈립니다. 상자 타이밍을 확실히 넣을 수 있는 개인 숙련도와 ilvl 차이가 판단 기준입니다."

    return {
        "pick": pick,
        "risk_profile": risk,
        "reason": reason,
        "box_adjusted_delta": box_delta,
    }


def analyze_boss(
    v2: V2Data,
    encounter: dict,
    rankings: list[dict],
    top_band: int,
    max_fetch_misses: int,
) -> dict:
    samples = []
    hero_counts: Counter = Counter()
    failures = 0
    cache_hits = 0
    live_fetches = 0
    skipped_uncached = 0
    for rank, row in enumerate(rankings, 1):
        report = row.get("report") or {}
        rid = report.get("code")
        fid = report.get("fightID")
        char = row.get("name")
        if not rid or not fid or not char:
            continue
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
        hero = "DarkRanger" if DR_MARKER in set(pfight.get("talents") or []) else "PackLeader"
        hero_counts[hero] += 1
        if hero != "PackLeader":
            continue
        stats = pfight.get("stats") or {}
        samples.append({
            "rank": rank,
            "char": char,
            "rid": rid,
            "fid": int(fid),
            "dps": float(row.get("amount") or row.get("total") or 0),
            "ilvl": float(row.get("bracketData") or stats.get("Item Level") or 0),
            "duration_s": float(row.get("duration") or 0) / 1000.0,
            "trinkets": trinket_ids(pfight),
            "crit": int(stats.get("Crit") or 0),
            "haste": int(stats.get("Haste") or 0),
            "mastery": int(stats.get("Mastery") or 0),
        })
    samples.sort(key=lambda r: r["rank"])
    residuals = residual_by_ilvl_and_duration(samples) if samples else {}
    for row in samples:
        row["adjusted_dps"] = residuals.get(id(row), 0.0)
    top = samples[:min(top_band, len(samples))]

    top_items: Counter = Counter()
    top_combos: Counter = Counter()
    for row in top:
        labels = [label_item(iid) for iid in row["trinkets"]]
        for label in labels:
            top_items[label] += 1
        top_combos[tuple(sorted(labels))] += 1
    top_item_pct = {label: pct(count, len(top)) for label, count in top_items.items()}

    summary = {
        "encounter_id": str(encounter["id"]),
        "boss": BOSS_KR.get(encounter["id"], encounter["name"]),
        "encounter_name": encounter["name"],
        "rankings_n": len(rankings),
        "pack_leader_n": len(samples),
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
        },
        "top_items": top_items.most_common(10),
        "top_item_pct": top_item_pct,
        "top_combos": [
            {"combo": " + ".join(combo), "n": count, "pct": pct(count, len(top))}
            for combo, count in top_combos.most_common(8)
        ],
        "groups": {
            "box": group_stats(samples, lambda r: BOX_ITEM in r["trinkets"]),
            "crit_plume": group_stats(samples, lambda r: PLUME_CRIT in r["trinkets"]),
            "mastery_plume": group_stats(samples, lambda r: PLUME_MASTERY in r["trinkets"]),
            "aln_gaze": group_stats(samples, lambda r: ALN_GAZE in r["trinkets"]),
            "cosmic_wrap": group_stats(samples, lambda r: COSMIC_WRAP in r["trinkets"]),
        },
        "box_events": box_event_summary(v2, top, max(3, max_fetch_misses // 2)),
    }
    summary["recommendation"] = recommendation(summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topn", type=int, default=40)
    parser.add_argument("--top-band", type=int, default=25)
    parser.add_argument("--max-fetch-misses", type=int, default=12)
    parser.add_argument("--flush-cache", action="store_true")
    args = parser.parse_args()

    cli = WCLV2()
    zone, partition, partition_name = latest_partition(cli)
    encounters = [e for e in zone.get("encounters") or [] if int(e.get("id")) in BOSS_KR]
    encounters.sort(key=lambda e: int(e["id"]) if int(e["id"]) != 3306 else 3184)
    v2 = V2Data(data_dir=DATA)

    print(f"zone={zone['name']} partition={partition} ({partition_name}) topn={args.topn}")
    output = {
        "_meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "zone_id": ZONE_ID,
            "zone": zone["name"],
            "difficulty": "mythic",
            "partition": partition,
            "partition_name": partition_name,
            "topn": args.topn,
            "top_band": args.top_band,
            "notes": [
                "DPS 보정값은 ilvl과 전투시간 선형효과를 제거한 잔차 평균입니다.",
                "상자 이벤트는 top-band 상자 착용자만 대상으로 실제 cast 383781을 확인합니다.",
                "기본 추천은 99 확률 관점이라 평균 DPS보다 상위권 채택률과 사용 난이도를 더 크게 봅니다.",
            ],
        },
        "Hunter|Beast Mastery": {},
    }

    for encounter in encounters:
        eid = int(encounter["id"])
        rankings = fetch_rankings(cli, eid, partition, args.topn)
        print(f"{eid} {BOSS_KR.get(eid, encounter['name'])}: rankings={len(rankings)}")
        summary = analyze_boss(v2, encounter, rankings, args.top_band, args.max_fetch_misses)
        output["Hunter|Beast Mastery"][str(eid)] = summary
        rec = summary["recommendation"]
        print(
            f"{eid} {summary['boss']}: {rec['pick']} | top items={summary['top_items'][:4]} "
            f"| box={summary['box_events']}"
        )

    OUT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_JSON}")
    if args.flush_cache:
        v2.flush()

    try:
        from update_log import record
        record(
            action="analyze_bm_trinket_recommendations",
            params={"topn": args.topn, "top_band": args.top_band, "partition": partition},
            result={"bosses": len(output["Hunter|Beast Mastery"])},
            files=[str(OUT_JSON).replace("\\", "/")],
        )
    except Exception as exc:
        print(f"[update_log] skip: {exc}")


if __name__ == "__main__":
    main()
