"""네임드별 스탯 분포 추출 — top1~20 개별 + 21~100 평균.

사용자 통찰: 같은 전문화도 광특(AoE 빌드)/단일특 스탯이 다름.
  예) 야수 광빌드=치명 42%, 단일빌드=가속 27% (실측 확인).

player_fight 캐시의 stats(특화/치명/가속/유연 + ilvl) 사용.
- top 20: 개별 행 (순위·DPS·빌드·각 스탯)
- 21~100: 빌드별 평균 (광/단일 분리)
출력: data/boss_stats.json. 사냥꾼 3스펙 먼저 (SPEC_BUILD 확장으로 타직업).
"""
from __future__ import annotations
import sys, json
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data"
TOP_INDIVIDUAL = 20   # 1~20등 개별
STAT_KEYS = [("Mastery", "특화"), ("Crit", "치명"), ("Haste", "가속"), ("Versatility", "유연")]

# 빌드 분기 노드 (광빌드 마커). None이면 빌드 구분 없음.
SPEC_BUILD = {
    ("Hunter", "Beast Mastery"): (102341, "광", "단일"),   # 회전베기(마구잡이 난타)
    ("Hunter", "Marksmanship"): (None, None, None),
    ("Hunter", "Survival"): (None, None, None),
    ("Shaman", "Elemental"): (None, None, None),           # 정기 — 빌드 구분 없이 전체
    ("Warlock", "Demonology"): (None, None, None),         # 악마
    ("Mage", "Frost"): (None, None, None),                 # 냉법
    ("Warrior", "Arms"): (None, None, None),               # 무기
    ("Warrior", "Fury"): (None, None, None),               # 분노
}


def load():
    df = pd.read_csv(DATA / "rankings_zone46_mythic_dps_top100.csv")
    df["fid"] = df["fight_id"].astype(int)
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    return df, pf


def get_stats(pf, r):
    p = pf.get(f'{r["report_id"]}:{int(r["fid"])}:{r["character"]}')
    if not isinstance(p, dict) or not p.get("stats"):
        return None
    s = p["stats"]
    return {
        "nodes": set(p.get("nodes") or []),
        "ilvl": s.get("Item Level"),
        "stats": {kr: s.get(en) for en, kr in STAT_KEYS},
        # 장비창은 클릭 시 /api/character 로 조회 (한글명·아이콘·마부·보석 enrichment 재사용)
        "ref": {"rid": r["report_id"], "fid": int(r["fid"]), "char": r["character"]},
    }


def pct(stats):
    """4스탯 비중% (특화/치명/가속/유연 합 기준)."""
    tot = sum(v for v in stats.values() if v) or 1
    return {k: round(v / tot * 100) if v else 0 for k, v in stats.items()}


def analyze(df, pf, cls, spec):
    node, aoe_lbl, st_lbl = SPEC_BUILD.get((cls, spec), (None, None, None))
    sub = df[(df["class"] == cls) & (df["spec"] == spec)]
    out = {}
    for eid, g in sub.groupby("encounter_id"):
        g = g.sort_values("rank")
        top, rest = [], []
        for _, r in g.iterrows():
            st = get_stats(pf, r)
            if not st:
                continue
            is_aoe = (node in st["nodes"]) if node else None
            row = {
                "rank": int(r["rank"]), "dps": int(r["dps"]), "ilvl": st["ilvl"],
                "char": st["ref"]["char"],
                "build": (aoe_lbl if is_aoe else st_lbl) if node else None,
                "is_aoe": is_aoe,
                "stats": st["stats"], "pct": pct(st["stats"]),
                "ref": st["ref"],   # 장비창 조회용 (rid/fid/char)
            }
            if r["rank"] <= TOP_INDIVIDUAL:
                top.append(row)
            else:
                rest.append(row)
        if len(top) + len(rest) < 5:
            continue
        out[int(eid)] = {
            "boss_kr": g.iloc[0]["encounter_name"],
            "top": top,
            "top_avg": _avg_block(top, node, aoe_lbl, st_lbl),   # 1~20등 평균 (사용자 요청)
            "rest_avg": _avg_block(rest, node, aoe_lbl, st_lbl),  # 21~100등 평균
            "has_build": node is not None,
        }
    return out


def _avg_block(rows, node, aoe_lbl, st_lbl):
    """21~100 평균 — 빌드 있으면 광/단일 분리, 없으면 전체."""
    if not rows:
        return None
    def block(rs, label):
        if not rs:
            return None
        med = {kr: round(float(np.median([r["stats"][kr] for r in rs if r["stats"][kr] is not None] or [0])))
               for _, kr in STAT_KEYS}
        return {"label": label, "n": len(rs), "stats": med, "pct": pct(med),
                "ilvl": round(float(np.median([r["ilvl"] for r in rs if r["ilvl"]] or [0])))}
    if node:
        return [b for b in (
            block([r for r in rows if r["is_aoe"]], aoe_lbl),
            block([r for r in rows if not r["is_aoe"]], st_lbl),
        ) if b]
    return [block(rows, "전체")]


def main():
    df, pf = load()
    result = {}
    for (cls, spec) in SPEC_BUILD:
        data = analyze(df, pf, cls, spec)
        if data:
            result[f"{cls}|{spec}"] = data
            print(f"{cls} {spec}: {len(data)}개 보스")
            for eid, d in data.items():
                avgs = d["rest_avg"] or []
                astr = " | ".join(f"{b['label']}{b['n']}명" for b in avgs)
                print(f"  {d['boss_kr'][:16]:<16} top{len(d['top'])} + 평균[{astr}]")
    json.dump(result, open(DATA / "boss_stats.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n저장: boss_stats.json ({len(result)} 스펙)")


if __name__ == "__main__":
    main()
