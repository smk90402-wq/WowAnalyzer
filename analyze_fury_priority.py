"""분노 전사 프록 우선순위 실측 — 재현 스크립트 + 보스별 분석.

산출물 (data/fury_priority_stats.json + 콘솔):
 A. 보스별 영웅특성 채택률 (산왕 vs 학살자) — rankings+player_fight nodes (전 표본)
 B. 스펙별 메커니즘 검증 — 무모한 희생 중 변형 비율(피범벅/분쇄의 타격),
    칼날폭풍 무모한 희생 정렬%, 우레 작렬 2충전 비율
 C. 보스별 회전 프로필 — 소용돌이/천둥벼락/마무리 일격 시전 비중 (광역성·처형 길이 프록시)

이벤트 추출 캐시(tmp_fury_bs_events.json=학살자, tmp_fury_thane_events.json=산왕)가
있으면 사용, 없으면 v2_cache_events.json(~1.3GB)에서 추출.
"""
from __future__ import annotations
import sys, json, bisect
from pathlib import Path
from collections import Counter, defaultdict
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import pandas as pd

DATA = Path(__file__).parent / "data"
RECK = 1719
PER = 90


def load_common():
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))
    hero = {h: set(n["id"] for n in tt["Warrior/Fury"]["hero"][h]["nodes"])
            for h in ("산왕", "학살자")}
    df = pd.read_csv(DATA / "rankings_zone46_mythic_dps_top100.csv")
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    def nm(s):
        v = db.get(str(s)); v = v if isinstance(v, dict) else {}
        return v.get("name_ko") or f"#{s}"
    return hero, df, pf, nm


def classify(nodes, hero):
    """노드 교집합으로 영웅특성 판별 (>=3 노드)."""
    nodes = set(nodes or [])
    s, t = len(nodes & hero["산왕"]), len(nodes & hero["학살자"])
    if t >= 3 and t >= s: return "학살자"
    if s >= 3: return "산왕"
    return None


def part_A(df, pf, hero):
    """보스별 영웅특성 채택률 (전 표본)."""
    fu = df[(df["class"] == "Warrior") & (df["spec"] == "Fury")]
    out = {}
    for eid, g in fu.groupby("encounter_id"):
        c = Counter(); name = g.iloc[0]["encounter_name"]
        for _, r in g.iterrows():
            p = pf.get(f'{r["report_id"]}:{int(r["fight_id"])}:{r["character"]}')
            if isinstance(p, dict):
                c[classify(p.get("nodes"), hero)] += 1
        tot = c["산왕"] + c["학살자"]
        if tot < 5: continue
        out[int(eid)] = {"boss": name, "n": tot,
                         "산왕": c["산왕"], "학살자": c["학살자"],
                         "산왕%": round(c["산왕"] / tot * 100),
                         "학살자%": round(c["학살자"] / tot * 100)}
    return out


def reck_spans(buffs):
    on, iv = None, []
    for x in sorted((y for y in buffs if len(y) >= 3 and y[1] == RECK), key=lambda z: z[0]):
        if x[2] == "applybuff" and on is None: on = x[0]
        elif x[2] == "removebuff" and on is not None: iv.append((on, x[0])); on = None
    return iv


def part_B(ev, nm, spec):
    """변형 비율 + 칼날폭풍/우레작렬 검증."""
    cc = Counter(); during = Counter()
    bs_total = bs_reck = 0
    tb_stack = Counter()
    for k, e in ev.items():
        if not isinstance(e, dict): continue
        buffs = e.get("buffs") or []
        iv = reck_spans(buffs); starts = [a for a, _ in iv]
        def act(t):
            i = bisect.bisect_right(starts, t) - 1
            return i >= 0 and iv[i][0] <= t <= iv[i][1]
        for c in (e.get("casts") or []):
            if len(c) >= 3 and c[2] == "cast":
                cc[nm(c[1])] += 1
                if act(c[0]): during[nm(c[1])] += 1
        # 칼날폭풍 정렬 (446035 applybuff)
        for b in buffs:
            if len(b) >= 3 and b[1] == 446035 and b[2] == "applybuff":
                bs_total += 1; bs_reck += act(b[0])
            if len(b) >= 3 and b[1] == 435615:  # 우레 작렬 프록 스택
                if b[2] == "applybuffstack": tb_stack[b[4] if len(b) >= 5 else 2] += 1
                elif b[2] == "applybuff": tb_stack[1] += 1
    def share(name):
        return [during[name], cc[name], round(during[name] / cc[name] * 100) if cc[name] else None]
    res = {"n": sum(1 for v in ev.values() if isinstance(v, dict)),
           "피범벅_reck": share("피범벅"), "분쇄의 타격_reck": share("분쇄의 타격"),
           "피의 갈증_reck": share("피의 갈증"), "분노의 강타_reck": share("분노의 강타"),
           "광란_reck": share("광란")}
    if bs_total:
        res["칼날폭풍_정렬"] = [bs_reck, bs_total, round(bs_reck / bs_total * 100)]
    if tb_stack:
        t1, t2 = tb_stack.get(1, 0), tb_stack.get(2, 0)
        res["우레작렬_2충전"] = [t2, t1 + t2, round(t2 / (t1 + t2) * 100) if (t1 + t2) else 0]
    return res


