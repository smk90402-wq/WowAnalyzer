# -*- coding: utf-8 -*-
"""무기 전사(Arms) 프록 규율 + 12.0.5 우선순위 변경 검증 채굴.

데이터: 스크래치패드 arms_cd_events.json (casts+buffs, tmp_mine_arms_cd.py 산출물 재사용).

질문:
 Q5 영웅의 일격(캐스트 1269383, 프록 버프 1269391 실측) — 프록 apply 후 다음 GCD가
    영일인지 필사(12294)인지 비율, apply→소모 지연, 낭비율.
    (실측 근거: 영일 캐스트의 100%가 1269391 removebuff ±150ms 일치, 제거의 93%가 영일 소모.
     영일은 자체 GCD 점유 — 최근접 타 로테이션 캐스트 거리 ≥0.7s 절벽.)
 Q6 급살(52살437) apply→마무리 일격(281000 학살자/163201 거신/5308) 소모 지연·낭비율
 Q7 제압(7384) — 필사 직전 GCD가 제압인 비율, 제압 직후 GCD가 필사인 비율
 Q8 처형구간 근사(전투 마지막 25% 시간) — 스킬별 분당 시전 변화, 분쇄(772) 도포 중단 여부
    (보스 HP 실측 불가 → 시간 근사임을 명시)

출력: data/arms_proc_discipline.json (커밋 금지 — 가이드 입력용)
"""
from __future__ import annotations
import json, sys, csv, bisect
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(r"C:\Users\MKSEORTV\Desktop\WowAnalyzer\data")
SCRATCH = Path(r"C:\Users\MKSEORTV\AppData\Local\Temp\claude\C--Users-MKSEORTV-Desktop-WowAnalyzer\30b0abb8-5226-4b13-9c1c-14e4a1562211\scratchpad")

SPEC_KEY, CSV_SPEC = "Warrior/Arms", "Arms"
CACHE_NAME, OUT_NAME = "arms_cd_events.json", "arms_proc_discipline.json"

# ── 실측 확정 ID ────────────────────────────────────────────────
HS = 1269383             # 영웅의 일격 캐스트
HS_PROC = 1269391        # 영웅의 일격 프록 버프(전쟁의 지배자) — 실측 매칭 100%
MS = 12294               # 필사의 일격
OP = 7384                # 제압
SUDDEN_DEATH = 52437     # 급살 프록 버프
EXECUTES = (281000, 163201, 5308)  # 마무리 일격 (281000 학살자 / 163201 거신)
REND, SLAM, CSMASH = 772, 1464, 167105
CLEAVE, DEMOLISH = 845, 436358
# 다음/직전 GCD 판정용 주력 로테이션 캐스트
GCD_SET = {MS, OP, HS, SLAM, REND, CSMASH, CLEAVE, DEMOLISH,
           281000, 163201, 5308, 446035, 107570, 260708, 228920, 6343, 384110}

CONSUME_MS = 150
EXEC_WINDOW_FRAC = 0.25  # 전투 마지막 25% 시간 = 처형구간 근사
BOSS_KO = {3176: "아베르지안", 3177: "보라시우스", 3178: "바엘고어&에조라크",
           3179: "살라다르", 3180: "선봉대", 3181: "우주의 왕관",
           3182: "벨로렌", 3183: "한밤의 도래(르우라)", 3306: "카이메루스"}


def load_names():
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    return {int(k): (v.get("name_ko") or v.get("name_en") or "?")
            for k, v in db.items() if isinstance(v, dict)}


def load_wanted():
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))[SPEC_KEY]
    hero_sets = {t: set(nd["id"] for nd in h["nodes"]) for t, h in tt["hero"].items()}
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    sel = [r for r in rows if r["class"] == "Warrior" and r["spec"] == CSV_SPEC]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    wanted = {}
    for r in sel:
        rid, fid, ch = r["report_id"], int(r["fight_id"]), r["character"]
        p = pf.get(f"{rid}:{fid}:{ch}")
        if not isinstance(p, dict): continue
        sid = p.get("sourceID"); m = meta.get(rid)
        if sid is None or not m: continue
        f = next((x for x in (m.get("fights") or []) if x.get("id") == fid), None)
        if not f: continue
        key = f"{rid}:{fid}:{sid}"
        if key in wanted: continue
        hero = "불명"
        if p.get("nodes"):
            nodes = set(int(x) for x in p["nodes"])
            best = max(hero_sets, key=lambda t: len(nodes & hero_sets[t]))
            if len(nodes & hero_sets[best]) >= 8: hero = best
        wanted[key] = {"boss": r["encounter_name"], "eid": int(r["encounter_id"]),
                       "rank": int(r["rank"]), "hero": hero,
                       "t0": f["startTime"], "t1": f["endTime"]}
    return wanted


