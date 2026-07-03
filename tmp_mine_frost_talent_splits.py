"""냉기 법사 특성(노드) 보스별 분기 실측 — rank 1~20 vs 21~100. (v2)

입력(캐시만, API 호출 없음):
  data/rankings_zone46_mythic_dps_top100.csv  (Mage/Frost 900행 → pf 매칭 885)
  data/v2_cache_player_fight.json             (nodes/talents/talent_points)
  scratchpad/frost_event_sets.json            (냉법 301킬 시전/버프 집합 — 이름 해석 근거)
  data/spell_db.json                          (spell_id → 한글명)

이름 원칙(추측 금지):
  - talent_trees.json 에 Mage/Frost 없음 → 노드 이름은 이벤트 증거로만 부여.
    (그 노드 보유자만 시전/보유한 스펠 → 스펠 한글명. 유일 확증: 62124=환영 복제)
  - 트리 구분은 Fire/Arcane top100 표본과의 공유율로 실측 분류
    (둘 다 공유=직업 공용 / 냉기+비전만 공유=주문술사 영웅 / 냉기 단독=냉기 전용).
  - 영웅트리는 885명 전원 동일 노드셋 + 쇄편폭풍(1247908) 버프 302/302 → 주문술사.

출력: data/frost_talent_splits.json
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
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")
OUT = DATA / "frost_talent_splits.json"

BOSS_KR = {
    "3176": "아베르지안", "3177": "보라시우스", "3178": "바엘고어",
    "3179": "살라다르", "3180": "선봉대", "3181": "우주의 왕관",
    "3182": "벨로렌", "3183": "한밤의 도래(르우라)", "3306": "카이메루스",
}
BOSS_ORDER = ["3176", "3177", "3178", "3179", "3180", "3181", "3182", "3183", "3306"]
TOP_BAND = 20

# 이벤트 증거로 확정된 노드 이름 (보유자만 해당 버프/시전 보유, 비보유자 0%)
NODE_NAMES_EVIDENCE = {
    62124: {"name": "환영 복제", "evidence": "버프 55342 '환영 복제' — 보유자 61%가 사용, 비보유자(11명) 0%", "kind": "buff"},
}
HERO_EVIDENCE = "쇄편폭풍(1247908) 버프 302/302 전원 관측 + 비전 법사 top100의 94%와 동일 노드 공유(화염 0%) → 주문술사(Spellslinger)"


def load_sample():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))

    def spec_rows(cls, spec):
        out = []
        for r in rows:
            if r["class"] != cls or r["spec"] != spec:
                continue
            p = pf.get(f'{r["report_id"]}:{int(r["fight_id"])}:{r["character"]}')
            if isinstance(p, dict) and p.get("nodes"):
                out.append((r, p))
        return out

    frost = []
    for r, p in spec_rows("Mage", "Frost"):
        frost.append({
            "boss_id": r["encounter_id"], "boss": BOSS_KR[r["encounter_id"]],
            "rank": int(r["rank"]), "dps": float(r["dps"]),
            "nodes": set(int(x) for x in p["nodes"]),
            "talents": [int(x) for x in (p.get("talents") or [])],
            "nodes_seq": [int(x) for x in p["nodes"]],
            "points": p.get("talent_points") or {},
        })
    fire = [set(int(x) for x in p["nodes"]) for _, p in spec_rows("Mage", "Fire")]
    arc = [set(int(x) for x in p["nodes"]) for _, p in spec_rows("Mage", "Arcane")]
    return frost, fire, arc


def main() -> None:
    frost, fire, arc = load_sample()
    n = len(frost)
    print(f"냉법 표본 {n} / 화염 {len(fire)} / 비전 {len(arc)}")

    # 노드 채택률(전체)
    cnt = Counter()
    for s in frost:
        for nid in s["nodes"]:
            cnt[nid] += 1
    unanimous = sorted(nid for nid, c in cnt.items() if c >= 0.98 * n)
    variable = sorted((nid for nid, c in cnt.items() if 0.02 * n <= c < 0.98 * n),
                      key=lambda x: -cnt[x])
    print(f"노드 종류 {len(cnt)} · 만장일치(98%+) {len(unanimous)} · 가변 {len(variable)}")

    # 트리 실측 분류 (Fire/Arcane 공유율)
    def share(nid, group):
        return round(sum(1 for ns in group if nid in ns) / len(group), 3) if group else 0.0

    def tree_label(nid):
        f, a = share(nid, fire), share(nid, arc)
        if f >= 0.3 and a >= 0.3:
            return "직업 공용"
        if f >= 0.3 or a >= 0.3:
            return "직업 공용(일부 스펙만 채택)" if nid < 90000 else ("주문술사 영웅" if a >= 0.3 and f < 0.05 else "직업 공용(일부 스펙만 채택)")
        if f == 0 and a == 0:
            return "냉기 전용"
        return "직업 공용(냉기 위주)"

    # node ↔ talent 페어링 (choice 노드 옵션 분해)
    pairs = defaultdict(Counter)
    for s in frost:
        if len(s["nodes_seq"]) == len(s["talents"]):
            for nid, tid in zip(s["nodes_seq"], s["talents"]):
                pairs[nid][tid] += 1

    # 가변 노드 상세
    def band_rates(group, nid):
        top = [s for s in group if s["rank"] <= TOP_BAND]
        rest = [s for s in group if s["rank"] > TOP_BAND]
        rt = sum(1 for s in top if nid in s["nodes"]) / len(top) if top else 0
        rr = sum(1 for s in rest if nid in s["nodes"]) / len(rest) if rest else 0
        return round(rt, 3), round(rr, 3)

    variable_nodes = {}
    for nid in variable:
        per_boss = {}
        for bid in BOSS_ORDER:
            bs = [s for s in frost if s["boss_id"] == bid]
            rate = sum(1 for s in bs if nid in s["nodes"]) / len(bs)
            rt, rr = band_rates(bs, nid)
            per_boss[BOSS_KR[bid]] = {"rate": round(rate, 3), "top20": rt, "rest": rr,
                                      "gap": round(rt - rr, 3)}
        rt_all, rr_all = band_rates(frost, nid)
        # 전역 안티/동반 상관 (스왑 축)
        H = [s for s in frost if nid in s["nodes"]]
        O = [s for s in frost if nid not in s["nodes"]]
        rel = []
        for other in variable:
            if other == nid:
                continue
            rh = sum(1 for s in H if other in s["nodes"]) / len(H)
            ro = sum(1 for s in O if other in s["nodes"]) / len(O)
            if abs(rh - ro) >= 0.20:
                rel.append({"node": other, "with_rate": round(rh, 3), "without_rate": round(ro, 3)})
        rel.sort(key=lambda x: abs(x["with_rate"] - x["without_rate"]), reverse=True)
        info = NODE_NAMES_EVIDENCE.get(nid)
        variable_nodes[str(nid)] = {
            "name": info["name"] if info else None,
            "name_evidence": info["evidence"] if info else None,
            "tree": tree_label(nid),
            "overall_rate": round(cnt[nid] / n, 3),
            "fire_share": share(nid, fire), "arcane_share": share(nid, arc),
            "talent_ids": [t for t, _ in pairs.get(nid, Counter()).most_common()],
            "pooled_top20": rt_all, "pooled_rest": rr_all,
            "pooled_gap": round(rt_all - rr_all, 3),
            "per_boss": per_boss,
            "swap_relations": rel[:6],
        }

    # 보스별 요약: top20 이 나머지와 12%p 이상 다르게 가져가는 노드
    per_boss_splits = {}
    for bid in BOSS_ORDER:
        bs = [s for s in frost if s["boss_id"] == bid]
        top = [s for s in bs if s["rank"] <= TOP_BAND]
        rest = [s for s in bs if s["rank"] > TOP_BAND]
        splits = []
        for nid in variable:
            rt, rr = band_rates(bs, nid)
            if abs(rt - rr) >= 0.12:
                info = NODE_NAMES_EVIDENCE.get(nid)
                splits.append({"node": nid, "name": info["name"] if info else None,
                               "tree": tree_label(nid),
                               "top20_rate": rt, "rest_rate": rr, "gap": round(rt - rr, 3)})
        splits.sort(key=lambda x: -abs(x["gap"]))
        per_boss_splits[BOSS_KR[bid]] = {
            "boss_id": bid, "n_top": len(top), "n_rest": len(rest), "splits": splits,
        }

    # 선택(CHOICE) 노드 옵션 (실질 갈림 2% 이상만)
    choice_nodes = {}
    for nid, tc in pairs.items():
        if len(tc) < 2:
            continue
        total = sum(tc.values())
        if total > n or total < 20:   # 슬롯 여러 개(선택형 묶음 885×k) 또는 표본 부족
            continue
        minor = total - tc.most_common(1)[0][1]
        if minor / total < 0.02:
            continue
        # 옵션별 top20 비중
        opts = []
        for tid, c in tc.most_common():
            holders = [s for s in frost if tid in set(s["talents"])]
            topc = sum(1 for s in holders if s["rank"] <= TOP_BAND)
            opts.append({"talent_id": tid, "share": round(c / total, 3),
                         "top20_share_within": round(topc / len(holders), 3) if holders else 0})
        choice_nodes[str(nid)] = {
            "tree": tree_label(nid), "picked_by": total,
            "name": (NODE_NAMES_EVIDENCE.get(nid) or {}).get("name"),
            "options": opts,
        }

    # 2포인트 노드 투자 갈림
    point_splits = {}
    for s in frost:
        pass
    pt = defaultdict(Counter)
    for s in frost:
        if len(s["nodes_seq"]) == len(s["talents"]):
            for nid, tid in zip(s["nodes_seq"], s["talents"]):
                rk = s["points"].get(str(tid))
                if rk:
                    pt[nid][rk] += 1
    for nid, c in pt.items():
        if sum(pairs[nid].values()) > n:   # 다중 슬롯 노드 제외
            continue
        if len(c) >= 2 and sum(c.values()) >= 20 and min(c.values()) >= 10:
            point_splits[str(nid)] = dict(sorted(c.items()))

    out = {
        "_meta": {
            "source": "rankings_zone46_mythic_dps_top100.csv + v2_cache_player_fight.json + events 캐시(301킬) — API 호출 없음",
            "spec": "Mage|Frost", "sample_n": n,
            "top_band": TOP_BAND,
            "naming_rule": "노드 이름은 이벤트 실측 증거로만 부여(추측 금지). 근거 없으면 null — node ID + 채택률로 보고.",
            "tree_rule": "트리 구분은 화염/비전 top100 표본과의 노드 공유율로 실측 분류 (talent_trees.json 에 Mage/Frost 없음).",
        },
        "hero_tree": {
            "result": "885명 전원(100%) 동일 영웅트리 — 주문술사(Spellslinger)",
            "evidence": HERO_EVIDENCE,
            "frostfire_users": 0,
            "hero_choice_nodes": {
                "94660": {"options": [{"talent_id": 117263, "share": round(pairs[94660][117263] / n, 3)},
                                       {"talent_id": 123417, "share": round(pairs[94660][123417] / n, 3)}]},
                "94659": {"options": [{"talent_id": 117262, "share": round(pairs[94659][117262] / n, 3)},
                                       {"talent_id": 123418, "share": round(pairs[94659][123418] / n, 3)}]},
            },
        },
        "build_uniformity": {
            "total_nodes_seen": len(cnt),
            "unanimous_98pct": len(unanimous),
            "variable_nodes": len(variable),
            "comment": "빌드 뼈대는 사실상 고정 — 갈리는 건 15개 노드뿐. 100% 채택 액티브(전원 시전): 얼음 화살·얼음창·진눈깨비·얼어붙은 구슬·혹한의 쐐기·서리 광선. 혜성 폭풍은 301킬에서 시전 0회(아무도 안 씀).",
        },
        "variable_nodes": variable_nodes,
        "per_boss_top20_vs_rest": per_boss_splits,
        "choice_nodes": choice_nodes,
        "two_point_splits": point_splits,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {OUT}")

    # 콘솔 요약
    print("\n=== 가변 노드 (전체 채택률순) ===")
    for nid_s, v in variable_nodes.items():
        print(f"  {nid_s} {v['name'] or '?'} [{v['tree']}] {v['overall_rate']:.0%} "
              f"(top20 {v['pooled_top20']:.0%} vs rest {v['pooled_rest']:.0%})")
    print("\n=== 보스별 top20 차별 픽 ===")
    for b, v in per_boss_splits.items():
        if v["splits"]:
            tags = ", ".join(f"{x['node']}({x['gap']:+.0%})" for x in v["splits"][:6])
            print(f"  {b}: {tags}")


if __name__ == "__main__":
    main()
