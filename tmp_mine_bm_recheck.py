"""BM 07-05 재검증 — 07-04 가이드 결론이 오늘자(07-05) 신규 로그로 흔들리는지 확인.

읽기 전용. 커밋 대상 JSON 을 덮어쓰지 않음 — 결과는 스크래치패드로만.
입력(캐시만, API 없음):
  data/rankings_zone46_mythic_dps_top100.csv  (07-05 05:34 재수집본)
  data/v2_cache_player_fight.json             (07-05 06:12 백필본, nodes/talents)
  data/talent_trees.json
비교 기준: data/bm_talent_splits.json (07-03 데이터로 계산된 가이드 근거)

산출: 영웅트리 채택, 회전베기(단일/광 빌드) 보스별 채택, 핵심 가변노드(자연의 교감자↔꿰뚫는 송곳니 등)
      → 07-04 가이드 문장의 수치와 diff.
"""
from __future__ import annotations
import csv, json, sys
from collections import Counter, defaultdict
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(__file__).parent / "data"
SCR = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")

BOSS_KR = {
    "3176": "아베르지안", "3177": "보라시우스", "3178": "바엘고어",
    "3179": "살라다르", "3180": "선봉대", "3181": "우주의 왕관",
    "3182": "벨로렌", "3183": "르우라", "3306": "카이메루스",
}
BOSS_ORDER = ["3176", "3177", "3178", "3179", "3180", "3181", "3182", "3183", "3306"]
TOP_BAND = 20
BEAST_CLEAVE_NODE = 102341  # 야수의 회전베기 노드


def load_tree():
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))
    bm = tt["Hunter/Beast Mastery"]
    node_name, node_tree, hero_sets = {}, {}, {}
    def take(nodes, label):
        for nd in nodes:
            opts = nd.get("options") or []
            nm = opts[0]["name"] if len(opts) == 1 else (" / ".join(o["name"] for o in opts) or None)
            node_name[nd["id"]] = nm
            node_tree[nd["id"]] = label
    take(bm["class"], "직업")
    take(bm["spec"], "야수")
    for tname, h in bm["hero"].items():
        take(h["nodes"], f"영웅({tname})")
        hero_sets[tname] = set(nd["id"] for nd in h["nodes"])
    return node_name, node_tree, hero_sets


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
            "nodes": set(int(x) for x in p["nodes"]),
            "talents": set(int(x) for x in (p.get("talents") or [])),
        })
    return out


def rate(group, pred):
    g = list(group)
    return (sum(1 for s in g if pred(s)) / len(g)) if g else 0.0


def band_rates(group, pred):
    top = [s for s in group if s["rank"] <= TOP_BAND]
    rest = [s for s in group if s["rank"] > TOP_BAND]
    return rate(top, pred), rate(rest, pred)