def pct(vals, q):
    if not vals: return None
    v = sorted(vals)
    return v[min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))]


def near(sorted_ts, t, win):
    i = bisect.bisect_left(sorted_ts, t)
    best = min((abs(sorted_ts[j] - t) for j in (i - 1, i) if 0 <= j < len(sorted_ts)),
               default=None)
    return best is not None and best <= win


def parse_fight(info, e):
    t0, t1 = info["t0"], info["t1"]
    dur = (t1 - t0) / 1000
    casts = sorted((c for c in e.get("casts") or [] if len(c) >= 3 and c[2] == "cast"),
                   key=lambda c: c[0])
    buffs = sorted((b for b in e.get("buffs") or [] if len(b) >= 3), key=lambda b: b[0])
    r = {"dur": dur}
    gcd_casts = [(c[0], c[1]) for c in casts if c[1] in GCD_SET]
    gcd_ts = [t for t, _ in gcd_casts]

    # ── Q5 영일 프록 (1269391): apply→다음 GCD 정체, 소모 지연, 낭비 ──
    hs_ts = sorted(c[0] for c in casts if c[1] == HS)
    q5 = {"gains": 0, "consumed": 0, "expired_or_lost": 0,
          "consume_delays": [], "next_gcd": Counter(), "gcds_before_consume": Counter()}
    act = None
    for b in buffs:
        if b[1] != HS_PROC: continue
        ts, typ = b[0], b[2]
        if typ in ("applybuff", "refreshbuff"):
            if typ == "refreshbuff" and act is not None:
                q5["expired_or_lost"] += 1  # 프록 중첩 덮어쓰기
            q5["gains"] += 1
            act = ts
            # 다음 GCD 정체 (apply 이후 첫 로테이션 캐스트, 6s 내)
            i = bisect.bisect_right(gcd_ts, ts)
            if i < len(gcd_casts) and gcd_casts[i][0] - ts <= 6000:
                q5["next_gcd"][gcd_casts[i][1]] += 1
        elif typ == "removebuff":
            if act is None: continue
            hold = (ts - act) / 1000
            if near(hs_ts, ts, CONSUME_MS):
                q5["consumed"] += 1
                q5["consume_delays"].append(hold)
                nbetween = sum(1 for t in gcd_ts
                               if act < t < ts - CONSUME_MS and t not in hs_ts)
                q5["gcds_before_consume"][min(nbetween, 4)] += 1
            else:
                q5["expired_or_lost"] += 1
            act = None
    r["q5"] = q5

    # ── Q6 급살 (FIFO 충전 추적) ──
    exe_ts = sorted(c[0] for c in casts if c[1] in EXECUTES)
    sd = {"gains": 0, "refresh_overwrites": 0, "consumed": 0, "holds": [],
          "consume_delays": [], "other_removed_holds": []}
    q = []
    for b in buffs:
        if b[1] != SUDDEN_DEATH: continue
        ts, typ = b[0], b[2]
        if typ == "applybuff":
            q = [ts]; sd["gains"] += 1
        elif typ == "applybuffstack":
            q.append(ts); sd["gains"] += 1
        elif typ == "refreshbuff":
            sd["gains"] += 1; sd["refresh_overwrites"] += 1
            if q: q[-1] = ts
        elif typ in ("removebuff", "removebuffstack"):
            if not q: continue
            gained = q.pop(0)
            hold = (ts - gained) / 1000
            sd["holds"].append(hold)
            if near(exe_ts, ts, CONSUME_MS):
                sd["consumed"] += 1; sd["consume_delays"].append(hold)
            else:
                sd["other_removed_holds"].append(hold)
            if typ == "removebuff": q = []
    r["sd"] = sd

    # ── Q7 제압↔필사 교차 ──
    ms_ts = sorted(c[0] for c in casts if c[1] == MS)
    op_ts = sorted(c[0] for c in casts if c[1] == OP)
    q7 = {"ms_n": len(ms_ts), "op_n": len(op_ts),
          "ms_prev_op": 0, "ms_prev_any": 0, "op_next_ms": 0, "op_next_any": 0,
          "ms_prev_top": Counter()}
    for t in ms_ts:
        i = bisect.bisect_left(gcd_ts, t)
        for j in range(i - 1, -1, -1):
            pt, pid = gcd_casts[j]
            if pt >= t: continue
            if t - pt > 4000: break
            q7["ms_prev_any"] += 1
            q7["ms_prev_top"][pid] += 1
            if pid == OP: q7["ms_prev_op"] += 1
            break
    for t in op_ts:
        i = bisect.bisect_right(gcd_ts, t)
        while i < len(gcd_casts) and gcd_casts[i][0] == t: i += 1
        if i < len(gcd_casts) and gcd_casts[i][0] - t <= 4000:
            q7["op_next_any"] += 1
            if gcd_casts[i][1] == MS: q7["op_next_ms"] += 1
    r["q7"] = q7

    # ── Q8 처형구간 근사 (마지막 25% 시간 vs 앞 75%) ──
    cut = t1 - (t1 - t0) * EXEC_WINDOW_FRAC
    early, late = Counter(), Counter()
    for c in casts:
        if c[1] in (MS, OP, HS, SLAM, REND, CSMASH, *EXECUTES):
            (late if c[0] >= cut else early)[c[1]] += 1
    last_rend = max((c[0] for c in casts if c[1] == REND), default=None)
    r["q8"] = {"early": early, "late": late,
               "early_s": dur * (1 - EXEC_WINDOW_FRAC), "late_s": dur * EXEC_WINDOW_FRAC,
               "last_rend_frac": (last_rend - t0) / (t1 - t0) if last_rend else None}
    return r


