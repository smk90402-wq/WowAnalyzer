"""BM 교대 규율 실측 — 살상 명령 연속 시전(back-to-back) 빈도, 필러 분포,
날카로운 사격 충전 관리, 살상 명령 공백 시간.

파싱 패턴은 analyze_bm_addwave.py / tmp_mine_frost_cd.py 를 따름
(v2_cache_events.json 1.4GB → raw_decode 증분 스캔, 스크래치패드에 추출 캐시).
대상: 오늘자 rankings CSV(2026-07-03)에 있는 BM 킬만.

출력: data/bm_alternation.json
"""
from __future__ import annotations
import json, sys, csv, os
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze\data")
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")
SCRATCH.mkdir(parents=True, exist_ok=True)

KC = 34026        # 살상 명령
BARB = 217200     # 날카로운 사격
COBRA = 193455    # 코브라 사격
WT_IDS = {1264359, 1264355}   # 마구잡이 난타 (광 필러)
BW = 19574        # 야수의 격노
COTW = 359844     # 야생의 부름
FRENZY = 272790   # 광기 (펫 버프, 잡히면 사용)
BARB_PBUFF = 246152

NODE_ALPHA = 102368   # 우두머리 포식자: 살상 명령 2회 충전

BOSS_KO = {3176: "아베르지안", 3177: "보라시우스", 3178: "바엘고어", 3179: "살라다르",
           3180: "선봉대", 3181: "우주의왕관", 3182: "벨로렌", 3183: "한밤의도래(르우라)",
           3306: "카이메루스"}


def load_wanted():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    bm = [r for r in rows if r["class"] == "Hunter" and r["spec"].replace(" ", "") == "BeastMastery"]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    wanted = {}
    for r in bm:
        rid, fid, ch = r["report_id"], int(r["fight_id"]), r["character"]
        p = pf.get(f"{rid}:{fid}:{ch}")
        if not isinstance(p, dict): continue
        sid = p.get("sourceID")
        m = meta.get(rid)
        if sid is None or not m: continue
        f = next((x for x in (m.get("fights") or []) if x.get("id") == fid), None)
        if not f: continue
        key = f"{rid}:{fid}:{sid}"
        if key in wanted: continue
        wanted[key] = {
            "boss_id": int(r["encounter_id"]), "boss": BOSS_KO.get(int(r["encounter_id"]), r["encounter_name"]),
            "rank": int(r["rank"]), "char": ch,
            "t0": f["startTime"], "t1": f["endTime"],
            "alpha": NODE_ALPHA in set(p.get("nodes") or []),
        }
    return wanted


def stream_filter(wanted):
    cache = SCRATCH / "bm_alt_events.json"
    if cache.exists():
        return json.load(open(cache, encoding="utf-8"))
    s = open(DATA / "v2_cache_events.json", encoding="utf-8").read()
    print(f"events 캐시 {len(s)/1e6:.0f}MB 스캔...", flush=True)
    dec = json.JSONDecoder()
    out, i, n, seen = {}, 1, len(s), 0
    while i < n:
        while i < n and s[i] in " \t\r\n,": i += 1
        if i >= n or s[i] == "}": break
        key, j = dec.raw_decode(s, i); i = j
        while s[i] in " \t\r\n:": i += 1
        val, j = dec.raw_decode(s, i); i = j
        seen += 1
        if seen % 2000 == 0: print(f"  스캔 {seen}, 적중 {len(out)}", flush=True)
        if key in wanted:
            casts = [[c[0], c[1]] for c in (val.get("casts") or []) if len(c) >= 3 and c[2] == "cast"]
            buffs = [b for b in (val.get("buffs") or []) if len(b) >= 3 and b[1] in (FRENZY, BARB_PBUFF)]
            out[key] = {"casts": casts, "buffs": buffs}
    json.dump(out, open(cache, "w", encoding="utf-8"))
    print(f"추출 {len(out)}/{len(wanted)}", flush=True)
    return out


def pct(vals, q):
    if not vals: return None
    v = sorted(vals)
    idx = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return round(v[idx], 2)


def detect_offgcd(fights):
    """캐스트 간격이 짧은(=글쿨 안 먹는) 스킬을 실측으로 분류."""
    dt_by_id = defaultdict(list)
    for casts in fights:
        for i in range(1, len(casts)):
            dt = (casts[i][0] - casts[i-1][0]) / 1000
            dt_by_id[casts[i][1]].append(dt)
    off = set()
    stats = {}
    for sid, dts in dt_by_id.items():
        if len(dts) < 50: continue
        short = sum(1 for d in dts if d < 0.6) / len(dts)
        stats[sid] = (len(dts), round(short, 2))
        if short > 0.5:
            off.add(sid)
    return off, stats