def main():
    node_name, node_tree, hero_sets = load_tree()
    S = load_sample()
    n = len(S)
    lines = []
    def P(x=""):
        print(x); lines.append(str(x))

    P(f"[BM 07-05 재검증] 표본 {n} (nodes 보유 pf 기준)")

    # 1) 영웅트리
    hero_total = Counter()
    for s in S:
        best = max(hero_sets, key=lambda t: len(s["nodes"] & hero_sets[t]))
        ov = len(s["nodes"] & hero_sets[best])
        s["hero"] = best if ov >= 8 else "불명"
        hero_total[s["hero"]] += 1
    P(f"\n=== 영웅트리 === {dict(hero_total)}")
    P("  가이드 근거: 890명 전원 무리의 지도자, 어둠 순찰자 0명")

    # 2) 회전베기 보스별 (단일/광 빌드 분기)
    P("\n=== 야수의 회전베기(102341) 보스별 채택 [07-05 vs 07-04가이드] ===")
    baseline = json.load(open(DATA / "bm_talent_splits.json", encoding="utf-8"))
    base_cleave = baseline["beast_cleave_build"]
    guide_claims = {
        "바엘고어": "100%", "선봉대": "100%", "아베르지안": "92%",
        "보라시우스": "0~4%", "우주의 왕관": "0~4%", "르우라": "0~4%", "벨로렌": "0~4%",
        "살라다르": "top20 60% vs rest 32%", "카이메루스": "top20 70% vs rest 40%",
    }
    cleave_now = {}
    for bid in BOSS_ORDER:
        bs = [s for s in S if s["boss_id"] == bid]
        r_all = rate(bs, lambda s: BEAST_CLEAVE_NODE in s["nodes"])
        rt, rr = band_rates(bs, lambda s: BEAST_CLEAVE_NODE in s["nodes"])
        b = BOSS_KR[bid]
        base = base_cleave.get(b, {})
        cleave_now[b] = {"rate": round(r_all, 3), "top20": round(rt, 3), "rest": round(rr, 3), "n": len(bs)}
        P(f"  {b:8s} n={len(bs):3d}  전체 {r_all:5.0%} (top20 {rt:4.0%} / rest {rr:4.0%})"
          f"  | 07-03 전체 {base.get('rate',0):5.0%} (top20 {base.get('top20',0):.0%}/rest {base.get('rest',0):.0%})"
          f"  | 가이드: {guide_claims.get(b,'')}")

    # 3) 핵심 가변 노드 — 자연의 교감자 ↔ 꿰뚫는 송곳니 (단일/광 스왑축)
    # 가이드: 단일보스(보라시우스·왕관·르우라)=교감자 100%, 광보스(바엘고어·선봉대)=0%
    # 노드ID를 이름으로 역인덱스
    name2node = defaultdict(list)
    for nid, nm in node_name.items():
        if nm: name2node[nm].append(nid)
    def find_node(substr):
        hits = [nid for nid, nm in node_name.items() if nm and substr in nm]
        return hits
    P("\n=== 핵심 가변 노드 확인 (이름 검색) ===")
    for kw in ["교감", "송곳니", "우두머리", "포식자", "멧돼지 기수", "전쟁 명령", "날카로운 비늘",
               "피의 향기", "피의 광란", "무리의 지도자의 포효"]:
        hits = find_node(kw)
        for nid in hits:
            r_all = rate(S, lambda s: nid in s["nodes"])
            P(f"  '{kw}' → node {nid} [{node_tree.get(nid)}] {node_name.get(nid)}  전체채택 {r_all:.0%}")

    # 4) 보스별 top20 갈림 재검 — 살라다르·카이메루스 회전베기 갭
    P("\n=== 살라다르·카이메루스 회전베기 top20 vs rest 갭 재검 ===")
    for bid, bname, claim in [("3179","살라다르","top20 60% vs rest 32%(갭+28)"),
                              ("3306","카이메루스","top20 70% vs rest 40%(갭+30)")]:
        bs = [s for s in S if s["boss_id"] == bid]
        rt, rr = band_rates(bs, lambda s: BEAST_CLEAVE_NODE in s["nodes"])
        P(f"  {bname}: top20 {rt:.0%} vs rest {rr:.0%} (갭 {rt-rr:+.0%}) [07-05]  | 가이드 {claim}")

    # 5) 자연의 교감자/꿰뚫는 송곳니 보스별 (단일 vs 광)
    comp = find_node("교감")
    fang = find_node("송곳니")
    if comp and fang:
        cnid, fnid = comp[0], fang[0]
        P(f"\n=== 자연의 교감자(node {cnid}) 보스별 채택 [가이드: 단일100%/광0%] ===")
        for bid in BOSS_ORDER:
            bs = [s for s in S if s["boss_id"] == bid]
            rc = rate(bs, lambda s: cnid in s["nodes"])
            rf = rate(bs, lambda s: fnid in s["nodes"])
            P(f"  {BOSS_KR[bid]:8s} 교감자 {rc:4.0%} / 송곳니 {rf:4.0%}")

    out = {
        "sample_n": n, "hero_total": dict(hero_total),
        "cleave_now": cleave_now, "cleave_baseline_0703": base_cleave,
    }
    (SCR / "bm_recheck_0705.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (SCR / "bm_recheck_0705.txt").write_text("\n".join(lines), encoding="utf-8")
    P(f"\n저장: {SCR / 'bm_recheck_0705.json'}")


if __name__ == "__main__":
    main()