def part_C(ev, df, nm):
    """보스별 회전 프로필 (소용돌이/천둥벼락/마무리 일격 시전 비중)."""
    emap = {(r["report_id"], int(r["fight_id"])): r["encounter_name"] for _, r in df.iterrows()}
    per = defaultdict(lambda: Counter())
    for k, e in ev.items():
        if not isinstance(e, dict): continue
        rid, fid, _ = k.split(":"); enc = emap.get((rid, int(fid)), "?")
        for c in (e.get("casts") or []):
            if len(c) >= 3 and c[2] == "cast":
                per[enc]["_tot"] += 1; per[enc][nm(c[1])] += 1
        per[enc]["_n"] += 1 / 1e6  # 대략 표본수 표시는 생략
    out = {}
    for enc, c in per.items():
        tot = c["_tot"]
        if tot < 200: continue
        out[enc] = {"casts": tot,
                    "소용돌이%": round(c["소용돌이"] / tot * 100, 1),
                    "천둥벼락%": round(c["천둥벼락"] / tot * 100, 1),
                    "마무리 일격%": round(c["마무리 일격"] / tot * 100, 1),
                    "우레 작렬%": round(c["우레 작렬"] / tot * 100, 1)}
    return out


def main():
    hero, df, pf, nm = load_common()
    result = {}

    print("=== A. 보스별 영웅특성 채택률 (전 표본) ===")
    A = part_A(df, pf, hero); result["hero_adoption"] = A
    for eid, d in sorted(A.items(), key=lambda x: -x[1]["산왕%"]):
        bar = "산왕" if d["산왕%"] >= 50 else "학살자"
        print(f'  {d["boss"][:20]:<20} 산왕 {d["산왕%"]:>3}% · 학살자 {d["학살자%"]:>3}%  (n={d["n"]}) → {bar}')

    result["mechanics"] = {}
    result["boss_profile"] = {}
    for spec, fn in [("학살자", "tmp_fury_bs_events.json"), ("산왕", "tmp_fury_thane_events.json")]:
        path = DATA / fn
        if not path.exists():
            print(f"\n[{spec}] {fn} 없음 — analyze_fury_bladestorm.py / analyze_fury_thane.py 먼저 실행")
            continue
        ev = json.load(open(path, encoding="utf-8"))
        B = part_B(ev, nm, spec); result["mechanics"][spec] = B
        print(f"\n=== B. {spec} 메커니즘 검증 (n={B['n']}) ===")
        for kk in ("피범벅_reck", "분쇄의 타격_reck", "피의 갈증_reck", "광란_reck", "칼날폭풍_정렬", "우레작렬_2충전"):
            if kk in B and B[kk][2] is not None:
                d, t, p = B[kk]; print(f'  {kk:<16} {d}/{t} = {p}% (무모한 희생 중 또는 정렬)')
        C = part_C(ev, df, nm); result["boss_profile"][spec] = C
        print(f"--- C. {spec} 보스별 회전 프로필 ---")
        for enc, d in sorted(C.items(), key=lambda x: -x[1]["casts"]):
            extra = f' 우레작렬{d["우레 작렬%"]}%' if spec == "산왕" else ""
            print(f'  {enc[:18]:<18} 소용돌이{d["소용돌이%"]:>4}% 천둥벼락{d["천둥벼락%"]:>4}% 처형{d["마무리 일격%"]:>4}%{extra} (시전{d["casts"]})')

    json.dump(result, open(DATA / "fury_priority_stats.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n저장: data/fury_priority_stats.json")


if __name__ == "__main__":
    main()