def analyze_fight(casts, t0, t1, offgcd):
    seq = sorted((t, i) for t, i in casts if t >= t0 - 1000)
    gseq = [(t, i) for t, i in seq if i not in offgcd]
    dur = (t1 - t0) / 1000
    r = {"dur": dur, "kc_n": 0, "trans": 0, "b2b": 0, "b2b_rapid": 0, "b2b_gaps": [],
         "filler": Counter(), "first_after": Counter(),
         "barb_gaps": [], "kc_gaps": [], "barb_n": 0, "cobra_n": 0,
         "bf_pairs": 0, "bf_barb_first": 0}
    kc_idx = [k for k, (t, i) in enumerate(gseq) if i == KC]
    r["kc_n"] = len(kc_idx)
    for a, b in zip(kc_idx, kc_idx[1:]):
        r["trans"] += 1
        between = [gseq[k][1] for k in range(a + 1, b)]
        gap = (gseq[b][0] - gseq[a][0]) / 1000
        r["kc_gaps"].append(gap)
        if not between:
            r["b2b"] += 1
            r["b2b_gaps"].append(gap)
            if gap <= 2.5: r["b2b_rapid"] += 1
        else:
            for i in between: r["filler"][i] += 1
            # 날카/코브라 둘 다 있으면 어느 쪽이 먼저?
            has_b = BARB in between
            has_c = COBRA in between
            if has_b and has_c:
                r["bf_pairs"] += 1
                if between.index(BARB) < between.index(COBRA):
                    r["bf_barb_first"] += 1
        if between:
            r["first_after"][between[0]] += 1
    barb_ts = [t for t, i in gseq if i == BARB]
    r["barb_n"] = len(barb_ts)
    r["cobra_n"] = sum(1 for _, i in gseq if i == COBRA)
    r["barb_gaps"] = [(b - a) / 1000 for a, b in zip(barb_ts, barb_ts[1:])]
    return r


def agg(items):
    """items: (info, r) 리스트 → 집계."""
    if not items: return None
    trans = sum(r["trans"] for _, r in items)
    b2b = sum(r["b2b"] for _, r in items)
    rapid = sum(r["b2b_rapid"] for _, r in items)
    tot_min = sum(r["dur"] for _, r in items) / 60
    kc_gaps = sorted(g for _, r in items for g in r["kc_gaps"])
    barb_gaps = sorted(g for _, r in items for g in r["barb_gaps"])
    filler = Counter()
    first = Counter()
    for _, r in items:
        filler.update(r["filler"]); first.update(r["first_after"])
    # 살명 공백 추정: 판마다 쿨 추정치(짧은 간격 p25) 대비 초과분 합
    idle_pm, cds = [], []
    for _, r in items:
        gs = [g for g in r["kc_gaps"] if 1.5 <= g <= 15]
        if len(gs) < 8: continue
        cd = pct(gs, 0.25)
        cds.append(cd)
        idle = sum(max(0.0, g - cd) for g in r["kc_gaps"])
        idle_pm.append(idle / (r["dur"] / 60))
    bf_pairs = sum(r["bf_pairs"] for _, r in items)
    bf_bfirst = sum(r["bf_barb_first"] for _, r in items)
    per_fight_viol = sorted(100 * r["b2b"] / r["trans"] for _, r in items if r["trans"] >= 10)
    return {
        "n_fights": len(items),
        "kc": {
            "casts_per_min": round(sum(r["kc_n"] for _, r in items) / tot_min, 2),
            "b2b_pct": round(100 * b2b / trans, 2) if trans else None,
            "b2b_rapid_pct": round(100 * rapid / trans, 2) if trans else None,
            "b2b_count": b2b, "transitions": trans,
            "per_fight_b2b_pct_median": pct(per_fight_viol, 0.5),
            "per_fight_b2b_pct_p90": pct(per_fight_viol, 0.9),
            "fights_with_zero_b2b_pct": round(100 * sum(1 for v in per_fight_viol if v == 0) / len(per_fight_viol), 1) if per_fight_viol else None,
            "gap_median_s": pct(kc_gaps, 0.5), "gap_p90_s": pct(kc_gaps, 0.9),
            "cd_est_median_s": pct(sorted(c for c in cds if c is not None), 0.5),
            "idle_s_per_min_median": pct(idle_pm, 0.5), "idle_s_per_min_p75": pct(idle_pm, 0.75),
        },
        "filler_share_pct": {},
        "first_after_kc_pct": {},
        "_filler_raw": filler, "_first_raw": first,
        "barbed": {
            "casts_per_min": round(sum(r["barb_n"] for _, r in items) / tot_min, 2),
            "gap_median_s": pct(barb_gaps, 0.5), "gap_p75_s": pct(barb_gaps, 0.75),
            "gap_p90_s": pct(barb_gaps, 0.9),
            "gaps_gt_8s_pct": round(100 * sum(1 for g in barb_gaps if g > 8) / len(barb_gaps), 1) if barb_gaps else None,
            "gaps_gt_12s_pct": round(100 * sum(1 for g in barb_gaps if g > 12) / len(barb_gaps), 1) if barb_gaps else None,
            "n_gaps": len(barb_gaps),
        },
        "cobra_per_min": round(sum(r["cobra_n"] for _, r in items) / tot_min, 2),
        "barbed_first_when_both_pct": round(100 * bf_bfirst / bf_pairs, 1) if bf_pairs else None,
        "bf_pairs": bf_pairs,
    }


