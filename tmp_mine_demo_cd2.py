"""데모 쿨기 딥다이브 — 크라운 오프너 홀드 전략별 DPS 비교, 벨로렌 4:30 홀드 표본 점검.

tmp_mine_demo_cd.py 의 파서 재사용. data/demo_cd_usage.json 에 deep_dive 섹션 추가.
"""
from __future__ import annotations
import json, sys, csv
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

sys.path.insert(0, r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze")
from tmp_mine_demo_cd import (DATA, SCRATCH, load_names, load_wanted, stream_filter,
                              parse_fight, pct, mmss)


def med(v):
    v = [x for x in v if x is not None]
    v = sorted(v); return v[len(v)//2] if v else None


def main():
    names = load_names()
    wanted = load_wanted()
    ev = stream_filter(wanted)

    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    dps_map = {}
    for r in rows:
        if r["class"] == "Warlock" and r["spec"] == "Demonology":
            dps_map[(r["report_id"], int(r["fight_id"]), r["character"])] = float(r["dps"])

    per = []
    for k, info in wanted.items():
        e = ev.get(k)
        if not e: continue
        f = parse_fight(info, e, names)
        if len(f["tyrant"]) < 2: continue
        rid, fid, _ = k.split(":")
        f["dps"] = dps_map.get((rid, int(fid), info["char"]))
        f["eid"] = info["eid"]; f["rank"] = info["rank"]
        per.append(f)

    deep = {}

    def grp_stats(fs):
        return {"n": len(fs),
                "dps_med": round(med([f["dps"] for f in fs if f["dps"]]) or 0),
                "rank_med": med([f["rank"] for f in fs]),
                "dur_med_s": round(med([f["dur"] for f in fs]), 1) if fs else None,
                "first_tyrant_med_s": round(med([f["tyrant"][0] for f in fs]), 1) if fs else None}

    # ── 우주의 왕관: 즉시 오프너(<=8s) vs ~22s 홀드 오프너 ──
    crown = [f for f in per if f["eid"] == 3181]
    early = [f for f in crown if f["tyrant"][0] <= 8]
    hold = [f for f in crown if f["tyrant"][0] >= 15]
    mid = [f for f in crown if 8 < f["tyrant"][0] < 15]
    firsts = sorted(f["tyrant"][0] for f in crown)
    early_hold_arrivals = Counter()
    for f in early:
        for i in range(1, len(f["tyrant"])):
            if f["tyrant"][i] - f["tyrant"][i-1] > 45:
                early_hold_arrivals[int(f["tyrant"][i] // 30) * 30] += 1
    deep["crown_3181_opener"] = {
        "n_total": len(crown),
        "first_tyrant_dist_s": [round(x, 1) for x in firsts],
        "early_le8s": grp_stats(early), "hold_ge15s": grp_stats(hold),
        "mid_8_15s": {"n": len(mid)},
        "early_group_later_hold_arrivals": [
            {"t": mmss(t), "n": c} for t, c in early_hold_arrivals.most_common(4)],
        "note": "76%(26/34)가 첫 폭군을 17~26s로 홀드(대부분 22~24s 클러스터), 18%(6/34)만 8s 이내 즉시 사용. "
                "DPS는 홀드파 144090 vs 즉시파 145683으로 거의 동일(표본 6 vs 26, 지속시간도 달라 직접비교 주의) — "
                "BM 야수 격노 분석과 동일하게 크라운 특유의 ~20s 지점 기믹 정렬로 추정되나 기믹 자체는 미확인.",
    }

    # ── 벨로렌: 4:30 부근 홀드 표본 점검 (소수파 여부 확인) ──
    bel = [f for f in per if f["eid"] == 3182]
    bel_hold_fights = []
    for f in bel:
        held = False
        for i in range(1, len(f["tyrant"])):
            g = f["tyrant"][i] - f["tyrant"][i-1]
            if g > 75 and 250 <= f["tyrant"][i] <= 290:
                held = True
        if held: bel_hold_fights.append(f)
    deep["belren_3182_430_hold"] = {
        "n_total": len(bel),
        "hold_fights": len(bel_hold_fights),
        "hold_pct": round(100 * len(bel_hold_fights) / len(bel)) if bel else None,
        "note": f"4:30 부근 대홀드는 {len(bel_hold_fights)}/{len(bel)}킬({round(100*len(bel_hold_fights)/len(bel))}%)만 겪음 — "
                "소수파라 대표 패턴으로 단정 못 함. 미해결(표본부족).",
    }

    # ── 르우라: 폭군 오프너가 매우 빠름(med 2.8s) — BM(격노 13.7s 홀드)과 반대 패턴 기록만 ──
    lura = [f for f in per if f["eid"] == 3183]
    fb = sorted(f["tyrant"][0] for f in lura)
    deep["lura_3183_opener"] = {
        "n": len(lura),
        "first_tyrant": {"min": round(fb[0], 1), "p10": round(pct(fb, .10), 1),
                          "med": round(pct(fb, .5), 1), "p90": round(pct(fb, .90), 1),
                          "max": round(fb[-1], 1)},
        "note": "97%가 5s 이내 즉시 폭군 사용 — BM(야수 격노는 전원 13.7s까지 홀드)과 정반대 패턴. "
                "미해결: 데모 폭군은 60s 짧은 쿨이라 홀드 손실이 더 크기 때문인지, 스펙별 오프닝 셋업 차이인지 로그만으론 판정 불가.",
    }

    out_path = DATA / "demo_cd_usage.json"
    out = json.load(open(out_path, encoding="utf-8"))
    out["deep_dive"] = deep
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(json.dumps(deep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
