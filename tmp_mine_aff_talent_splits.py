"""고통 흑마법사(Affliction) 특성 노드 보스별 분기 실측 — rank 1~20 vs 21~100.

입력(캐시만, API 호출 없음):
  data/rankings_zone46_mythic_dps_top100.csv  (2026-07-05, Warlock/Affliction 878행 → pf 매칭 876)
  data/v2_cache_player_fight.json             (nodes/talents/talent_points)
  data/talent_trees.json                      ('Warlock/Affliction' — 노드/선택지 한글명)

이름 원칙: talent_trees.json 의 공식 한글명 그대로 사용.
선택(CHOICE) 노드의 플레이어측 entry_id ↔ 옵션 매핑:
  1옵션 노드들에서 talent_id - entry_id 오프셋을 실측해 상수인지 검증 후,
  상수면 entry_id+오프셋 == talent_id 직접 매핑, 아니면 오름차순 대응(BM 방식) 폴백.
출력: data/aff_talent_splits.json
"""
from __future__ import annotations
import csv, json, sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path(__file__).parent / "data"
OUT = DATA / "aff_talent_splits.json"

BOSS_KR = {
    "3176": "아베르지안", "3177": "보라시우스", "3178": "바엘고어",
    "3179": "살라다르", "3180": "선봉대", "3181": "우주의 왕관",
    "3182": "벨로렌", "3183": "한밤의 도래(르우라)", "3306": "카이메루스",
}
BOSS_ORDER = ["3176", "3177", "3178", "3179", "3180", "3181", "3182", "3183", "3306"]
TOP_BAND = 20
APEX_ROWS = (11, 12)  # spec 트리 최하단 = 정점 특성


def load_tree():
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))
    aff = tt["Warlock/Affliction"]
    node_name, node_tree, node_type, talent_name, node_opts, node_desc = {}, {}, {}, {}, {}, {}
    node_row = {}
    def take(nodes, label):
        for nd in nodes:
            opts = nd.get("options") or []
            nm = opts[0]["name"] if len(opts) == 1 else (" / ".join(o["name"] for o in opts) or None)
            node_name[nd["id"]] = nm
            node_tree[nd["id"]] = label
            node_type[nd["id"]] = nd["type"]
            node_row[nd["id"]] = nd.get("row")
            node_opts[nd["id"]] = sorted(((o["talent_id"], o["name"], o.get("desc", "")) for o in opts),
                                         key=lambda x: x[0])
            node_desc[nd["id"]] = " / ".join((o.get("desc") or "")[:90] for o in opts)
            for o in opts:
                talent_name[o["talent_id"]] = o["name"]
    take(aff["class"], "직업(흑마법사 공용)")
    take(aff["spec"], "고통 전문화")
    hero_sets = {}
    for tname, h in aff["hero"].items():
        take(h["nodes"], f"영웅({tname})")
        hero_sets[tname] = set(nd["id"] for nd in h["nodes"])
    apex_ids = [nd["id"] for nd in aff["spec"] if nd.get("row") in APEX_ROWS]
    return (node_name, node_tree, node_type, talent_name, node_opts, node_desc,
            hero_sets, node_row, apex_ids)


def load_sample():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    out = []
    for r in rows:
        if r["class"] != "Warlock" or r["spec"] != "Affliction":
            continue
        p = pf.get(f'{r["report_id"]}:{int(r["fight_id"])}:{r["character"]}')
        if not (isinstance(p, dict) and p.get("nodes")):
            continue
        out.append({
            "boss_id": r["encounter_id"], "boss": BOSS_KR[r["encounter_id"]],
            "rank": int(r["rank"]), "dps": float(r["dps"]) if r["dps"] else 0.0,
            "dur": int(r["duration_ms"]) / 1000,
            "nodes": set(int(x) for x in p["nodes"]),
            "nodes_seq": [int(x) for x in p["nodes"]],
            "talents": [int(x) for x in (p.get("talents") or [])],
            "points": p.get("talent_points") or {},
        })
    return out