def seg_summary(fs):
    if not fs: return None
    n = len(fs)
    tot_min = sum(f["dur"] for f in fs) / 60
    d = {"n": n}
    # Q5
    gains = sum(f["q5"]["gains"] for f in fs)
    consumed = sum(f["q5"]["consumed"] for f in fs)
    lost = sum(f["q5"]["expired_or_lost"] for f in fs)
    delays = sorted(x for f in fs for x in f["q5"]["consume_delays"])
    nxt = Counter(); gbc = Counter()
    for f in fs:
        nxt.update(f["q5"]["next_gcd"]); gbc.update(f["q5"]["gcds_before_consume"])
    nxt_tot = sum(nxt.values())
    d["q5_heroic_strike_proc"] = {
        "gains": gains, "gains_per_min": round(gains / tot_min, 2),
        "consumed_pct": round(100 * consumed / gains, 1) if gains else None,
        "wasted_pct": round(100 * lost / gains, 1) if gains else None,
        "consume_delay_s_med": round(pct(delays, .5), 2) if delays else None,
        "consume_delay_s_p75": round(pct(delays, .75), 2) if delays else None,
        "consume_within_2s_pct": round(100 * sum(1 for x in delays if x <= 2) / len(delays), 1) if delays else None,
        "next_gcd_total": nxt_tot,
        "next_gcd_hs_pct": round(100 * nxt[HS] / nxt_tot, 1) if nxt_tot else None,
        "next_gcd_ms_pct": round(100 * nxt[MS] / nxt_tot, 1) if nxt_tot else None,
        "next_gcd_top6": nxt.most_common(6),
        "gcds_before_consume": {str(k): v for k, v in sorted(gbc.items())},
    }
    # Q6
    sg = sum(f["sd"]["gains"] for f in fs)
    sc = sum(f["sd"]["consumed"] for f in fs)
    ow = sum(f["sd"]["refresh_overwrites"] for f in fs)
    sdel = sorted(x for f in fs for x in f["sd"]["consume_delays"])
    holds = sorted(x for f in fs for x in f["sd"]["holds"])
    other = [x for f in fs for x in f["sd"]["other_removed_holds"]]
    thr = round((pct(holds, .995) or 12) - 0.3, 1)
    expired = sum(1 for x in other if x >= thr)
    d["q6_sudden_death"] = {
        "gains": sg, "gains_per_min": round(sg / tot_min, 2),
        "consumed": sc, "consumed_pct": round(100 * sc / sg, 1) if sg else None,
        "consume_delay_s_med": round(pct(sdel, .5), 2) if sdel else None,
        "consume_within_3s_pct": round(100 * sum(1 for x in sdel if x <= 3) / len(sdel), 1) if sdel else None,
        "refresh_overwrites": ow, "expired": expired, "expiry_threshold_s": thr,
        "waste_pct": round(100 * (ow + expired) / sg, 1) if sg else None,
    }
    # Q7
    ms_prev_any = sum(f["q7"]["ms_prev_any"] for f in fs)
    ms_prev_op = sum(f["q7"]["ms_prev_op"] for f in fs)
    op_next_any = sum(f["q7"]["op_next_any"] for f in fs)
    op_next_ms = sum(f["q7"]["op_next_ms"] for f in fs)
    mtop = Counter()
    for f in fs: mtop.update(f["q7"]["ms_prev_top"])
    d["q7_overpower_weave"] = {
        "ms_casts": sum(f["q7"]["ms_n"] for f in fs),
        "op_casts": sum(f["q7"]["op_n"] for f in fs),
        "ms_prev_gcd_is_op_pct": round(100 * ms_prev_op / ms_prev_any, 1) if ms_prev_any else None,
        "op_next_gcd_is_ms_pct": round(100 * op_next_ms / op_next_any, 1) if op_next_any else None,
        "ms_prev_gcd_top5": mtop.most_common(5),
    }
    # Q8
    e_s = sum(f["q8"]["early_s"] for f in fs)
    l_s = sum(f["q8"]["late_s"] for f in fs)
    ec, lc = Counter(), Counter()
    for f in fs: ec.update(f["q8"]["early"]); lc.update(f["q8"]["late"])
    exe_ids = set(EXECUTES)
    def cpm(c, t, ids): return round(sum(v for k, v in c.items() if k in ids) / (t / 60), 2)
    lr = sorted(x for f in fs if (x := f["q8"]["last_rend_frac"]) is not None)
    d["q8_execute_window_last25pct_time"] = {
        "note": "보스 HP 실측 불가 → 전투 마지막 25% '시간' 근사. 학살자 급살 프록 처형은 전 구간 발생 유의.",
        "cpm_early_vs_late": {
            "mortal_strike": [cpm(ec, e_s, {MS}), cpm(lc, l_s, {MS})],
            "execute": [cpm(ec, e_s, exe_ids), cpm(lc, l_s, exe_ids)],
            "overpower": [cpm(ec, e_s, {OP}), cpm(lc, l_s, {OP})],
            "heroic_strike": [cpm(ec, e_s, {HS}), cpm(lc, l_s, {HS})],
            "slam": [cpm(ec, e_s, {SLAM}), cpm(lc, l_s, {SLAM})],
            "rend": [cpm(ec, e_s, {REND}), cpm(lc, l_s, {REND})],
            "colossus_smash": [cpm(ec, e_s, {CSMASH}), cpm(lc, l_s, {CSMASH})],
        },
        "last_rend_at_fight_frac_med": round(pct(lr, .5), 3) if lr else None,
        "last_rend_at_fight_frac_p75": round(pct(lr, .75), 3) if lr else None,
        "rend_stopped_before_75pct_share": round(100 * sum(1 for x in lr if x <= 0.75) / len(lr), 1) if lr else None,
    }
    return d


