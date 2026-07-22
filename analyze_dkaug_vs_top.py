"""이디죽기(부정)·하늘연달스물엿새(증강) vs 한밤의 도래 신화 탑30 비교 분석.

수집: WCL characterRankings(3183, 신화) 탑30/스펙 → events_for(casts+buffs) + player_fight(gear)
      우리 쪽: report CPA42mqBHXMyca86 의 한밤의 도래 풀 전체 (180s+ 위주)
비교: 물약/생존기/딜쿨(분당)·시전 밀도·핵심 시전 비중·버프 유지율·오프너·장신구
산출: data/dkaug_top_comparison.json (우측 독 죽기/증강 탭 데이터)

사용: python analyze_dkaug_vs_top.py            # 수집+분석
      python analyze_dkaug_vs_top.py --analyze  # 캐시만으로 재분석
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from wcl_v2 import WCLV2
from wcl_v2_data import V2Data

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = DATA / "dkaug_top_comparison.json"

ENCOUNTER_ID = 3183
DIFFICULTY = 5          # 신화
TOP_N = 30
OUR_REPORT = "CPA42mqBHXMyca86"
MIN_OUR_FIGHT_S = 180   # 분당 지표가 의미있는 풀만

SPECS = [
    {
        "key": "dk",
        "tab": "죽기",
        "class_name": "DeathKnight",
        "spec_name": "Unholy",
        "our_char": "이디죽기",
        # 버프 유지율 추적(자기 버프): 어둠의 변신 (12.0 id 1233448 — player_spell_types 실측)
        "uptime_buffs": {1233448: "어둠의 변신"},
    },
    {
        "key": "aug",
        "tab": "증강",
        "class_name": "Evoker",
        "spec_name": "Augmentation",
        "our_char": "하늘연달스물엿새",
        # 칠흑의 힘(395152)은 cast=buff 동일 id (app/aug_feedback.py 검증)
        "uptime_buffs": {395152: "칠흑의 힘"},
    },
]

POTION_HS_IDS = {1234768, 1236616, 1236994, 1236998, 1238443, 431932, 453035, 6262}

Q_TOP = """
query($encounterId: Int!, $difficulty: Int!, $cls: String!, $spec: String!, $partition: Int!, $page: Int!) {
  worldData {
    encounter(id: $encounterId) {
      characterRankings(metric: dps, difficulty: $difficulty,
        className: $cls, specName: $spec, page: $page, partition: $partition)
    }
  }
}
"""
Q_ZONE = 'query($id: Int!) { worldData { zone(id: $id) { partitions { id name default } } } }'


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


SPELL_DB = _load(DATA / "spell_db.json")
SPELL_KINDS = {int(k): v for k, v in _load(DATA / "player_spell_types.json").items()
               if not str(k).startswith("_") and isinstance(v, str)}


def spell_name(gid: int) -> str:
    row = SPELL_DB.get(str(gid))
    if isinstance(row, dict):
        return str(row.get("name_ko") or row.get("name_en") or gid)
    return str(gid)


def med(values: list[float]) -> float | None:
    return round(float(statistics.median(values)), 2) if values else None


def q3(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(float(s[int(len(s) * 0.75)]), 2)


# ── 표본 1개(한 전투의 한 캐릭터) 지표 추출 ────────────────────────────────
def sample_metrics(events: dict, start_ms: float, end_ms: float,
                   uptime_buffs: dict[int, str]) -> dict:
    duration_s = (end_ms - start_ms) / 1000.0
    casts = [(t, gid) for t, gid, typ in (events.get("casts") or []) if typ == "cast"]
    minutes = max(duration_s / 60.0, 0.01)
    per_spell = Counter(gid for _, gid in casts)

    # player_spell_types.json 은 Viserio 라벨: Defensives/Immunities/DPS CD/Potions...
    buckets = {"potion": 0, "defensive": 0, "offensive": 0}
    offensive_by_spell: Counter = Counter()
    defensive_by_spell: Counter = Counter()
    for gid, n in per_spell.items():
        kind = SPELL_KINDS.get(gid, "")
        if gid in POTION_HS_IDS or kind in ("Potions", "Healthpots"):
            buckets["potion"] += n
        elif kind in ("Defensives", "Immunities"):
            buckets["defensive"] += n
            defensive_by_spell[gid] += n
        elif kind in ("DPS CD", "Minor DPS CD"):
            buckets["offensive"] += n
            offensive_by_spell[gid] += n

    # 버프 유지율 (자기 대상 buffs: [ts, gid, type, src, stack?])
    uptimes: dict[int, float] = {}
    for want in uptime_buffs:
        on_at = None
        covered = 0.0
        t0 = None
        for rec in events.get("buffs") or []:
            ts, gid, typ = rec[0], rec[1], rec[2]
            if gid != want:
                continue
            if t0 is None:
                t0 = ts
            if typ in ("applybuff", "refreshbuff", "applybuffstack"):
                if on_at is None:
                    on_at = ts
            elif typ == "removebuff" and on_at is not None:
                covered += (ts - on_at) / 1000.0
                on_at = None
        if on_at is not None:
            covered += max(0.0, (end_ms - on_at) / 1000.0)  # 전투 끝까지 유지
        uptimes[want] = round(min(100.0, covered / duration_s * 100.0), 1)

    return {
        "duration_s": round(duration_s, 1),
        "cpm": round(len(casts) / minutes, 1),
        "per_spell": dict(per_spell),
        "potion_per_fight": buckets["potion"],
        "defensive_pm": round(buckets["defensive"] / minutes, 2),
        "offensive_pm": round(buckets["offensive"] / minutes, 2),
        "offensive_by_spell": dict(offensive_by_spell),
        "defensive_by_spell": dict(defensive_by_spell),
        "uptimes": {str(k): v for k, v in uptimes.items()},
        "opener": [[round((t - casts[0][0]) / 1000.0, 1), gid]
                   for t, gid in casts[:22]] if casts else [],
    }


def collect_top(v2: V2Data, cli: WCLV2, cfg: dict, partition: int) -> list[dict]:
    rows: list[dict] = []
    data = cli.query(Q_TOP, {
        "encounterId": ENCOUNTER_ID, "difficulty": DIFFICULTY,
        "cls": cfg["class_name"], "spec": cfg["spec_name"],
        "partition": partition, "page": 1,
    })
    ranks = ((((data.get("worldData") or {}).get("encounter") or {})
              .get("characterRankings") or {}).get("rankings") or [])
    for rank, row in enumerate(ranks, 1):
        if len(rows) >= TOP_N:
            break
        rep = row.get("report") or {}
        code, fid = rep.get("code"), rep.get("fightID")
        char = row.get("name")
        if not code or not fid or not char:
            continue
        try:
            ev = v2.events_for(code, int(fid), char)
            pf = v2.player_fight(code, int(fid), char)
            meta = v2.report_meta(code)
        except Exception as e:
            print(f"  [{cfg['key']}] #{rank} {char} 수집 실패: {e}")
            continue
        if not ev or not pf or not meta:
            continue
        f = next((x for x in (meta.get("fights") or []) if x.get("id") == int(fid)), None)
        if not f:
            continue
        m = sample_metrics(ev, f["startTime"], f["endTime"], cfg["uptime_buffs"])
        m.update({"rank": rank, "char": char,
                  "dps": round(float(row.get("amount") or 0)),
                  "gear": [g for g in (pf.get("gear") or []) if g.get("slot") in (12, 13)]})
        rows.append(m)
        if len(rows) % 10 == 0:
            v2.flush()   # events 캐시가 거대해서 매 표본 flush 는 디스크 낭비
        print(f"  [{cfg['key']}] #{rank} {char} ok ({m['duration_s']:.0f}s, cpm {m['cpm']})")
    return rows


def collect_ours(v2: V2Data, cfg: dict) -> list[dict]:
    meta = v2.report_meta(OUR_REPORT)
    if not meta:
        return []
    fights = [f for f in meta.get("fights") or []
              if f.get("encounterID") == ENCOUNTER_ID
              and (f["endTime"] - f["startTime"]) / 1000.0 >= MIN_OUR_FIGHT_S]
    out = []
    for f in fights:
        fid = f["id"]
        try:
            ev = v2.events_for(OUR_REPORT, int(fid), cfg["our_char"])
            pf = v2.player_fight(OUR_REPORT, int(fid), cfg["our_char"])
        except Exception as e:
            print(f"  [ours/{cfg['key']}] fight {fid} 실패: {e}")
            continue
        if not ev or not pf:
            continue
        m = sample_metrics(ev, f["startTime"], f["endTime"], cfg["uptime_buffs"])
        m.update({"fight_id": fid,
                  "gear": [g for g in (pf.get("gear") or []) if g.get("slot") in (12, 13)]})
        out.append(m)
        print(f"  [ours/{cfg['key']}] fight {fid} ok ({m['duration_s']:.0f}s, cpm {m['cpm']})")
    return out


# ── 비교 행 생성 ──────────────────────────────────────────────────────────
def verdict(ours: float | None, top: float | None, higher_better=True,
            warn_ratio=0.75) -> str:
    if ours is None or top is None or top == 0:
        return "info"
    ratio = ours / top if higher_better else (top / ours if ours else 0)
    return "good" if ratio >= 0.95 else ("warn" if ratio < warn_ratio else "mid")


def build_comparison(cfg: dict, top: list[dict], ours: list[dict]) -> dict:
    rows: list[dict] = []

    def add(cat, label, ours_v, top_v, unit="", higher=True, note=""):
        if (not ours_v) and (not top_v):
            return   # 양쪽 다 0/None — 의미 없는 행 제거
        rows.append({
            "cat": cat, "label": label,
            "ours": ours_v, "top": top_v, "unit": unit,
            "verdict": verdict(
                ours_v if isinstance(ours_v, (int, float)) else None,
                top_v if isinstance(top_v, (int, float)) else None, higher),
            "note": note,
        })

    o_cpm = med([m["cpm"] for m in ours])
    add("딜사이클", "시전 밀도(분당)", o_cpm, med([m["cpm"] for m in top]), "회/분",
        note="낮으면 빈 GCD·이동 손실이 크다는 뜻")

    # 물약: 상위는 킬(긴 전투) 기준 — 풀당 사용횟수 비교
    add("물약", "전투당 물약·치유물약", med([m["potion_per_fight"] for m in ours]),
        med([m["potion_per_fight"] for m in top]), "회",
        note="상위는 킬 기준(8~9분) — 우리 풀이 짧아도 위기 구간엔 써야 함")
    add("생존기", "생존기 사용(분당)", med([m["defensive_pm"] for m in ours]),
        med([m["defensive_pm"] for m in top]), "회/분")
    add("쿨기", "딜쿨 사용(분당)", med([m["offensive_pm"] for m in ours]),
        med([m["offensive_pm"] for m in top]), "회/분",
        note="정렬 밀림·아껴두기가 누적되면 낮아짐")

    # 버프 유지율
    for gid_s, label in ((str(k), v) for k, v in cfg["uptime_buffs"].items()):
        add("딜사이클", f"{label} 유지율",
            med([m["uptimes"].get(gid_s) for m in ours if m["uptimes"].get(gid_s) is not None]),
            med([m["uptimes"].get(gid_s) for m in top if m["uptimes"].get(gid_s) is not None]),
            "%")

    # 생존기·딜쿨 스킬별 섹션에 나올 gid — 딜패턴 핵심 목록에서 중복 제거용
    sectioned: set[int] = set()
    for m in top:
        sectioned.update(m["defensive_by_spell"].keys())
        sectioned.update(m["offensive_by_spell"].keys())

    # 핵심 시전 비중: 탑에서 많이 쓰는 스킬(중앙값 기준 상위 10) — 분당 비교
    top_pm: defaultdict[int, list[float]] = defaultdict(list)
    for m in top:
        minutes = m["duration_s"] / 60.0
        for gid, n in m["per_spell"].items():
            top_pm[gid].append(n / minutes)
    core = sorted(
        ((gid, med(v)) for gid, v in top_pm.items()
         if gid not in sectioned
         and len(v) >= len(top) * 0.6 and (med(v) or 0) >= 0.4),
        key=lambda x: -(x[1] or 0))[:10]
    ours_pm: defaultdict[int, list[float]] = defaultdict(list)
    for m in ours:
        minutes = m["duration_s"] / 60.0
        for gid, n in m["per_spell"].items():
            ours_pm[gid].append(n / minutes)
    for gid, tv in core:
        add("딜패턴", f"{spell_name(gid)}(분당)", med(ours_pm.get(gid) or [0.0]), tv, "회/분")

    # 생존기·딜쿨 스킬별 (탑 채택 60%+)
    for cat, field in (("생존기", "defensive_by_spell"), ("쿨기", "offensive_by_spell")):
        agg: defaultdict[int, list[float]] = defaultdict(list)
        for m in top:
            minutes = m["duration_s"] / 60.0
            for gid, n in m[field].items():
                agg[gid].append(n / minutes)
        for gid, vals in sorted(agg.items(), key=lambda kv: -(med(kv[1]) or 0)):
            if len(vals) < len(top) * 0.6:
                continue
            o_vals = []
            for m in ours:
                o_vals.append(m[field].get(gid, 0) / (m["duration_s"] / 60.0))
            add(cat, f"{spell_name(gid)}(분당)", med(o_vals), med(vals), "회/분")

    # 장신구 채택
    top_trinkets: Counter = Counter()
    for m in top:
        for g in m.get("gear") or []:
            if g.get("name"):
                top_trinkets[g["name"]] += 1
    our_trinkets = [g.get("name") or "?" for g in (ours[0].get("gear") or [])] if ours else []

    # 오프너: 탑1 vs 우리 최장 풀
    top1 = min(top, key=lambda m: m["rank"]) if top else None
    our_best = max(ours, key=lambda m: m["duration_s"]) if ours else None

    return {
        "tab": cfg["tab"],
        "player": cfg["our_char"],
        "spec": f"{cfg['class_name']}/{cfg['spec_name']}",
        "our_fights": len(ours),
        "top_n": len(top),
        "top_dps_med": med([m["dps"] for m in top]),
        "rows": rows,
        "trinkets": {
            "ours": our_trinkets,
            "top": [{"name": n, "n": c} for n, c in top_trinkets.most_common(6)],
        },
        "opener": {
            "top": [[t, spell_name(g)] for t, g in (top1 or {}).get("opener", [])],
            "top_char": (top1 or {}).get("char", ""),
            "ours": [[t, spell_name(g)] for t, g in (our_best or {}).get("opener", [])],
        },
    }


def main() -> None:
    analyze_only = "--analyze" in sys.argv
    v2 = V2Data()
    cli = v2.cli
    zone = cli.query(Q_ZONE, {"id": 46})["worldData"]["zone"]
    part = next((p for p in zone.get("partitions") or [] if p.get("default")), {"id": 3})
    partition = int(part["id"])

    result = {"encounter_id": ENCOUNTER_ID, "difficulty": "신화",
              "our_report": OUR_REPORT, "specs": {}}
    for cfg in SPECS:
        print(f"== {cfg['tab']} ({cfg['spec_name']}) ==")
        top = collect_top(v2, cli, cfg, partition)
        ours = collect_ours(v2, cfg)
        if not top or not ours:
            print(f"  !! 표본 부족: top={len(top)} ours={len(ours)}")
        result["specs"][cfg["key"]] = build_comparison(cfg, top, ours)
        v2.flush()

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {OUT}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