def main() -> None:
    (node_name, node_tree, node_type, talent_name, node_opts, node_desc,
     hero_sets, node_row, apex_ids) = load_tree()
    S = load_sample()
    n = len(S)
    print(f"고통 흑마 표본 {n}")

    # ---------- 1) 영웅트리 분류 ----------
    hero_by_boss = defaultdict(Counter)
    hero_top_by_boss = defaultdict(Counter)
    hero_total = Counter()
    for s in S:
        best = max(hero_sets, key=lambda t: len(s["nodes"] & hero_sets[t]))
        ov = len(s["nodes"] & hero_sets[best])
        s["hero"] = best if ov >= 8 else "불명"
        hero_total[s["hero"]] += 1
        hero_by_boss[s["boss"]][s["hero"]] += 1
        if s["rank"] <= TOP_BAND:
            hero_top_by_boss[s["boss"]][s["hero"]] += 1

    # ---------- 2) 노드 채택률 (만장일치 / 가변 / 죽은 노드) ----------
    cnt = Counter()
    for s in S:
        for nid in s["nodes"]:
            cnt[nid] += 1
    unanimous = sorted(nid for nid, c in cnt.items() if c >= 0.98 * n)
    variable = sorted((nid for nid, c in cnt.items() if 0.02 * n <= c < 0.98 * n),
                      key=lambda x: -cnt[x])
    # 죽은 노드: 트리에 존재하나 채택 <2% (영웅트리는 해당 트리 채택자 대비)
    dead_nodes = {}
    hero_pop = {t: sum(1 for s in S if s["hero"] == t) for t in hero_sets}
    for nid, tree_label in node_tree.items():
        c = cnt.get(nid, 0)
        if tree_label.startswith("영웅("):
            tname = tree_label[3:-1]
            base = hero_pop.get(tname, 0)
            if base < 20:  # 그 영웅트리 자체가 비주류면 판단 보류
                continue
        else:
            base = n
        if base and c / base < 0.02:
            dead_nodes[str(nid)] = {"name": node_name.get(nid), "tree": tree_label,
                                    "type": node_type.get(nid), "picked": c, "base": base,
                                    "desc": node_desc.get(nid, "")[:150]}
    print(f"노드 종류 {len(cnt)} · 만장일치(98%+) {len(unanimous)} · 가변 {len(variable)} · 죽은 노드 {len(dead_nodes)}")

    # node ↔ entry 페어링 (choice 노드 옵션 분해)
    pairs = defaultdict(Counter)
    for s in S:
        if len(s["nodes_seq"]) == len(s["talents"]):
            for nid, tid in zip(s["nodes_seq"], s["talents"]):
                pairs[nid][tid] += 1

    # entry ↔ talent 오프셋 검증 (1옵션 노드에서 실측)
    offset_cnt = Counter()
    for nid, tc in pairs.items():
        opts = node_opts.get(nid) or []
        if len(opts) == 1 and len(tc) == 1:
            eid = next(iter(tc))
            offset_cnt[opts[0][0] - eid] += 1
    dominant_offset, dom_n = (offset_cnt.most_common(1)[0] if offset_cnt else (None, 0))
    offset_consistent = bool(offset_cnt) and dom_n / sum(offset_cnt.values()) >= 0.95
    print(f"entry→talent 오프셋 분포: {dict(offset_cnt.most_common(5))} → "
          f"{'상수 ' + str(dominant_offset) if offset_consistent else '비상수(오름차순 폴백)'}")

    def map_entries(nid, entry_ids):
        """entry_id -> 옵션(talent_id, name, desc). 오프셋 우선, 실패 시 오름차순."""
        opts = node_opts.get(nid) or []
        emap = {}
        if offset_consistent:
            by_tid = {tid: (tid, nm, ds) for tid, nm, ds in opts}
            if all((e + dominant_offset) in by_tid for e in entry_ids):
                for e in entry_ids:
                    tid, nm, ds = by_tid[e + dominant_offset]
                    emap[e] = {"name": nm, "talent_id": tid, "desc": ds[:120]}
                return emap, "offset"
        if len(entry_ids) == len(opts):
            for eid, (tid, nm, ds) in zip(sorted(entry_ids), opts):
                emap[eid] = {"name": nm, "talent_id": tid, "desc": ds[:120]}
            return emap, "ascending"
        return emap, "unmapped"

    def band_rates(group, nid):
        top = [s for s in group if s["rank"] <= TOP_BAND]
        rest = [s for s in group if s["rank"] > TOP_BAND]
        rt = sum(1 for s in top if nid in s["nodes"]) / len(top) if top else 0
        rr = sum(1 for s in rest if nid in s["nodes"]) / len(rest) if rest else 0
        return round(rt, 3), round(rr, 3)

    # ---------- 3) 가변 노드 상세 ----------
    variable_nodes = {}
    for nid in variable:
        per_boss = {}
        for bid in BOSS_ORDER:
            bs = [s for s in S if s["boss_id"] == bid]
            rate = sum(1 for s in bs if nid in s["nodes"]) / len(bs)
            rt, rr = band_rates(bs, nid)
            per_boss[BOSS_KR[bid]] = {"rate": round(rate, 3), "top20": rt, "rest": rr,
                                      "gap": round(rt - rr, 3)}
        rt_all, rr_all = band_rates(S, nid)
        H = [s for s in S if nid in s["nodes"]]
        O = [s for s in S if nid not in s["nodes"]]
        rel = []
        for other in variable:
            if other == nid:
                continue
            rh = sum(1 for s in H if other in s["nodes"]) / len(H)
            ro = sum(1 for s in O if other in s["nodes"]) / len(O)
            if abs(rh - ro) >= 0.30:
                rel.append({"node": other, "name": node_name.get(other),
                            "with_rate": round(rh, 3), "without_rate": round(ro, 3)})
        rel.sort(key=lambda x: abs(x["with_rate"] - x["without_rate"]), reverse=True)
        rates = [per_boss[BOSS_KR[b]]["rate"] for b in BOSS_ORDER]
        variable_nodes[str(nid)] = {
            "name": node_name.get(nid),
            "tree": node_tree.get(nid, "?"),
            "type": node_type.get(nid, "?"),
            "overall_rate": round(cnt[nid] / n, 3),
            "boss_spread": round(max(rates) - min(rates), 3),
            "pooled_top20": rt_all, "pooled_rest": rr_all,
            "pooled_gap": round(rt_all - rr_all, 3),
            "per_boss": per_boss,
            "swap_relations": rel[:6],
        }

    # ---------- 4) 정점 특성 (spec 트리 row 11~12) ----------
    apex = {}
    for nid in apex_ids:
        per_boss = {}
        for bid in BOSS_ORDER:
            bs = [s for s in S if s["boss_id"] == bid]
            rate = sum(1 for s in bs if nid in s["nodes"]) / len(bs)
            rt, rr = band_rates(bs, nid)
            per_boss[BOSS_KR[bid]] = {"rate": round(rate, 3), "top20": rt, "rest": rr}
        apex[str(nid)] = {
            "name": node_name.get(nid), "row": node_row.get(nid),
            "type": node_type.get(nid),
            "overall_rate": round(cnt.get(nid, 0) / n, 3),
            "per_boss": per_boss,
            "desc": node_desc.get(nid, "")[:150],
        }

    # ---------- 5) 선택(CHOICE) 노드 옵션 ----------
    choice_nodes = {}
    for nid, tc in pairs.items():
        if len(tc) < 2:
            continue
        total = sum(tc.values())
        if total > n or total < 20:
            continue
        minor = total - tc.most_common(1)[0][1]
        if minor / total < 0.02:
            continue
        emap, basis = map_entries(nid, list(tc))
        opts = []
        for eid, c in tc.most_common():
            holders = [s for s in S if eid in set(s["talents"])]
            topc = sum(1 for s in holders if s["rank"] <= TOP_BAND)
            per_boss_share = {}
            for bid in BOSS_ORDER:
                bs = [s for s in S if s["boss_id"] == bid]
                bh = sum(1 for s in bs if eid in set(s["talents"]))
                per_boss_share[BOSS_KR[bid]] = round(bh / len(bs), 3)
            m = emap.get(eid, {})
            opts.append({"entry_id": eid, "name": m.get("name"),
                         "desc": m.get("desc"),
                         "share": round(c / total, 3),
                         "top20_share_within": round(topc / len(holders), 3) if holders else 0,
                         "per_boss": per_boss_share})
        choice_nodes[str(nid)] = {
            "name": node_name.get(nid), "tree": node_tree.get(nid, "?"),
            "picked_by": total,
            "mapping_basis": basis + (f" (talent_id-entry_id={dominant_offset}, 1옵션 노드 {dom_n}건 실측)"
                                      if basis == "offset" else ""),
            "options": opts,
        }

    # ---------- 6) 보스별 top20 차별 픽 ----------
    per_boss_splits = {}
    for bid in BOSS_ORDER:
        bs = [s for s in S if s["boss_id"] == bid]
        top = [s for s in bs if s["rank"] <= TOP_BAND]
        rest = [s for s in bs if s["rank"] > TOP_BAND]
        splits = []
        for nid in variable:
            rt, rr = band_rates(bs, nid)
            if abs(rt - rr) >= 0.12:
                splits.append({"node": nid, "name": node_name.get(nid),
                               "tree": node_tree.get(nid, "?"),
                               "top20_rate": rt, "rest_rate": rr, "gap": round(rt - rr, 3)})
        splits.sort(key=lambda x: -abs(x["gap"]))
        per_boss_splits[BOSS_KR[bid]] = {
            "boss_id": bid, "n_top": len(top), "n_rest": len(rest), "splits": splits,
        }

    # ---------- 7) 유틸 노드 보스 스왑 (직업트리, 보스간 진폭) ----------
    main_heroes = [t for t, c in hero_total.most_common() if c >= 20 and t != "불명"]
    util_swaps = []
    for nid in variable:
        v = variable_nodes[str(nid)]
        if v["tree"] != "직업(흑마법사 공용)":
            continue
        if v["boss_spread"] >= 0.15:
            rates = {b: v["per_boss"][b]["rate"] for b in v["per_boss"]}
            hi = max(rates, key=rates.get)
            lo = min(rates, key=rates.get)
            util_swaps.append({"node": nid, "name": v["name"], "spread": v["boss_spread"],
                               "overall": v["overall_rate"],
                               "desc": node_desc.get(nid, "")[:180],
                               "highest": {hi: rates[hi]}, "lowest": {lo: rates[lo]},
                               "per_boss_rate": rates})
    util_swaps.sort(key=lambda x: -x["spread"])
    # 영웅트리 고정 후에도 남는 진폭 → 진짜 기믹 스왑 (흑마 빌드 축 = 영웅트리)
    for u in util_swaps:
        nid = u["node"]
        ctrl = {}
        for hname in main_heroes:
            per = {}
            for bid in BOSS_ORDER:
                bs = [s for s in S if s["boss_id"] == bid and s["hero"] == hname]
                if len(bs) < 20:
                    continue
                per[BOSS_KR[bid]] = round(sum(1 for s in bs if nid in s["nodes"]) / len(bs), 3)
            if len(per) >= 2:
                ctrl[f"{hname}만"] = {"per_boss": per,
                                     "spread": round(max(per.values()) - min(per.values()), 3)}
        u["hero_controlled"] = ctrl
        u["controlled_spread"] = max((c["spread"] for c in ctrl.values()), default=None)

    # ---------- 8) 2포인트 노드 투자 갈림 ----------
    pt = defaultdict(Counter)
    for s in S:
        if len(s["nodes_seq"]) == len(s["talents"]):
            for nid, tid in zip(s["nodes_seq"], s["talents"]):
                rk = s["points"].get(str(tid))
                if rk:
                    pt[nid][rk] += 1
    point_splits = {}
    for nid, c in pt.items():
        if sum(pairs[nid].values()) > n:
            continue
        if len(c) >= 2 and sum(c.values()) >= 20 and min(c.values()) >= 10:
            point_splits[str(nid)] = {"name": node_name.get(nid), "ranks": dict(sorted(c.items()))}

    out = {
        "_meta": {
            "source": "rankings_zone46_mythic_dps_top100.csv(2026-07-05) + v2_cache_player_fight.json + talent_trees.json — API 호출 없음",
            "spec": "Warlock|Affliction", "sample_n": n, "top_band": TOP_BAND,
            "naming_rule": "노드/선택지 한글명은 talent_trees.json('Warlock/Affliction') 공식 데이터 그대로.",
        },
        "hero_tree": {
            "total": dict(hero_total),
            "per_boss": {b: dict(c) for b, c in hero_by_boss.items()},
            "per_boss_top20": {b: dict(c) for b, c in hero_top_by_boss.items()},
            "comment": None,
        },
        "build_uniformity": {
            "total_nodes_seen": len(cnt),
            "unanimous_98pct": len(unanimous),
            "unanimous_nodes": {str(x): node_name.get(x) for x in unanimous},
            "variable_nodes": len(variable),
        },
        "dead_nodes": dead_nodes,
        "apex_talents": apex,
        "variable_nodes": variable_nodes,
        "per_boss_top20_vs_rest": per_boss_splits,
        "choice_nodes": choice_nodes,
        "utility_boss_swaps": util_swaps,
        "two_point_splits": point_splits,
    }
    parts = ", ".join(f"{t} {c}" for t, c in hero_total.most_common())
    out["hero_tree"]["comment"] = f"{n}명 중 {parts}."
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {OUT}")

    # 콘솔 요약
    print("\n=== 영웅트리 ===")
    print(out["hero_tree"]["comment"])
    for bid in BOSS_ORDER:
        b = BOSS_KR[bid]
        print(f"  {b}: 전체 {dict(hero_by_boss[b])} / top20 {dict(hero_top_by_boss[b])}")
    print("\n=== 정점 특성 (spec row 11~12) ===")
    for nid_s, v in apex.items():
        print(f"  {nid_s} {v['name']} row{v['row']} 전체 {v['overall_rate']:.0%}")
    print("\n=== 죽은 노드 (<2%) ===")
    for nid_s, v in dead_nodes.items():
        print(f"  {nid_s} {v['name']} [{v['tree']}] {v['picked']}/{v['base']}")
    print("\n=== 가변 노드 (보스 진폭 큰 순) ===")
    for nid_s, v in sorted(variable_nodes.items(), key=lambda kv: -kv[1]["boss_spread"])[:25]:
        print(f"  {nid_s} {v['name']} [{v['tree']}] 전체 {v['overall_rate']:.0%} 진폭 {v['boss_spread']:.0%} "
              f"(top20 {v['pooled_top20']:.0%} vs rest {v['pooled_rest']:.0%})")
    print("\n=== 보스별 top20 차별 픽 (12%p+) ===")
    for b, v in per_boss_splits.items():
        if v["splits"]:
            tags = ", ".join(f"{x['name']}({x['gap']:+.0%})" for x in v["splits"][:6])
            print(f"  {b}: {tags}")
    print("\n=== 유틸(직업트리) 보스 스왑 ===")
    for u in util_swaps[:14]:
        hi_b, hi_r = next(iter(u["highest"].items()))
        lo_b, lo_r = next(iter(u["lowest"].items()))
        cs = u["controlled_spread"]
        print(f"  {u['name']}: 진폭 {u['spread']:.0%}" +
              (f" (영웅고정 후 {cs:.0%})" if cs is not None else "") +
              f" — 최고 {hi_b} {hi_r:.0%} / 최저 {lo_b} {lo_r:.0%}")
        for label, c in u["hero_controlled"].items():
            print(f"      {label}: {c['per_boss']}")
    print("\n=== 선택 노드 옵션 ===")
    for nid_s, v in choice_nodes.items():
        o = ", ".join(f"{x['name']} {x['share']:.0%}" for x in v["options"])
        print(f"  {nid_s} {v['name']} [{v['tree']}]: {o}")
    print("\n=== 2포인트 투자 갈림 ===")
    for nid_s, v in point_splits.items():
        print(f"  {nid_s} {v['name']}: {v['ranks']}")


if __name__ == "__main__":
    main()