def main():
    names = load_names()
    wanted = load_wanted()
    ev = json.load(open(SCRATCH / CACHE_NAME, encoding="utf-8"))
    per = []
    for k, info in wanted.items():
        e = ev.get(k)
        if not e or not e.get("buffs"): continue
        per.append((info, parse_fight(info, e)))
    hc = Counter(i["hero"] for i, _ in per)
    print(f"분석 킬: {len(per)} · 영웅트리 {dict(hc)}", flush=True)

    def name_tops(seg):
        if not seg: return seg
        seg["q5_heroic_strike_proc"]["next_gcd_top6"] = [
            {"id": sid, "name": names.get(sid, "?"), "n": n}
            for sid, n in seg["q5_heroic_strike_proc"]["next_gcd_top6"]]
        seg["q7_overpower_weave"]["ms_prev_gcd_top5"] = [
            {"id": sid, "name": names.get(sid, "?"), "n": n}
            for sid, n in seg["q7_overpower_weave"]["ms_prev_gcd_top5"]]
        return seg

    out = {"meta": {
        "date": "2026-07-11", "spec": SPEC_KEY, "n_kills": len(per),
        "hero_adoption": dict(hc),
        "ids": {
            "heroic_strike_cast": HS, "heroic_strike_proc_buff": HS_PROC,
            "mortal_strike": MS, "overpower": OP,
            "sudden_death_buff": SUDDEN_DEATH, "execute_casts": list(EXECUTES),
            "rend": REND, "slam": SLAM, "colossus_smash": CSMASH,
        },
        "evidence": ("HS_PROC=1269391 확정 근거: 영일 캐스트 8847건 중 8825건(99.8%)이 "
                     "1269391 removebuff ±150ms 일치, 제거 9519건 중 8825건(92.7%)이 영일 소모. "
                     "영일은 자체 GCD 점유(최근접 타 캐스트 ≥0.7s). "
                     "next_gcd 비율은 프록 활성 조건만 통제(분노량·다른 프록 미통제) — 빈도이지 단정 아님."),
    }, "segments": {}, "per_boss": {}}

    out["segments"]["all"] = name_tops(seg_summary([f for _, f in per]))
    out["segments"]["rank_1_20"] = name_tops(seg_summary([f for i, f in per if i["rank"] <= 20]))
    out["segments"]["rank_21_100"] = name_tops(seg_summary([f for i, f in per if i["rank"] > 20]))
    for hero in sorted(set(i["hero"] for i, _ in per)):
        if hero == "불명": continue
        out["segments"][f"hero_{hero}"] = name_tops(
            seg_summary([f for i, f in per if i["hero"] == hero]))

    bosses = defaultdict(list)
    for i, f in per: bosses[(i["eid"], i["boss"])].append(f)
    for (eid, bname), fs in sorted(bosses.items()):
        out["per_boss"][BOSS_KO.get(eid, bname)] = name_tops(seg_summary(fs))

    json.dump(out, open(DATA / OUT_NAME, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"저장: data/{OUT_NAME}", flush=True)

    for label, s in out["segments"].items():
        if not s: continue
        q5, q6, q7, q8 = (s["q5_heroic_strike_proc"], s["q6_sudden_death"],
                          s["q7_overpower_weave"], s["q8_execute_window_last25pct_time"])
        print(f"\n[{label}] n={s['n']}")
        print(f"  Q5 영일프록 {q5['gains_per_min']}/min 소모 {q5['consumed_pct']}% 낭비 {q5['wasted_pct']}% "
              f"지연 med {q5['consume_delay_s_med']}s (2s내 {q5['consume_within_2s_pct']}%)")
        print(f"     프록 후 다음 GCD: 영일 {q5['next_gcd_hs_pct']}% vs 필사 {q5['next_gcd_ms_pct']}% "
              f"top {[(x['name'], x['n']) for x in q5['next_gcd_top6'][:4]]}")
        print(f"     소모 전 끼운 GCD 수 분포: {q5['gcds_before_consume']}")
        print(f"  Q6 급살 {q6['gains_per_min']}/min 소모 {q6['consumed_pct']}% 지연 med {q6['consume_delay_s_med']}s "
              f"(3s내 {q6['consume_within_3s_pct']}%) 낭비 {q6['waste_pct']}% (덮{q6['refresh_overwrites']}/만료{q6['expired']})")
        print(f"  Q7 필사 직전=제압 {q7['ms_prev_gcd_is_op_pct']}% · 제압 직후=필사 {q7['op_next_gcd_is_ms_pct']}% "
              f"(필사 {q7['ms_casts']}회) 필사 직전 top {[(x['name'], x['n']) for x in q7['ms_prev_gcd_top5'][:4]]}")
        c = q8["cpm_early_vs_late"]
        print(f"  Q8 [앞75%→뒤25% 분당] 필사 {c['mortal_strike']} 마무리 {c['execute']} 제압 {c['overpower']} "
              f"영일 {c['heroic_strike']} 격돌 {c['slam']} 분쇄 {c['rend']}")
        print(f"     분쇄 마지막 시전 시점 med {q8['last_rend_at_fight_frac_med']} (75% 이전 중단 {q8['rend_stopped_before_75pct_share']}%)")


if __name__ == "__main__":
    main()
