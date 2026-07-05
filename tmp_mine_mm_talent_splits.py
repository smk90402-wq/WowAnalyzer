# -*- coding: utf-8 -*-
"""사격 사냥꾼(MM) 특성 노드 보스별 분기 실측 — rank 1~20 vs 21~100.

패턴은 tmp_mine_bm_talent_splits.py 를 그대로 따름 (BM/MM 트리 구조 동일 계열).

입력(캐시만, API 호출 없음):
  data/rankings_zone46_mythic_dps_top100.csv  (Hunter/Marksmanship 900행)
  data/v2_cache_player_fight.json             (nodes/talents/talent_points)
  data/talent_trees.json                      ('Hunter/Marksmanship' — 노드/선택지 한글명)

★스펙 주의: 사용자가 어둠 순찰자(Dark Ranger) 영웅특성 중심 분석을 요청.
  영웅특성 채택률(어둠 순찰자 vs 파수꾼)을 최우선 산출하고, 이후 차원 해석은
  다수파 영웅특성 기준으로 본다.★
  (talent_trees.json 의 hero 딕셔너리에는 '무리의 지도자'도 들어있으나 이는
   Blizzard API가 사냥꾼 클래스트리 전체를 반환하는 특성 — 실제 MM은 파수꾼/
   어둠 순찰자만 선택 가능. 실측으로도 무리의 지도자 채택 0명이면 그대로 확인.)

이름 원칙: talent_trees.json 의 공식 한글명 그대로 사용.
선택(CHOICE) 노드의 플레이어측 entry_id ↔ 옵션 매핑:
  노드 안에서 entry_id 오름차순 = 옵션 talent_id 오름차순 대응 (BM에서 검증된 규칙,
  구세대 노드들은 talent_id-entry_id 차가 4826으로 일정 — 동일 사냥꾼 클래스 트리라 재확인 없이 적용).
출력: data/mm_talent_splits.json
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
OUT = DATA / "mm_talent_splits.json"

BOSS_KR = {
    "3176": "아베르지안", "3177": "보라시우스", "3178": "바엘고어",
    "3179": "살라다르", "3180": "선봉대", "3181": "우주의 왕관",
    "3182": "벨로렌", "3183": "한밤의 도래(르우라)", "3306": "카이메루스",
}
BOSS_ORDER = ["3176", "3177", "3178", "3179", "3180", "3181", "3182", "3183", "3306"]
TOP_BAND = 20


def load_tree():
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))
    mm = tt["Hunter/Marksmanship"]
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
    take(mm["class"], "직업(사냥꾼 공용)")
    take(mm["spec"], "사격 전문화")
    hero_sets = {}
    for tname, h in mm["hero"].items():
        take(h["nodes"], f"영웅({tname})")
        hero_sets[tname] = set(nd["id"] for nd in h["nodes"])
    return node_name, node_tree, node_type, talent_name, node_opts, node_desc, hero_sets


def load_sample():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    out = []
    for r in rows:
        if r["class"] != "Hunter" or r["spec"].replace(" ", "") != "Marksmanship":
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
    print(f"MM 표본 {n}")

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

    # ---------- 2b) 영웅특성별 분리 채택률 (어둠 순찰자 vs 파수꾼) ----------
    # 사용자 요청 핵심: 다수파 영웅특성 기준으로 이후 해석. 각 노드를 헤어 그룹별로도 집계.
    hero_groups = {h: [s for s in S if s["hero"] == h] for h in ("어둠 순찰자", "파수꾼")}
    hero_node_rate = {}
    for h, grp in hero_groups.items():
        if not grp:
            continue
        c = Counter()
        for s in grp:
            for nid in s["nodes"]:
                c[nid] += 1
        hero_node_rate[h] = {nid: v / len(grp) for nid, v in c.items()}

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
        by_hero = {h: round(hero_node_rate[h].get(nid, 0.0), 3) for h in hero_node_rate}
        variable_nodes[str(nid)] = {
            "name": node_name.get(nid),
            "tree": node_tree.get(nid, "?"),
            "type": node_type.get(nid, "?"),
            "overall_rate": round(cnt[nid] / n, 3),
            "by_hero": by_hero,
            "boss_spread": round(max(rates) - min(rates), 3),
            "pooled_top20": rt_all, "pooled_rest": rr_all,
            "pooled_gap": round(rt_all - rr_all, 3),
            "per_boss": per_boss,
            "swap_relations": rel[:6],
        }

    # ---------- 4) 선택(CHOICE) 노드 옵션 ----------
    # 플레이어측 entry_id ↔ 옵션명: 노드 내 entry_id 오름차순 = talent_id 오름차순 대응
    # 99831: talent_trees.json 상 options=[] (이름 매핑 불가) — 실측 카운트(477/419)가
    # 정확히 파수꾼/어둠 순찰자 인원수와 일치 = 영웅트리 선택을 나타내는 내부 마커 노드로 판단.
    # spell_db 매핑도 "그림"/"못 자란 시각 효과: 당근" 등 무관한 placeholder라 팬 번역명 검증 불가 → 제외.
    DEAD_UNMAPPED_NODES = {99831}
    choice_nodes = {}
    for nid, tc in pairs.items():
        if len(tc) < 2 or nid in DEAD_UNMAPPED_NODES:
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
            hero_share = {}
            for h, grp in hero_groups.items():
                if not grp:
                    continue
                hh = sum(1 for s in grp if eid in set(s["talents"]))
                hero_share[h] = round(hh / len(grp), 3)
            m = emap.get(eid, {})
            opts.append({"entry_id": eid, "name": m.get("name"),
                         "desc": m.get("desc"),
                         "share": round(c / total, 3),
                         "top20_share_within": round(topc / len(holders), 3) if holders else 0,
                         "per_boss": per_boss_share,
                         "by_hero": hero_share})
        choice_nodes[str(nid)] = {
            "name": node_name.get(nid), "tree": node_tree.get(nid, "?"),
            "picked_by": total,
            "mapping_basis": "entry_id 오름차순=talent_id 오름차순 (BM 110164 희생의 포효 시전 실측으로 검증된 규칙 — 동일 사냥꾼 클래스 트리라 재사용)",
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

    # ---------- 6) 유틸 노드 보스 스왑 (보스간 채택률 진폭 큰 직업트리 노드) ----------
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

    # 영웅특성 고정 후에도 남는 보스별 진폭 → 진짜 기믹 스왑 (다수파 영웅특성 기준 우선 확인)
    for u in util_swaps:
        nid = u["node"]
        ctrl = {}
        for hero_label in ("어둠 순찰자", "파수꾼"):
            per = {}
            for bid in BOSS_ORDER:
                bs = [s for s in S if s["boss_id"] == bid and s["hero"] == hero_label]
                if len(bs) < 15:
                    continue
                per[BOSS_KR[bid]] = round(sum(1 for s in bs if nid in s["nodes"]) / len(bs), 3)
            if len(per) >= 2:
                ctrl[hero_label] = {"per_boss": per,
                                     "spread": round(max(per.values()) - min(per.values()), 3)}
        u["hero_controlled"] = ctrl
        u["controlled_spread"] = max((c["spread"] for c in ctrl.values()), default=None)

    # ---------- 7) 2포인트 노드 투자 갈림 ----------
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

    # ---------- 8) 정점 특성(마지막 행) 채택 ----------
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))["Hunter/Marksmanship"]
    apex_row = max(nd["row"] for nd in tt["spec"])
    apex_nodes = [nd for nd in tt["spec"] if nd["row"] == apex_row]
    apex_info = {}
    for nd in apex_nodes:
        nid = nd["id"]
        rate = round(cnt.get(nid, 0) / n, 3)
        rt, rr = band_rates(S, nid)
        by_hero = {h: round(hero_node_rate[h].get(nid, 0.0), 3) for h in hero_node_rate}
        apex_info[str(nid)] = {"name": node_name.get(nid), "row": apex_row,
                                "rate": rate, "top20": rt, "rest": rr, "by_hero": by_hero}

    out = {
        "_meta": {
            "source": "rankings_zone46_mythic_dps_top100.csv(2026-07-05) + v2_cache_player_fight.json + talent_trees.json — API 호출 없음",
            "spec": "Hunter|Marksmanship", "sample_n": n, "top_band": TOP_BAND,
            "naming_rule": "노드/선택지 한글명은 talent_trees.json('Hunter/Marksmanship') 공식 데이터 그대로.",
            "hero_focus": "사용자 요청: 어둠 순찰자(Dark Ranger) 영웅특성 중심. 이후 차원 해석은 다수파 영웅특성 기준.",
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
        "apex_talent": apex_info,
        "variable_nodes": variable_nodes,
        "per_boss_top20_vs_rest": per_boss_splits,
        "choice_nodes": choice_nodes,
        "utility_boss_swaps": util_swaps,
        "two_point_splits": point_splits,
    }
    dr = hero_total.get("어둠 순찰자", 0)
    sen = hero_total.get("파수꾼", 0)
    pl = hero_total.get("무리의 지도자", 0)
    majority = "어둠 순찰자" if dr > sen else "파수꾼"
    out["hero_tree"]["comment"] = (
        f"{n}명 중 파수꾼 {sen}, 어둠 순찰자 {dr}"
        + (f", 무리의 지도자 {pl}" if pl else "")
        + f". 다수파: {majority} ({max(dr, sen) / n:.0%})."
        + (" 무리의 지도자는 API가 사냥꾼 클래스트리 전체를 반환해 생긴 항목 — 실제 MM 선택 불가, 채택 0명으로 확인." if pl == 0 else "")
    )
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {OUT}")

    # 콘솔 요약
    print("\n=== 영웅트리 ===")
    print(out["hero_tree"]["comment"])
    print("\n=== 영웅트리 보스별 ===")
    for b, c in hero_by_boss.items():
        print(f"  {b}: {dict(c)}")
    print("\n=== 정점 특성 ===")
    for k, v in apex_info.items():
        print(f"  {k} {v['name']}: 전체 {v['rate']:.0%} (top20 {v['top20']:.0%} vs rest {v['rest']:.0%}) by_hero={v['by_hero']}")
    print("\n=== 가변 노드 (보스 진폭 큰 순) ===")
    for nid_s, v in sorted(variable_nodes.items(), key=lambda kv: -kv[1]["boss_spread"])[:20]:
        print(f"  {nid_s} {v['name']} [{v['tree']}] 전체 {v['overall_rate']:.0%} 진폭 {v['boss_spread']:.0%} "
              f"(top20 {v['pooled_top20']:.0%} vs rest {v['pooled_rest']:.0%}) by_hero={v['by_hero']}")
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
        print(f"  {u['name']}: 진폭 {u['spread']:.0%} (영웅고정 후 {cs:.0%}) — 최고 {hi_b} {hi_r:.0%} / 최저 {lo_b} {lo_r:.0%}"
              if cs is not None else
              f"  {u['name']}: 진폭 {u['spread']:.0%} — 최고 {hi_b} {hi_r:.0%} / 최저 {lo_b} {lo_r:.0%}")
        for label, c in u["hero_controlled"].items():
            print(f"      {label}: {c['per_boss']}")
    print("\n=== 선택 노드 옵션 ===")
    for nid_s, v in choice_nodes.items():
        o = ", ".join(f"{x['name']} {x['share']:.0%}" for x in v["options"])
        print(f"  {nid_s} {v['name']} [{v['tree']}]: {o}")
    print("\n=== 2포인트 노드 투자 갈림 ===")
    for nid_s, v in point_splits.items():
        print(f"  {nid_s} {v['name']}: {v['ranks']}")


if __name__ == "__main__":
    main()
