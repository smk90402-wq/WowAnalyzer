"""BM 쿨기 딥다이브 — 크라운/르우라 오프너 홀드 전략별 DPS 비교, 살라다르 홀드 가치.

tmp_mine_bm_cd.py 의 파서 재사용. data/bm_cd_usage.json 에 deep_dive 섹션 추가.
"""
from __future__ import annotations
import json, sys, csv
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

sys.path.insert(0, r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze")
from tmp_mine_bm_cd import (DATA, SCRATCH, load_names, load_wanted, stream_filter,
                            parse_fight, pct, mmss, POT_IDS, PUZZLE)


def med(v):
    v = sorted(v); return v[len(v)//2] if v else None


def main():
    names = load_names()
    wanted = load_wanted()
    ev = stream_filter(wanted)

    # dps 매핑
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    dps_map = {}
    for r in rows:
        if r["class"] == "Hunter" and r["spec"].replace(" ", "") == "BeastMastery":
            dps_map[(r["report_id"], int(r["fight_id"]), r["character"])] = float(r["dps"])

    per = []
    for k, info in wanted.items():
        e = ev.get(k)
        if not e: continue
        f = parse_fight(info, e, names)
        if len(f["bw"]) < 2: continue
        rid, fid, _ = k.split(":")
        f["dps"] = dps_map.get((rid, int(fid), info["char"]))
        f["eid"] = info["eid"]; f["rank"] = info["rank"]
        per.append(f)

    deep = {}

    def grp_stats(fs):
        return {"n": len(fs),
                "dps_med": round(med([f["dps"] for f in fs if f["dps"]]) or 0),
                "rank_med": med([f["rank"] for f in fs]),
                "first_bw_med_s": round(med([f["bw"][0] for f in fs]), 1)}

    # ── 우주의 왕관: 즉시 오프너 vs 20초 홀드 오프너 ──
    crown = [f for f in per if f["eid"] == 3181]
    early = [f for f in crown if f["bw"][0] <= 5]
    hold = [f for f in crown if f["bw"][0] >= 15]
    mid = [f for f in crown if 5 < f["bw"][0] < 15]
    # 홀드파의 첫 상자 시각 (상자+격노 콤보 확인)
    hold_box1 = [f["box"][0] for f in hold if f["box"]]
    early_hold_arrivals = Counter()
    for f in early:
        for i in range(1, len(f["bw"])):
            if f["bw"][i] - f["bw"][i-1] > 45:
                early_hold_arrivals[int(f["bw"][i] // 30) * 30] += 1
    deep["crown_3181_opener"] = {
        "early_le5s": grp_stats(early), "hold_ge15s": grp_stats(hold),
        "mid_5_15s": {"n": len(mid)},
        "hold_first_box_med_s": round(med(hold_box1), 1) if hold_box1 else None,
        "early_group_later_hold_arrivals": [
            {"t": mmss(t), "n": c} for t, c in early_hold_arrivals.most_common(4)],
        "note": "첫 격노를 바로 쓰는 파 vs ~20초 아끼는 파의 실제 DPS 비교",
    }

    # ── 르우라: 첫 격노 분포 + 물약 페어링 + 5:30 홀드 ──
    lura = [f for f in per if f["eid"] == 3183]
    fb = sorted(f["bw"][0] for f in lura)
    pot_pair = [f["pots"][0][0] - f["bw"][0] for f in lura if f["pots"]]
    hold_len = []; hold_fights = 0; pot2_to_bw = []
    for f in lura:
        held = False
        for i in range(1, len(f["bw"])):
            g = f["bw"][i] - f["bw"][i-1]
            if g > 45 and 270 <= f["bw"][i] <= 380:
                hold_len.append(g); held = True
        if held: hold_fights += 1
        if len(f["pots"]) >= 2:
            p2 = f["pots"][1][0]
            nxt = [t for t in f["bw"] if t >= p2 - 1]
            if nxt: pot2_to_bw.append(nxt[0] - p2)
    deep["lura_3183"] = {
        "first_bw": {"min": round(fb[0], 1), "p10": round(pct(fb, .10), 1),
                     "med": round(pct(fb, .5), 1), "p90": round(pct(fb, .90), 1),
                     "max": round(fb[-1], 1)},
        "pot1_minus_bw1_med_s": round(med(pot_pair), 1) if pot_pair else None,
        "midfight_hold_fights": f"{hold_fights}/{len(lura)}",
        "midfight_hold_len_med_s": round(med(hold_len), 1) if hold_len else None,
        "pot2_to_next_bw_med_s": round(med(pot2_to_bw), 1) if pot2_to_bw else None,
        "note": "전원이 첫 격노를 ~13.7s까지 안 씀 + 물약도 같이 늦춤 — 왜인지는 전투 기믹(개막 무적/딜증 창) 확인 필요",
    }

    # ── 살라다르: 3:00/5:00 홀드 하는 파 vs 안 하는 파 ──
    sal = [f for f in per if f["eid"] == 3179]
    holders, nonholders = [], []
    for f in sal:
        held = any(f["bw"][i] - f["bw"][i-1] > 40 and f["bw"][i] >= 150
                   for i in range(1, len(f["bw"])))
        (holders if held else nonholders).append(f)
    deep["salhadaar_3179_hold"] = {
        "holders": grp_stats(holders), "nonholders": grp_stats(nonholders),
        "note": "간격>40s 홀드(2:30 이후)를 한 킬 vs 안 한 킬 — top20이 홀드를 더 함(즉시 54% vs 79%)",
    }

    # ── 아베르지안: 2:20 웨이브에 격노 모아치기 한 파 vs 안 한 파 ──
    avz = [f for f in per if f["eid"] == 3176]
    wave_hold, no_hold = [], []
    for f in avz:
        held = any(f["bw"][i] - f["bw"][i-1] > 40 and 120 <= f["bw"][i] <= 160
                   for i in range(1, len(f["bw"])))
        (wave_hold if held else no_hold).append(f)
    deep["averzian_3176_wavehold"] = {
        "hold_for_wave": grp_stats(wave_hold), "no_hold": grp_stats(no_hold),
        "note": "2:20 쫄웨이브 직전 격노 홀드 여부별 DPS — 6월 '모은 뒤 격노' 재검증",
    }

    # ── 바엘고어: 간격 밀림(med 33.4s)의 원인 — 밀린 격노가 어디서 나오나 ──
    vael = [f for f in per if f["eid"] == 3178]
    drift_arr = Counter()
    for f in vael:
        for i in range(1, len(f["bw"])):
            if 33 < f["bw"][i] - f["bw"][i-1] <= 45:
                drift_arr[int(f["bw"][i] // 30) * 30] += 1
    deep["vaelgor_3178_drift"] = {
        "drift_arrival_top": [{"t": mmss(t), "n": c} for t, c in drift_arr.most_common(8)],
        "note": "소홀드 50%가 특정 시각에 몰리는지(기믹) 고른지(다운타임) 판별",
    }

    out_path = DATA / "bm_cd_usage.json"
    out = json.load(open(out_path, encoding="utf-8"))
    out["deep_dive"] = deep
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(json.dumps(deep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