def name_of(sid, db):
    v = db.get(str(sid))
    return (v or {}).get("name_ko") or f"spell{sid}"


def fill_shares(block, db):
    if not block: return
    for key_raw, key_out in (("_filler_raw", "filler_share_pct"), ("_first_raw", "first_after_kc_pct")):
        c = block.pop(key_raw)
        tot = sum(c.values())
        if not tot: continue
        top = {}
        for sid, n in c.most_common(14):
            top[f"{name_of(sid, db)}({sid})"] = round(100 * n / tot, 2)
        block[key_out] = top


def main():
    wanted = load_wanted()
    print(f"BM player-fights wanted: {len(wanted)}", flush=True)
    ev = stream_filter(wanted)
    print(f"events 적중: {len(ev)}/{len(wanted)}", flush=True)
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))

    # 버프 캐스트에 광기(펫버프)가 잡히는지 확인
    frenzy_seen = sum(1 for e in ev.values() for b in e.get("buffs", []) if b[1] == FRENZY)
    print(f"광기(272790) 버프 이벤트 관측: {frenzy_seen}", flush=True)

    usable = [(k, wanted[k]) for k in ev if len(ev[k].get("casts") or []) >= 30]
    offgcd, offstats = detect_offgcd([ev[k]["casts"] for k, _ in usable])
    off_named = {sid: name_of(sid, db) for sid in sorted(offgcd)}
    print(f"실측 오프글쿨 분류({len(offgcd)}): {off_named}", flush=True)

    per = []
    for k, info in usable:
        r = analyze_fight(ev[k]["casts"], info["t0"], info["t1"], offgcd)
        if r["kc_n"] >= 10:
            per.append((info, r))
    print(f"분석 대상 킬: {len(per)}", flush=True)

    def band(i): return "rank_1_20" if i["rank"] <= 20 else "rank_21_100"

    out = {"meta": {
        "collected": "2026-07-03 rankings CSV 교집합",
        "n_kills": len(per),
        "bands": {b: sum(1 for i, _ in per if band(i) == b) for b in ("rank_1_20", "rank_21_100")},
        "alpha_predator_node": NODE_ALPHA,
        "n_alpha": sum(1 for i, _ in per if i["alpha"]),
        "spells": {"kill_command": KC, "barbed_shot": BARB, "cobra_shot": COBRA, "wild_thrash": sorted(WT_IDS)},
        "offgcd_detected": off_named,
        "note": "b2b = 살상 명령 다음 글쿨 스킬이 또 살상 명령(사이에 아무것도 안 누름). "
                "rapid = 그중 간격 2.5초 이하(진짜 연타). idle = 판별 살명 쿨 추정치(간격 p25) 초과 공백 합(추정치).",
    }, "overall": {}, "by_alpha_predator": {}, "per_boss": {}}

    for b in ("rank_1_20", "rank_21_100"):
        a = agg([(i, r) for i, r in per if band(i) == b]); fill_shares(a, db)
        out["overall"][b] = a
    a = agg(per); fill_shares(a, db)
    out["overall"]["all"] = a

    for flag, lab in ((True, "with_alpha_2charge"), (False, "without_alpha")):
        a = agg([(i, r) for i, r in per if i["alpha"] == flag]); fill_shares(a, db)
        out["by_alpha_predator"][lab] = a

    bosses = defaultdict(list)
    for i, r in per: bosses[i["boss"]].append((i, r))
    for boss, lst in sorted(bosses.items(), key=lambda x: -len(x[1])):
        d = {}
        for b in ("all", "rank_1_20", "rank_21_100"):
            sub = lst if b == "all" else [(i, r) for i, r in lst if band(i) == b]
            a = agg(sub); fill_shares(a, db)
            d[b] = a
        out["per_boss"][boss] = d

    json.dump(out, open(DATA / "bm_alternation.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("저장: data/bm_alternation.json", flush=True)

    # 콘솔 요약
    for b in ("rank_1_20", "rank_21_100"):
        s = out["overall"][b]
        if not s: continue
        print(f"\n[{b}] n={s['n_fights']}")
        k = s["kc"]
        print(f"  살명 {k['casts_per_min']}/분, 연속시전 {k['b2b_pct']}% (연타 {k['b2b_rapid_pct']}%), "
              f"무위반 판 {k['fights_with_zero_b2b_pct']}%, 공백 {k['idle_s_per_min_median']}s/분")
        print(f"  필러: {list(s['filler_share_pct'].items())[:6]}")
        bb = s["barbed"]
        print(f"  날카 간격 중앙 {bb['gap_median_s']}s p90 {bb['gap_p90_s']}s, 8s초과 {bb['gaps_gt_8s_pct']}%, "
              f"둘 다 있을 때 날카 먼저 {s['barbed_first_when_both_pct']}%")


if __name__ == "__main__":
    main()
