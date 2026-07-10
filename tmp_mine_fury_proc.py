# -*- coding: utf-8 -*-
"""분노 전사(Fury) 프록 규율 + 우선순위 시퀀스 실측 채굴.

데이터: 스크래치패드 fury_cd_events.json (v2_cache_events.json에서 추출된 casts+buffs,
        tmp_mine_fury_cd.py stream_filter 산출물 재사용).

질문:
 Q1 격노(184362, 버프 실측) 업타임 %, 격노 끊김→다음 광란(184367) 지연
 Q2 급살(52437, 버프 실측) apply→소모(마무리 일격 280735/5308) 지연·낭비율
 Q3 광란 시전 간격 분포 + 광란 직전 GCD top5 + 광란 시점 격노 상태
 Q4 무모한 희생(버프 1719) 창 안/밖 필러 구성 (피의 갈증23881/피범벅335096,
    분노의 강타85288/분쇄의 타격335097 — Reckless Abandon 변신 실측)

출력: data/fury_proc_discipline.json (커밋 금지 — 가이드 입력용)
"""
from __future__ import annotations
import json, sys, csv, bisect
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(r"C:\Users\MKSEORTV\Desktop\WowAnalyzer\data")
SCRATCH = Path(r"C:\Users\MKSEORTV\AppData\Local\Temp\claude\C--Users-MKSEORTV-Desktop-WowAnalyzer\30b0abb8-5226-4b13-9c1c-14e4a1562211\scratchpad")

SPEC_KEY, CSV_SPEC = "Warrior/Fury", "Fury"
CACHE_NAME, OUT_NAME = "fury_cd_events.json", "fury_proc_discipline.json"

# ── 실측 확정 ID (survey_warr.py 관측) ──────────────────────────
ENRAGE = 184362          # 격노 버프 (전 킬 관측)
RAMPAGE = 184367         # 광란 캐스트
SUDDEN_DEATH = 52437     # 급살 프록 버프 (분노도 52437 — 무기와 동일 ID 실측)
EXECUTES = (280735, 5308)  # 마무리 일격 캐스트 (280735 주력, 5308 일부 킬)
RECK_BUFF = 1719         # 무모한 희생 버프=캐스트 동일 ID
BT, BB = 23881, 335096   # 피의 갈증 / 피범벅
RB, CB = 85288, 335097   # 분노의 강타 / 분쇄의 타격
# 직전 GCD 후보(주력 로테이션 캐스트만; 오딘 보조이벤트 385060/61/62 제외)
GCD_SET = {23881, 335096, 85288, 335097, 280735, 5308, 184367, 446035,
           435222, 6343, 190411, 385059, 107570, 384110}

CONSUME_MS = 150
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


def buff_intervals(buffs, sid, t0, t1):
    """apply/refresh→remove 구간 (초, 전투 내 클립). refresh는 구간 연장으로 취급."""
    iv, act = [], None
    for b in buffs:
        if b[1] != sid: continue
        ts, typ = b[0], b[2]
        if typ == "applybuff":
            if act is None: act = ts
        elif typ == "removebuff":
            if act is not None:
                iv.append((max(act, t0), min(ts, t1))); act = None
    if act is not None: iv.append((max(act, t0), t1))
    iv = [(a, b) for a, b in iv if b > a]
    # 0~200ms 내 재적용(remove+apply 리프레시 인코딩)은 연속 구간으로 병합
    merged = []
    for a, b in iv:
        if merged and a - merged[-1][1] <= 200: merged[-1][1] = max(merged[-1][1], b)
        else: merged.append([a, b])
    return [(a, b) for a, b in merged]


def near(sorted_ts, t, win):
    i = bisect.bisect_left(sorted_ts, t)
    best = min((abs(sorted_ts[j] - t) for j in (i - 1, i) if 0 <= j < len(sorted_ts)),
               default=None)
    return best is not None and best <= win


def in_windows(wins, t):
    return any(a <= t <= b for a, b in wins)


