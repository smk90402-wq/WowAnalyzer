"""악마 흑마(Demonology) 특성 노드 보스별 분기 실측 — rank 1~20 vs 21~100.

입력(캐시만, API 호출 없음):
  data/rankings_zone46_mythic_dps_top100.csv  (Warlock/Demonology 900행, 2026-07-05)
  data/v2_cache_player_fight.json             (nodes/talents/talent_points)
  data/talent_trees.json                      ('Warlock/Demonology' — 노드/선택지 한글명)

이름 원칙: talent_trees.json 의 공식 한글명 그대로 사용 (BM 템플릿과 동일).
선택(CHOICE) 노드의 플레이어측 entry_id ↔ 옵션 매핑:
  노드 안에서 entry_id 오름차순 = 옵션 talent_id 오름차순 대응 (BM 에서 실측 검증된 규칙).
출력: data/demo_talent_splits.json
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
OUT = DATA / "demo_talent_splits.json"

BOSS_KR = {
    "3176": "아베르지안", "3177": "보라시우스", "3178": "바엘고어",
    "3179": "살라다르", "3180": "선봉대", "3181": "우주의 왕관",
    "3182": "벨로렌", "3183": "한밤의 도래(르우라)", "3306": "카이메루스",
}
BOSS_ORDER = ["3176", "3177", "3178", "3179", "3180", "3181", "3182", "3183", "3306"]
TOP_BAND = 20


def load_tree():
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))
    demo = tt["Warlock/Demonology"]
    node_name, node_tree, node_type, talent_name = {}, {}, {}, {}
    node_opts, node_desc, node_row = {}, {}, {}
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
    take(demo["class"], "직업(흑마 공용)")
    take(demo["spec"], "악마 전문화")
    hero_sets = {}
    for tname, h in demo["hero"].items():
        take(h["nodes"], f"영웅({tname})")
        hero_sets[tname] = set(nd["id"] for nd in h["nodes"])
    # 정점(spec 트리 최하단 행) 후보
    spec_rows = [nd.get("row") for nd in demo["spec"] if nd.get("row") is not None]
    max_row = max(spec_rows) if spec_rows else None
    apex_ids = [nd["id"] for nd in demo["spec"] if nd.get("row") == max_row]
    all_tree_ids = set(node_name)
    return (node_name, node_tree, node_type, talent_name, node_opts, node_desc,
            node_row, hero_sets, apex_ids, max_row, all_tree_ids)


def load_sample():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    out = []
    for r in rows:
        if r["class"] != "Warlock" or r["spec"] != "Demonology":
            continue
        p = pf.get(f'{r["report_id"]}:{int(r["fight_id"])}:{r["character"]}')
        if not (isinstance(p, dict) and p.get("nodes")):
            continue
        out.append({
            "boss_id": r["encounter_id"], "boss": BOSS_KR[r["encounter_id"]],
            "rank": int(r["rank"]), "dps": float(r["dps"]),
            "dur": int(r["duration_ms"]) / 1000,
            "nodes": set(int(x) for x in p["nodes"]),
            "nodes_seq": [int(x) for x in p["nodes"]],
            "talents": [int(x) for x in (p.get("talents") or [])],
            "points": p.get("talent_points") or {},
        })
    return out


def main() -> None:
    (node_name, node_tree, node_type, talent_name, node_opts, node_desc,
     node_row, hero_sets, apex_ids, max_row, all_tree_ids) = load_tree()
    S = load_sample()
    n = len(S)
    print(f"악마 흑마 표본 {n}")

    # ---------- 1) 영웅트리 분류 ----------
    hero_by_boss = defaultdict(Counter)
    hero_total = Counter()
    for s in S:
        best = max(hero_sets, key=lambda t: len(s["nodes"] & hero_sets[t]))
        ov = len(s["nodes"] & hero_sets[best])
        s["hero"] = best if ov >= 8 else "불명"
        hero_total[s["hero"]] += 1
        hero_by_boss[s["boss"]][s["hero"]] += 1

    # 영웅트리별 성적/보스 분포 (분포가 갈리면 밴드 비교)
    hero_perf = {}
    for h in hero_total:
        g = [s for s in S if s["hero"] == h]
        topc = sum(1 for s in g if s["rank"] <= TOP_BAND)
        hero_perf[h] = {"n": len(g), "top20_n": topc,
                        "top20_share_within": round(topc / len(g), 3) if g else 0}

    # ---------- 2) 노드 채택률 ----------
    cnt = Counter()
    for s in S:
        for nid in s["nodes"]:
            cnt[nid] += 1
    unanimous = sorted(nid for nid, c in cnt.items() if c >= 0.98 * n)
    variable = sorted((nid for nid, c in cnt.items() if 0.02 * n <= c < 0.98 * n),
                      key=lambda x: -cnt[x])
    print(f"노드 종류 {len(cnt)} · 만장일치(98%+) {len(unanimous)} · 가변 {len(variable)}")

    # node ↔ talent 페어링 (choice 노드 옵션 분해)
    pairs = defaultdict(Counter)
    for s in S:
        if len(s["nodes_seq"]) == len(s["talents"]):
            for nid, tid in zip(s["nodes_seq"], s["talents"]):
                pairs[nid][tid] += 1

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

    # ---------- 4) 선택(CHOICE) 노드 옵션 ----------
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
        entry_sorted = sorted(tc)
        tree_opts = node_opts.get(nid) or []
        emap = {}
        if len(entry_sorted) == len(tree_opts):
            for eid, (tid, nm, ds) in zip(entry_sorted, tree_opts):
                emap[eid] = {"name": nm, "talent_id": tid, "desc": ds[:120]}
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
            "mapping_basis": "entry_id 오름차순=talent_id 오름차순 (BM 110164 희생의 포효 시전 실측으로 검증된 규칙 재사용)",
            "options": opts,
        }

    # ---------- 5) 보스별 top20 차별 픽 ----------
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

    # ---------- 6) 유틸 노드 보스 스왑 (직업트리, 보스간 진폭 큰 것) ----------
    util_swaps = []
    for nid in variable:
        v = variable_nodes[str(nid)]
        if v["tree"] != "직업(흑마 공용)":
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

    # ---------- 7) 정점 특성 (spec 트리 최하단 행) ----------
    apex = {}
    for nid in apex_ids:
        rt_all, rr_all = band_rates(S, nid)
        per_boss = {}
        for bid in BOSS_ORDER:
            bs = [s for s in S if s["boss_id"] == bid]
            per_boss[BOSS_KR[bid]] = round(sum(1 for s in bs if nid in s["nodes"]) / len(bs), 3)
        apex[str(nid)] = {"name": node_name.get(nid), "row": node_row.get(nid),
                          "type": node_type.get(nid),
                          "overall_rate": round(cnt.get(nid, 0) / n, 3),
                          "top20": rt_all, "rest": rr_all,
                          "per_boss": per_boss}

    # ---------- 8) 죽은 노드 (트리에 있는데 900명 중 채택 0 또는 <2%) ----------
    dead = []
    for nid in sorted(all_tree_ids):
        c = cnt.get(nid, 0)
        if c < 0.02 * n:
            dead.append({"node": nid, "name": node_name.get(nid),
                         "tree": node_tree.get(nid), "type": node_type.get(nid),
                         "picked_n": c,
                         "desc": node_desc.get(nid, "")[:140]})

    # ---------- 9) 2포인트 노드 투자 갈림 ----------
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
            "spec": "Warlock|Demonology", "sample_n": n, "top_band": TOP_BAND,
            "naming_rule": "노드/선택지 한글명은 talent_trees.json('Warlock/Demonology') 공식 데이터 그대로.",
            "apex_row": max_row,
        },
        "hero_tree": {
            "total": dict(hero_total),
            "per_boss": {b: dict(c) for b, c in hero_by_boss.items()},
            "perf": hero_perf,
        },
        "build_uniformity": {
            "total_nodes_seen": len(cnt),
            "unanimous_98pct": len(unanimous),
            "unanimous_nodes": {str(x): node_name.get(x) for x in unanimous},
            "variable_nodes": len(variable),
        },
        "variable_nodes": variable_nodes,
        "per_boss_top20_vs_rest": per_boss_splits,
        "choice_nodes": choice_nodes,
        "utility_boss_swaps": util_swaps,
        "apex_talents": apex,
        "dead_nodes": dead,
        "two_point_splits": point_splits,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {OUT}")

    # 콘솔 요약
    print("\n=== 영웅트리 ===")
    for h, c in hero_total.most_common():
        print(f"  {h}: {c} ({hero_perf[h]})")
    for b in [BOSS_KR[x] for x in BOSS_ORDER]:
        print(f"    {b}: {dict(hero_by_boss[b])}")
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
        print(f"  {u['name']}: 진폭 {u['spread']:.0%} — 최고 {hi_b} {hi_r:.0%} / 최저 {lo_b} {lo_r:.0%}")
    print("\n=== 정점 특성 (row", max_row, ") ===")
    for nid_s, v in apex.items():
        print(f"  {nid_s} {v['name']}: 전체 {v['overall_rate']:.0%} (top20 {v['top20']:.0%} / rest {v['rest']:.0%})")
    print("\n=== 선택 노드 옵션 ===")
    for nid_s, v in choice_nodes.items():
        o = ", ".join(f"{x['name']} {x['share']:.0%}" for x in v["options"])
        print(f"  {nid_s} {v['name']} [{v['tree']}]: {o}")
    print(f"\n=== 죽은 노드(<2%) {len(dead)}개 ===")
    for d in dead:
        if d["tree"] and d["tree"].startswith("영웅"):
            continue
        print(f"  {d['node']} {d['name']} [{d['tree']}] {d['picked_n']}명")


if __name__ == "__main__":
    main()
