"""야수 사냥꾼(BM) 특성 노드 보스별 분기 실측 — rank 1~20 vs 21~100.

입력(캐시만, API 호출 없음):
  data/rankings_zone46_mythic_dps_top100.csv  (Hunter/Beast Mastery 900행 → pf 매칭 890)
  data/v2_cache_player_fight.json             (nodes/talents/talent_points)
  data/talent_trees.json                      ('Hunter/Beast Mastery' — 노드/선택지 한글명)

이름 원칙: talent_trees.json 의 공식 한글명 그대로 사용 (냉법과 달리 추측 불필요).
선택(CHOICE) 노드의 플레이어측 entry_id ↔ 옵션 매핑:
  노드 안에서 entry_id 오름차순 = 옵션 talent_id 오름차순 대응.
  검증: 110164 에서 희생의 포효(53480, 액티브) 시전자는 전원 entry 136686 보유
        (수호자의 가죽 entry 136685 보유자는 0명) + 구세대 노드들은 talent_id-entry_id
        차가 4826 으로 일정 (131226-126400, 131227-126401, 131232-126406, 131284-126458).
출력: data/bm_talent_splits.json
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
OUT = DATA / "bm_talent_splits.json"

BOSS_KR = {
    "3176": "아베르지안", "3177": "보라시우스", "3178": "바엘고어",
    "3179": "살라다르", "3180": "선봉대", "3181": "우주의 왕관",
    "3182": "벨로렌", "3183": "한밤의 도래(르우라)", "3306": "카이메루스",
}
BOSS_ORDER = ["3176", "3177", "3178", "3179", "3180", "3181", "3182", "3183", "3306"]
TOP_BAND = 20
BEAST_CLEAVE = 102341  # 야수의 회전베기


def load_tree():
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))
    bm = tt["Hunter/Beast Mastery"]
    node_name, node_tree, node_type, talent_name, node_opts, node_desc = {}, {}, {}, {}, {}, {}
    def take(nodes, label):
        for nd in nodes:
            opts = nd.get("options") or []
            nm = opts[0]["name"] if len(opts) == 1 else (" / ".join(o["name"] for o in opts) or None)
            node_name[nd["id"]] = nm
            node_tree[nd["id"]] = label
            node_type[nd["id"]] = nd["type"]
            node_opts[nd["id"]] = sorted(((o["talent_id"], o["name"], o.get("desc", "")) for o in opts),
                                         key=lambda x: x[0])
            node_desc[nd["id"]] = " / ".join((o.get("desc") or "")[:90] for o in opts)
            for o in opts:
                talent_name[o["talent_id"]] = o["name"]
    take(bm["class"], "직업(사냥꾼 공용)")
    take(bm["spec"], "야수 전문화")
    hero_sets = {}
    for tname, h in bm["hero"].items():
        take(h["nodes"], f"영웅({tname})")
        hero_sets[tname] = set(nd["id"] for nd in h["nodes"])
    return node_name, node_tree, node_type, talent_name, node_opts, node_desc, hero_sets


def load_sample():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    out = []
    for r in rows:
        if r["class"] != "Hunter" or r["spec"].replace(" ", "") != "BeastMastery":
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
    node_name, node_tree, node_type, talent_name, node_opts, node_desc, hero_sets = load_tree()
    S = load_sample()
    n = len(S)
    print(f"BM 표본 {n}")

    # ---------- 1) 영웅트리 분류 ----------
    hero_by_boss = defaultdict(Counter)
    hero_total = Counter()
    for s in S:
        best = max(hero_sets, key=lambda t: len(s["nodes"] & hero_sets[t]))
        ov = len(s["nodes"] & hero_sets[best])
        s["hero"] = best if ov >= 8 else "불명"
        hero_total[s["hero"]] += 1
        hero_by_boss[s["boss"]][s["hero"]] += 1

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
        # 스왑 상관 (이 노드 보유/미보유 그룹의 다른 가변노드 채택률 차)
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

    # ---------- 4) 빌드 분기 (야수의 회전베기 102341) ----------
    cleave_build = {}
    for bid in BOSS_ORDER:
        bs = [s for s in S if s["boss_id"] == bid]
        top = [s for s in bs if s["rank"] <= TOP_BAND]
        rest = [s for s in bs if s["rank"] > TOP_BAND]
        r_all = sum(1 for s in bs if BEAST_CLEAVE in s["nodes"]) / len(bs)
        rt = sum(1 for s in top if BEAST_CLEAVE in s["nodes"]) / len(top) if top else 0
        rr = sum(1 for s in rest if BEAST_CLEAVE in s["nodes"]) / len(rest) if rest else 0
        # 킬타임 비교 (채택 vs 미채택)
        with_d = sorted(s["dur"] for s in bs if BEAST_CLEAVE in s["nodes"])
        wo_d = sorted(s["dur"] for s in bs if BEAST_CLEAVE not in s["nodes"])
        med = lambda a: round(a[len(a) // 2], 1) if a else None
        cleave_build[BOSS_KR[bid]] = {
            "rate": round(r_all, 3), "top20": round(rt, 3), "rest": round(rr, 3),
            "n_with": len(with_d), "n_without": len(wo_d),
            "kill_med_with": med(with_d), "kill_med_without": med(wo_d),
        }

    # ---------- 5) 선택(CHOICE) 노드 옵션 ----------
    # 플레이어측 entry_id ↔ 옵션명: 노드 내 entry_id 오름차순 = talent_id 오름차순 대응
    # (희생의 포효 시전 실측으로 검증 — 파일 상단 주석 참조)
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
            "mapping_basis": "entry_id 오름차순=talent_id 오름차순 (110164 희생의 포효 시전 실측 검증 + ID 오프셋 4826 일치)",
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

    # ---------- 7) 유틸 노드 보스 스왑 (보스간 채택률 진폭 큰 직업트리 노드) ----------
    util_swaps = []
    for nid in variable:
        v = variable_nodes[str(nid)]
        if v["tree"] != "직업(사냥꾼 공용)":
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

    # 빌드(회전베기 유무) 고정 후에도 남는 보스별 진폭 → 진짜 기믹 스왑
    for u in util_swaps:
        nid = u["node"]
        ctrl = {}
        for build_has, label in ((False, "단일빌드만"), (True, "회전베기빌드만")):
            per = {}
            for bid in BOSS_ORDER:
                bs = [s for s in S if s["boss_id"] == bid
                      and (BEAST_CLEAVE in s["nodes"]) == build_has]
                if len(bs) < 20:
                    continue
                per[BOSS_KR[bid]] = round(sum(1 for s in bs if nid in s["nodes"]) / len(bs), 3)
            if len(per) >= 2:
                ctrl[label] = {"per_boss": per,
                               "spread": round(max(per.values()) - min(per.values()), 3)}
        u["build_controlled"] = ctrl
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
            "source": "rankings_zone46_mythic_dps_top100.csv(2026-07-03) + v2_cache_player_fight.json + talent_trees.json — API 호출 없음",
            "spec": "Hunter|BeastMastery", "sample_n": n, "top_band": TOP_BAND,
            "naming_rule": "노드/선택지 한글명은 talent_trees.json('Hunter/Beast Mastery') 공식 데이터 그대로.",
        },
        "hero_tree": {
            "total": dict(hero_total),
            "per_boss": {b: dict(c) for b, c in hero_by_boss.items()},
            "comment": None,  # 아래에서 채움
        },
        "build_uniformity": {
            "total_nodes_seen": len(cnt),
            "unanimous_98pct": len(unanimous),
            "unanimous_nodes": {str(x): node_name.get(x) for x in unanimous},
            "variable_nodes": len(variable),
        },
        "beast_cleave_build": cleave_build,
        "variable_nodes": variable_nodes,
        "per_boss_top20_vs_rest": per_boss_splits,
        "choice_nodes": choice_nodes,
        "utility_boss_swaps": util_swaps,
        "two_point_splits": point_splits,
    }
    dr = hero_total.get("어둠 순찰자", 0)
    pl = hero_total.get("무리의 지도자", 0)
    out["hero_tree"]["comment"] = (
        f"{n}명 중 무리의 지도자 {pl}, 어둠 순찰자 {dr}. "
        + ("전 보스 100% 무리의 지도자 — 어둠 순찰자는 상위권에서 소멸." if dr == 0 else "")
    )
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {OUT}")

    # 콘솔 요약
    print("\n=== 영웅트리 ===")
    print(out["hero_tree"]["comment"])
    print("\n=== 야수의 회전베기(102341) 보스별 ===")
    for b, v in cleave_build.items():
        print(f"  {b}: 전체 {v['rate']:.0%} (top20 {v['top20']:.0%} / rest {v['rest']:.0%}) "
              f"킬중앙 채택 {v['kill_med_with']} vs 미채택 {v['kill_med_without']}")
    print("\n=== 가변 노드 (보스 진폭 큰 순) ===")
    for nid_s, v in sorted(variable_nodes.items(), key=lambda kv: -kv[1]["boss_spread"])[:20]:
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
        print(f"  {u['name']}: 진폭 {u['spread']:.0%} (빌드고정 후 {cs:.0%}) — 최고 {hi_b} {hi_r:.0%} / 최저 {lo_b} {lo_r:.0%}"
              if cs is not None else
              f"  {u['name']}: 진폭 {u['spread']:.0%} — 최고 {hi_b} {hi_r:.0%} / 최저 {lo_b} {lo_r:.0%}")
        for label, c in u["build_controlled"].items():
            print(f"      {label}: {c['per_boss']}")
    print("\n=== 선택 노드 옵션 ===")
    for nid_s, v in choice_nodes.items():
        o = ", ".join(f"{x['name']} {x['share']:.0%}" for x in v["options"])
        print(f"  {nid_s} {v['name']} [{v['tree']}]: {o}")


if __name__ == "__main__":
    main()