def parse_fight(info, e):
    t0, t1 = info["t0"], info["t1"]
    dur = (t1 - t0) / 1000
    casts = sorted((c for c in e.get("casts") or [] if len(c) >= 3 and c[2] == "cast"),
                   key=lambda c: c[0])
    buffs = sorted((b for b in e.get("buffs") or [] if len(b) >= 3), key=lambda b: b[0])
    r = {"dur": dur}

    # ── Q1 격노 업타임 + 끊김→광란 지연 ──
    en_iv = buff_intervals(buffs, ENRAGE, t0, t1)
    r["enrage_uptime_pct"] = 100 * sum(b - a for a, b in en_iv) / (t1 - t0) if t1 > t0 else 0
    ramp_ts = sorted(c[0] for c in casts if c[1] == RAMPAGE)
    gaps, regain = [], []
    for i in range(len(en_iv) - 1):
        drop, nxt = en_iv[i][1], en_iv[i + 1][0]
        gaps.append((nxt - drop) / 1000)
        j = bisect.bisect_left(ramp_ts, drop)
        if j < len(ramp_ts) and ramp_ts[j] <= t1:
            regain.append((ramp_ts[j] - drop) / 1000)
    r["enrage_gaps_s"] = gaps
    r["drop_to_rampage_s"] = regain

    # ── Q2 급살 (FIFO 충전 추적) ──
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
            if q: q[-1] = ts  # 최신 충전 갱신으로 근사
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

    # ── Q3 광란 간격 + 직전 GCD + 시전 시점 격노 상태 ──
    r["ramp_intervals"] = [(ramp_ts[i + 1] - ramp_ts[i]) / 1000 for i in range(len(ramp_ts) - 1)]
    gcd_casts = [(c[0], c[1]) for c in casts if c[1] in GCD_SET]
    prev = Counter()
    for t in ramp_ts:
        i = bisect.bisect_left(gcd_casts, (t, -1))
        for j in range(i - 1, -1, -1):
            pt, pid = gcd_casts[j]
            if pt >= t: continue
            if t - pt > 3000: break
            if pid == RAMPAGE and pt == t: continue
            prev[pid] += 1
            break
    r["ramp_prev"] = prev
    r["ramp_n"] = len(ramp_ts)
    # 광란 자체가 시전 순간 격노를 부여하므로 100ms 이전 시점의 격노 상태로 판정
    r["ramp_enraged"] = sum(1 for t in ramp_ts if in_windows(en_iv, t - 100))

    # ── Q4 무희 창 안/밖 필러 ──
    reck_iv = buff_intervals(buffs, RECK_BUFF, t0, t1)
    if not reck_iv:
        reck_iv = [(t, min(t + 12000, t1)) for t in
                   sorted(c[0] for c in casts if c[1] == RECK_BUFF)]
    in_s = sum(b - a for a, b in reck_iv) / 1000
    r["reck_in_s"], r["reck_out_s"] = in_s, max(dur - in_s, 0.001)
    cnt_in, cnt_out = Counter(), Counter()
    for c in casts:
        if c[1] in (BT, BB, RB, CB, RAMPAGE, *EXECUTES):
            (cnt_in if in_windows(reck_iv, c[0]) else cnt_out)[c[1]] += 1
    r["fill_in"], r["fill_out"] = cnt_in, cnt_out
    return r


def seg_summary(fs):
    if not fs: return None
    n = len(fs)
    d = {"n": n}
    # Q1
    up = sorted(f["enrage_uptime_pct"] for f in fs)
    gaps = sorted(g for f in fs for g in f["enrage_gaps_s"])
    reg = sorted(g for f in fs for g in f["drop_to_rampage_s"])
    d["q1_enrage"] = {
        "uptime_pct_med": round(pct(up, .5), 1), "uptime_pct_p25": round(pct(up, .25), 1),
        "uptime_pct_p75": round(pct(up, .75), 1),
        "gaps_per_min": round(len(gaps) / (sum(f["dur"] for f in fs) / 60), 2),
        "gap_s_med": round(pct(gaps, .5), 2) if gaps else None,
        "drop_to_rampage_s_med": round(pct(reg, .5), 2) if reg else None,
        "drop_to_rampage_s_p75": round(pct(reg, .75), 2) if reg else None,
        "n_gaps": len(gaps),
    }
    # Q2
    gains = sum(f["sd"]["gains"] for f in fs)
    consumed = sum(f["sd"]["consumed"] for f in fs)
    ow = sum(f["sd"]["refresh_overwrites"] for f in fs)
    delays = sorted(x for f in fs for x in f["sd"]["consume_delays"])
    holds = sorted(x for f in fs for x in f["sd"]["holds"])
    other = [x for f in fs for x in f["sd"]["other_removed_holds"]]
    expiry_thr = round((pct(holds, .995) or 12) - 0.3, 1)
    expired = sum(1 for x in other if x >= expiry_thr)
    d["q2_sudden_death"] = {
        "gains": gains, "gains_per_min": round(gains / (sum(f["dur"] for f in fs) / 60), 2),
        "consumed": consumed, "consumed_pct": round(100 * consumed / gains, 1) if gains else None,
        "consume_delay_s_med": round(pct(delays, .5), 2) if delays else None,
        "consume_delay_s_p75": round(pct(delays, .75), 2) if delays else None,
        "consume_within_3s_pct": round(100 * sum(1 for x in delays if x <= 3) / len(delays), 1) if delays else None,
        "refresh_overwrites": ow, "expired": expired,
        "expiry_threshold_s": expiry_thr,
        "waste_pct": round(100 * (ow + expired) / gains, 1) if gains else None,
    }
    # Q3
    iv = sorted(x for f in fs for x in f["ramp_intervals"])
    prev = Counter()
    for f in fs: prev.update(f["ramp_prev"])
    ramp_n = sum(f["ramp_n"] for f in fs)
    enr = sum(f["ramp_enraged"] for f in fs)
    d["q3_rampage"] = {
        "casts": ramp_n,
        "interval_s_med": round(pct(iv, .5), 2) if iv else None,
        "interval_s_p25": round(pct(iv, .25), 2) if iv else None,
        "interval_s_p75": round(pct(iv, .75), 2) if iv else None,
        "share_le_3s_pct": round(100 * sum(1 for x in iv if x <= 3) / len(iv), 1) if iv else None,
        "share_3_6s_pct": round(100 * sum(1 for x in iv if 3 < x <= 6) / len(iv), 1) if iv else None,
        "share_gt_8s_pct": round(100 * sum(1 for x in iv if x > 8) / len(iv), 1) if iv else None,
        "cast_while_enraged_pct": round(100 * enr / ramp_n, 1) if ramp_n else None,
        "prev_gcd_top5": prev.most_common(5),
    }
    # Q4
    in_s = sum(f["reck_in_s"] for f in fs)
    out_s = sum(f["reck_out_s"] for f in fs)
    ci, co = Counter(), Counter()
    for f in fs: ci.update(f["fill_in"]); co.update(f["fill_out"])
    def cpm(c, t): return {str(k): round(v / (t / 60), 2) for k, v in sorted(c.items())}
    bb_in = 100 * ci[BB] / max(1, ci[BT] + ci[BB])
    bb_out = 100 * co[BB] / max(1, co[BT] + co[BB])
    cb_in = 100 * ci[CB] / max(1, ci[RB] + ci[CB])
    cb_out = 100 * co[CB] / max(1, co[RB] + co[CB])
    d["q4_reck_window"] = {
        "window_s_total": round(in_s), "window_share_pct": round(100 * in_s / (in_s + out_s), 1),
        "cpm_in": cpm(ci, in_s), "cpm_out": cpm(co, out_s),
        "bloodbath_share_of_bt_in_pct": round(bb_in, 1),
        "bloodbath_share_of_bt_out_pct": round(bb_out, 1),
        "crushing_share_of_rb_in_pct": round(cb_in, 1),
        "crushing_share_of_rb_out_pct": round(cb_out, 1),
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

    def name_prev(seg):
        if seg:
            seg["q3_rampage"]["prev_gcd_top5"] = [
                {"id": sid, "name": names.get(sid, "?"), "n": n}
                for sid, n in seg["q3_rampage"]["prev_gcd_top5"]]
        return seg

    out = {"meta": {
        "date": "2026-07-11", "spec": SPEC_KEY, "n_kills": len(per),
        "hero_adoption": dict(hc),
        "ids": {
            "enrage_buff": ENRAGE, "rampage_cast": RAMPAGE,
            "sudden_death_buff": SUDDEN_DEATH, "execute_casts": list(EXECUTES),
            "recklessness_buff": RECK_BUFF,
            "bloodthirst": BT, "bloodbath": BB, "raging_blow": RB, "crushing_blow": CB,
        },
        "note": ("격노/무희 창은 buff apply→remove 실측. 급살 소모=제거 ±0.15s 내 마무리 일격 캐스트. "
                 "직전 GCD 최빈은 조건(분노량·프록 유무) 통제가 없으므로 빈도이지 우선순위 단정 아님."),
    }, "segments": {}, "per_boss": {}}

    fs_all = [f for _, f in per]
    out["segments"]["all"] = name_prev(seg_summary(fs_all))
    out["segments"]["rank_1_20"] = name_prev(seg_summary([f for i, f in per if i["rank"] <= 20]))
    out["segments"]["rank_21_100"] = name_prev(seg_summary([f for i, f in per if i["rank"] > 20]))
    for hero in sorted(set(i["hero"] for i, _ in per)):
        out["segments"][f"hero_{hero}"] = name_prev(
            seg_summary([f for i, f in per if i["hero"] == hero]))

    bosses = defaultdict(list)
    for i, f in per: bosses[(i["eid"], i["boss"])].append(f)
    for (eid, bname), fs in sorted(bosses.items()):
        out["per_boss"][BOSS_KO.get(eid, bname)] = name_prev(seg_summary(fs))

    json.dump(out, open(DATA / OUT_NAME, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"저장: data/{OUT_NAME}", flush=True)

    for label, s in out["segments"].items():
        if not s: continue
        q1, q2, q3, q4 = s["q1_enrage"], s["q2_sudden_death"], s["q3_rampage"], s["q4_reck_window"]
        print(f"\n[{label}] n={s['n']}")
        print(f"  Q1 격노 업타임 med {q1['uptime_pct_med']}% (p25 {q1['uptime_pct_p25']} p75 {q1['uptime_pct_p75']}) "
              f"· 끊김 {q1['gaps_per_min']}/min gap med {q1['gap_s_med']}s → 광란 med {q1['drop_to_rampage_s_med']}s")
        print(f"  Q2 급살 {q2['gains_per_min']}/min 소모 {q2['consumed_pct']}% 지연 med {q2['consume_delay_s_med']}s "
              f"(3s내 {q2['consume_within_3s_pct']}%) 낭비 {q2['waste_pct']}% (덮{q2['refresh_overwrites']}/만료{q2['expired']}, 문턱{q2['expiry_threshold_s']}s)")
        print(f"  Q3 광란 간격 med {q3['interval_s_med']}s (≤3s {q3['share_le_3s_pct']}% >8s {q3['share_gt_8s_pct']}%) "
              f"격노중 시전 {q3['cast_while_enraged_pct']}% 직전GCD {[(p['name'], p['n']) for p in q3['prev_gcd_top5']]}")
        print(f"  Q4 무희창 {q4['window_share_pct']}% · 피범벅 비중 in {q4['bloodbath_share_of_bt_in_pct']}% out {q4['bloodbath_share_of_bt_out_pct']}% "
              f"· 분쇄타격 비중 in {q4['crushing_share_of_rb_in_pct']}% out {q4['crushing_share_of_rb_out_pct']}%")


if __name__ == "__main__":
    main()
