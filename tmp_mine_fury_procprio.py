# -*- coding: utf-8 -*-
"""
분노 전사(Fury) 프록 상태별 조건부 우선순위 + 쿨기 드리프트 실측 — 양 영웅특성 분리.
방법론: tmp_mine_arms_procprio.py / tmp_mine_arms_drift.py 와 동일.
입력: 스크래치패드 fury_cd_events.json (top100 296킬 casts/buffs) — 읽기 전용.
출력: data/fury_procprio.json

영웅특성 분류(실측 100% 상호배타):
  학살자 = 칼날폭풍 446035 시전 존재 (155킬)
  산왕   = 우레 작렬 435222 시전 존재 (141킬)

상태 태깅 (각 GCD 시전 직전, t-1ms 기준):
  enr  = 격노 184362 활성
  sd   = 급살 52437 활성
  btr  = 피의 갈증 준비 근사: 마지막 '수동' 피갈/피범벅 후 경과 >= 킬별 추정 쿨
         (깨끗한 간격 p25, 2400~4600ms 클램프 — 쿨 4.5초가 가속 적용이라 실측 중앙 ~3.1초).
         산왕은 폭발적인 힘 437121 활성 시 쿨 무시 → btr=True 강제.
  reck = 무모한 희생 1719 실측 버프 창 안 (applybuff→removebuff, 실측 지속 ~18초)
  phase: exec = 전투 시간 마지막 25% (대학살 35% HP의 시간 근사)

자동시전 오염 제거(학살자):
  불안정한 정신(386628)이 칼날폭풍 채널 중 피의 갈증(23881)/피범벅(335096)을
  자동 시전. 격렬한 희열 버프(1270731)가 칼폭 '종료 시점'에 정확히 적용되므로
  [칼폭 시전, 1270731 적용 +100ms] 창 안의 피갈/피범벅 = 자동으로 확정 제외.
  (채널 실측 중앙 2.49초, 최대 2.9초. 994회 중 4회만 종료 마커 없음 → +3000ms 폴백)
  오딘의 격노 385060/385061/385062 = 385059와 동일 타임스탬프 하위 이벤트 → 제외.
  피범벅/분쇄의 타격은 무희 창 안에서만 발생(실측 100%/미검증이면 표기) — 버튼 변신.
"""
import json
import os
import statistics
from collections import Counter, defaultdict

SCRATCH = r"C:\Users\MKSEORTV\AppData\Local\Temp\claude\C--Users-MKSEORTV-Desktop-WowAnalyzer\30b0abb8-5226-4b13-9c1c-14e4a1562211\scratchpad\fury_cd_events.json"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fury_procprio.json")

RAMPAGE = 184367
BT = 23881
BLOODBATH = 335096
RB = 85288
CRUSHING = 335097
EXEC1, EXEC2 = 280735, 5308
TC = 6343
TB_CAST = 435222
WW = 190411
BS = 446035
AVATAR = 107574
ODYN = 385059
RECK_CAST = 1719

BUTTONS = {
    RAMPAGE: "rampage", BT: "bt", BLOODBATH: "bloodbath",
    RB: "rb", CRUSHING: "crushing_blow",
    EXEC1: "execute", EXEC2: "execute",
    TC: "thunder_clap", TB_CAST: "thunder_blast", WW: "whirlwind",
    BS: "bladestorm", AVATAR: "avatar", ODYN: "odyns_fury",
    RECK_CAST: "recklessness",
}
# 오딘의 격노 하위 이벤트(385059와 동일 ms) + 비순환/이동/유틸 — 분포에서 제외
EXCLUDE = {385060, 385061, 385062,
           6552, 23920, 355, 100, 126664, 97462, 118038, 52174, 57755,
           6673, 202168, 20572, 12323, 384110, 2565, 107570, 3411, 64382,
           1236994, 1236616, 1234768, 386208, 12975, 871, 190456}

ENRAGE = 184362
SD_BUFF = 52437
RECK_BUFF = 1719
BP_BUFF = 437121      # 폭발적인 힘(산왕) — 피갈 쿨 미발동
FE_BUFF = 1270731     # 격렬한 희열(학살자) — 칼폭 종료 마커
TB_BUFF = 435615      # 우레 작렬 충전(산왕, 최대 2중첩)

GCD_MS = 1500
FLAT_THR = 4500
TIME_BINS = [("0-30s", 0, 30), ("30-120s", 30, 120), ("120s+", 120, float("inf"))]


# ---------------- 공용 유틸 ----------------

def build_intervals(buffs, buff_id, t0):
    iv, start = [], None
    for b in buffs:
        if b[1] != buff_id:
            continue
        t, typ = b[0], b[2]
        if typ == "applybuff":
            if start is None:
                start = t
        elif typ == "removebuff":
            if start is None:
                start = t0
            iv.append((start, t))
            start = None
        elif typ in ("refreshbuff", "applybuffstack", "removebuffstack") and start is None:
            start = t0
    if start is not None:
        iv.append((start, float("inf")))
    return iv


def active_at(iv, t):
    return any(a <= t <= b for a, b in iv)


def pack(counter):
    n = sum(counter.values())
    if n == 0:
        return {"n": 0}
    out = {"n": n}
    for btn, c in counter.most_common():
        out[btn] = {"count": c, "pct": round(100.0 * c / n, 1)}
    return out


def summ(vals):
    if not vals:
        return None
    return {
        "n": len(vals),
        "mean": round(statistics.mean(vals), 2),
        "median": round(statistics.median(vals), 2),
        "p25": round(statistics.quantiles(vals, n=4)[0], 2) if len(vals) >= 4 else None,
        "p75": round(statistics.quantiles(vals, n=4)[2], 2) if len(vals) >= 4 else None,
    }


def dist(vals, bins):
    out = {label: 0 for label, _, _ in bins}
    for v in vals:
        for label, lo, hi in bins:
            if lo <= v < hi:
                out[label] += 1
                break
    return out


def tbin(t):
    for label, lo, hi in TIME_BINS:
        if lo <= t < hi:
            return label


def last_before(times, t):
    prev = None
    for x in times:
        if x <= t:
            prev = x
        else:
            break
    return prev


def bs_channel_windows(casts, buffs):
    """[칼폭 시전, 격렬한 희열 적용 +100ms] — 불안정한 정신 자동 피갈 창."""
    bs_t = [c[0] for c in casts if c[1] == BS]
    fe = [b[0] for b in buffs if b[1] == FE_BUFF and b[2] in ("applybuff", "refreshbuff")]
    wins, miss = [], 0
    for b in bs_t:
        end = next((t for t in fe if t >= b and t - b <= 8000), None)
        if end is None:
            miss += 1
            end = b + 3000  # 종료 마커 없음(전투 종료 절단) — 채널 최대 2.9초 폴백
        wins.append((b, end + 100))
    return wins, miss


# ---------------- 상태별 우선순위 ----------------

def run_prio(kills, hero, mode):
    """mode: 'adaptive'(킬별 p25 쿨 추정) | 'flat'(4.5초 고정)."""
    bins = defaultdict(Counter)          # (enr, sd, btr, reck, phase) -> Counter
    other_ids = Counter()
    thr_used = []
    drop_first = Counter()               # 격노 끊긴 뒤 첫 버튼
    drop_delay = []                      # 격노 끊김 -> 광란 지연
    auto_removed = 0
    channel_durs = []
    miss_total = 0

    for kill, v in kills.items():
        casts = sorted(v["casts"], key=lambda c: c[0])
        buffs = sorted(v["buffs"], key=lambda b: b[0])
        if not casts:
            continue
        t0 = min(casts[0][0], buffs[0][0] if buffs else casts[0][0])
        t1 = casts[-1][0]
        exec_start = t0 + 0.75 * (t1 - t0)

        enr_iv = build_intervals(buffs, ENRAGE, t0)
        sd_iv = build_intervals(buffs, SD_BUFF, t0)
        reck_iv = build_intervals(buffs, RECK_BUFF, t0)
        bp_iv = build_intervals(buffs, BP_BUFF, t0) if hero == "thane" else []

        if hero == "slayer":
            wins, miss = bs_channel_windows(casts, buffs)
            miss_total += miss
            channel_durs += [e - 100 - a for a, e in wins]
        else:
            wins = []

        def is_auto_bt(t):
            return any(a <= t <= e for a, e in wins)

        manual_bt = [c[0] for c in casts if c[1] in (BT, BLOODBATH) and not is_auto_bt(c[0])]
        if mode == "adaptive":
            gaps = [b - a for a, b in zip(manual_bt, manual_bt[1:]) if 1500 <= b - a <= 9000]
            if len(gaps) >= 8:
                gaps.sort()
                thr = min(max(gaps[len(gaps) // 4], 2400), 4600)
            else:
                thr = 3200
        else:
            thr = FLAT_THR
        thr_used.append(thr)

        # 격노 끊김 -> 첫 버튼
        drops = [b[0] for b in buffs if b[1] == ENRAGE and b[2] == "removebuff"]
        gcd_casts = [c for c in casts if c[1] not in EXCLUDE and not
                     (c[1] in (BT, BLOODBATH) and is_auto_bt(c[0]))]
        for dt_ in drops:
            nxt = next((c for c in gcd_casts if c[0] > dt_), None)
            if nxt is None:
                continue
            # 끊긴 즉시 다시 붙는 경우(같은 ms 재적용)는 다음 apply가 nxt 이전이면 스킵
            reapply = next((b[0] for b in buffs if b[1] == ENRAGE and b[2] == "applybuff" and b[0] >= dt_), None)
            if reapply is not None and reapply < nxt[0]:
                continue
            drop_first[BUTTONS.get(nxt[1], "other")] += 1
            ramp = next((c[0] for c in gcd_casts if c[0] > dt_ and c[1] == RAMPAGE), None)
            if ramp is not None:
                drop_delay.append(ramp - dt_)

        last_bt = None
        for c in casts:
            t, sid = c[0], c[1]
            if sid in EXCLUDE:
                continue
            if sid in (BT, BLOODBATH) and is_auto_bt(t):
                auto_removed += 1
                continue  # 불안정한 정신 자동 시전 — 버튼 입력 아님
            btn = BUTTONS.get(sid, "other")
            if btn == "other":
                other_ids[sid] += 1
            eps = t - 1
            enr = active_at(enr_iv, eps)
            sd = active_at(sd_iv, eps)
            btr = (last_bt is None or (t - last_bt) >= thr)
            if hero == "thane" and not btr and active_at(bp_iv, eps):
                btr = True  # 폭발적인 힘 — 쿨 미발동
            reck = active_at(reck_iv, eps)
            phase = "exec" if t >= exec_start else "normal"
            bins[(enr, sd, btr, reck, phase)][btn] += 1
            if sid in (BT, BLOODBATH):
                last_bt = t

    return {
        "bins": bins, "other_ids": other_ids, "thr_used": thr_used,
        "drop_first": drop_first, "drop_delay": drop_delay,
        "auto_removed": auto_removed, "channel_durs": channel_durs,
        "channel_end_marker_missing": miss_total,
    }


def merge_bins(bins, enr=None, sd=None, btr=None, reck=None, phase=None):
    c = Counter()
    for (e, s, b, r, ph), cnt in bins.items():
        if enr is not None and e != enr:
            continue
        if sd is not None and s != sd:
            continue
        if btr is not None and b != btr:
            continue
        if reck is not None and r != reck:
            continue
        if phase is not None and ph != phase:
            continue
        c += cnt
    return c


def prio_views(r, hero):
    b = r["bins"]
    dd = sorted(r["drop_delay"])
    views = {
        "Q1_not_enraged": {
            "설명": "격노 OFF 상태에서 누른 다음 버튼 분포 — '비격노면 광란' 룰의 실측 강도. 분노량 미관측: 광란(분노 80)이 안 나간 GCD는 분노 부족일 수 있음.",
            "all": pack(merge_bins(b, enr=False)),
            "normal": pack(merge_bins(b, enr=False, phase="normal")),
            "exec": pack(merge_bins(b, enr=False, phase="exec")),
            "first_button_after_enrage_drop": pack(r["drop_first"]),
            "drop_to_rampage_ms": {
                "n": len(dd),
                "med": statistics.median(dd) if dd else None,
                "p75": dd[3 * len(dd) // 4] if dd else None,
                "within_1gcd_pct": round(100.0 * sum(1 for x in dd if x <= GCD_MS) / len(dd), 1) if dd else None,
            },
        },
        "Q2_sd_on": {
            "설명": "급살 프록 활성 상태의 다음 버튼 — 마무리 일격 비율. exec 구간은 대학살로 상시 사용 가능하니 normal이 프록 반응의 순수 지표.",
            "all": pack(merge_bins(b, sd=True)),
            "normal": pack(merge_bins(b, sd=True, phase="normal")),
            "exec": pack(merge_bins(b, sd=True, phase="exec")),
        },
        "Q2b_sdX_btrO": {
            "설명": "급살 X · 피의 갈증 준비 O(근사) — 피갈(무희 중 피범벅) 비율.",
            "all": pack(merge_bins(b, sd=False, btr=True)),
            "normal": pack(merge_bins(b, sd=False, btr=True, phase="normal")),
            "exec": pack(merge_bins(b, sd=False, btr=True, phase="exec")),
        },
        "Q3_all_off": {
            "설명": "격노 O · 급살 X · 피갈 쿨 X — 필러 선택. " + (
                "학살자: 분노의 강타 vs 소용돌이." if hero == "slayer"
                else "산왕: 천둥벼락/우레 작렬 vs 분노의 강타 — '천둥벼락>분강' 이론 판정."),
            "all": pack(merge_bins(b, enr=True, sd=False, btr=False)),
            "normal": pack(merge_bins(b, enr=True, sd=False, btr=False, phase="normal")),
            "exec": pack(merge_bins(b, enr=True, sd=False, btr=False, phase="exec")),
            "out_of_reck": pack(merge_bins(b, enr=True, sd=False, btr=False, reck=False)),
            "in_reck": pack(merge_bins(b, enr=True, sd=False, btr=False, reck=True)),
        },
        "Q4_reck_window": {
            "설명": "무모한 희생 실측 버프 창(~18초) 안/밖 전체 버튼 분포 — 창 안 피범벅/분쇄의 타격/칼폭 비중.",
            "in_reck": pack(merge_bins(b, reck=True)),
            "out_of_reck": pack(merge_bins(b, reck=False)),
        },
    }
    return views


# ---------------- 드리프트 ----------------

def kill_times(v):
    casts = sorted(v["casts"], key=lambda c: c[0])
    t0 = casts[0][0]

    def rel(sid):
        return [(c[0] - t0) / 1000.0 for c in casts if c[1] == sid]
    buffs = sorted(v["buffs"], key=lambda b: b[0])
    reck_iv = [((a - t0) / 1000.0, (b - t0) / 1000.0 if b != float("inf") else float("inf"))
               for a, b in build_intervals(buffs, RECK_BUFF, t0)]
    return t0, rel, buffs, reck_iv, (casts[-1][0] - t0) / 1000.0


def reck_baseline(kills):
    """무희 시전 주기 + 실측 버프 창의 전투시간 점유율 — 정렬률의 우연 기준선."""
    gaps, up, tot = [], 0.0, 0.0
    for v in kills.values():
        casts = sorted(v["casts"], key=lambda c: c[0])
        t0, t1 = casts[0][0], casts[-1][0]
        rc = [(c[0] - t0) / 1000.0 for c in casts if c[1] == RECK_CAST]
        gaps += [b - a for a, b in zip(rc, rc[1:])]
        start = None
        for b in sorted(v["buffs"], key=lambda x: x[0]):
            if b[1] != RECK_BUFF:
                continue
            if b[2] == "applybuff":
                start = b[0]
            elif b[2] == "removebuff" and start is not None:
                up += min(b[0], t1) - start
                start = None
        if start is not None:
            up += max(0, t1 - start)
        tot += t1 - t0
    return {"cast_gap_s": summ(gaps),
            "buff_time_share": round(up / tot, 3) if tot else None,
            "설명": "buff_time_share = 무희 창이 전투시간에서 차지하는 비율 — 어떤 쿨기의 '무희 창 안 %'가 이 값 근처면 우연(정렬 안 함), 크게 높으면 의도적 정렬."}


def hold_analysis(pairs, thr):
    hold = {"n": 0, "in_reck": 0}
    norm = {"n": 0, "in_reck": 0}
    hgaps = []
    for gap, in_reck in pairs:
        tgt = hold if gap >= thr else norm
        tgt["n"] += 1
        tgt["in_reck"] += in_reck
        if gap >= thr:
            hgaps.append(gap)
    for tgt in (hold, norm):
        tgt["in_reck_rate"] = round(tgt["in_reck"] / tgt["n"], 3) if tgt["n"] else None
    return {"threshold_s": thr, "holds_n": hold["n"],
            "holds_share": round(hold["n"] / len(pairs), 3) if pairs else None,
            "hold_gap_summary": summ(hgaps),
            "hold_end_in_reck": hold, "normal_end_in_reck": norm}


def drift_slayer(kills):
    res = {"reck_baseline": reck_baseline(kills)}
    bs_total = 0
    in_reck_n = 0
    by_bin = {label: {"n": 0, "in_reck": 0} for label, _, _ in TIME_BINS}
    solo_since_reck = []
    pairs = []
    all_gaps = []
    odyn_total = 0
    odyn_in_reck = 0
    odyn_gaps = []
    odyn_by_bin = {label: {"n": 0, "in_reck": 0} for label, _, _ in TIME_BINS}
    for v in kills.values():
        t0, rel, buffs, reck_iv, dur = kill_times(v)
        bs = rel(BS)
        reck_c = rel(RECK_CAST)
        od = rel(ODYN)
        for t in bs:
            bs_total += 1
            inr = active_at(reck_iv, t)
            in_reck_n += inr
            bb = by_bin[tbin(t)]
            bb["n"] += 1
            bb["in_reck"] += inr
            if not inr:
                prev = last_before(reck_c, t)
                solo_since_reck.append(None if prev is None else t - prev)
        for a, b in zip(bs, bs[1:]):
            gap = b - a
            all_gaps.append(gap)
            pairs.append((gap, active_at(reck_iv, b)))
        for t in od:
            odyn_total += 1
            inr = active_at(reck_iv, t)
            odyn_in_reck += inr
            ob = odyn_by_bin[tbin(t)]
            ob["n"] += 1
            ob["in_reck"] += inr
        odyn_gaps += [b - a for a, b in zip(od, od[1:])]
    for d in (by_bin, odyn_by_bin):
        for label, bb in d.items():
            bb["in_reck_rate"] = round(bb["in_reck"] / bb["n"], 3) if bb["n"] else None
    have_s = [x for x in solo_since_reck if x is not None]
    res["bs_vs_reck"] = {
        "n_bs_casts": bs_total,
        "in_reck_realbuff_n": in_reck_n,
        "in_reck_realbuff_rate": round(in_reck_n / bs_total, 3) if bs_total else None,
        "by_fight_time": by_bin,
        "solo_elapsed_since_reck_cast_dist": dist(have_s, [
            ("18-25s", 18, 25), ("25-35s", 25, 35), ("35-50s", 35, 50),
            ("50-70s", 50, 70), ("70s+", 70, float("inf")), ("0-18s(창 계산 밖)", 0, 18)]),
        "solo_no_prior_reck": len(solo_since_reck) - len(have_s),
        "solo_elapsed_summary": summ(have_s),
    }
    res["bs_holds"] = {
        "n_bs_intervals": len(all_gaps),
        "gap_summary": summ(all_gaps),
        "gap_histogram": dist(all_gaps, [
            ("<30s", 0, 30), ("30-40s", 30, 40), ("40-50s", 40, 50),
            ("50-60s", 50, 60), ("60-75s", 60, 75), ("75-100s", 75, 100),
            ("100s+", 100, float("inf"))]),
        "설명": "칼폭 실효 쿨은 붉은돌격대의 무자비함(급살 사용마다 -5초) 때문에 가변 — 임계값은 데이터 분포 기준.",
    }
    med = statistics.median(all_gaps) if all_gaps else 0
    res["bs_holds"]["data_threshold_med+15s"] = hold_analysis(pairs, round(med + 15, 1))
    res["bs_holds"]["fixed_threshold_60s"] = hold_analysis(pairs, 60.0)
    res["odyn"] = {
        "n_casts": odyn_total,
        "in_reck_realbuff_rate": round(odyn_in_reck / odyn_total, 3) if odyn_total else None,
        "by_fight_time": odyn_by_bin,
        "gap_summary": summ(odyn_gaps),
        "gap_histogram": dist(odyn_gaps, [
            ("<40s", 0, 40), ("40-50s", 40, 50), ("50-60s", 50, 60),
            ("60-80s", 60, 80), ("80s+", 80, float("inf"))]),
        "설명": "'오딘은 기다리지 않는다' 검증 — 무희 창(전투의 ~1/3) 밖 사용률이 높으면 쿨마다 즉시 사용.",
    }
    return res


def drift_thane(kills):
    res = {"reck_baseline": reck_baseline(kills)}
    deltas = []
    av_by_bin = {label: {"n": 0, "synced3": 0} for label, _, _ in TIME_BINS}
    cyc = {"normal_lt100": {"n": 0, "synced3": 0}, "delayed_ge100": {"n": 0, "synced3": 0}}
    gap_vals = []
    av_in_reck = 0
    av_total = 0
    odyn_total = 0
    odyn_in_reck = 0
    odyn_in_av20 = 0
    odyn_gaps = []
    tb_delays = []
    tb_no_consume = 0
    tb_reach2 = 0
    overflow_refresh = 0
    for v in kills.values():
        t0, rel, buffs, reck_iv, dur = kill_times(v)
        av = rel(AVATAR)
        reck_c = rel(RECK_CAST)
        od = rel(ODYN)
        tb_c = rel(TB_CAST)
        for t in av:
            av_total += 1
            av_in_reck += active_at(reck_iv, t)
            d = None
            if reck_c:
                d = t - min(reck_c, key=lambda c: abs(c - t))
            deltas.append(d)
            bb = av_by_bin[tbin(t)]
            bb["n"] += 1
            if d is not None and abs(d) <= 3:
                bb["synced3"] += 1
        for a, b in zip(av, av[1:]):
            gap = b - a
            gap_vals.append(gap)
            key = "delayed_ge100" if gap >= 100 else "normal_lt100"
            cyc[key]["n"] += 1
            if reck_c and abs(min(reck_c, key=lambda c: abs(c - b)) - b) <= 3:
                cyc[key]["synced3"] += 1
        for t in od:
            odyn_total += 1
            odyn_in_reck += active_at(reck_iv, t)
            if any(0 <= t - a <= 20 for a in av):
                odyn_in_av20 += 1
        odyn_gaps += [b - a for a, b in zip(od, od[1:])]
        # 우레 작렬 2충전 추적 (버프 435615 스택)
        stacks = 0
        reach2_t = None
        for b in sorted(v["buffs"], key=lambda x: x[0]):
            if b[1] != TB_BUFF:
                continue
            t = (b[0] - t0) / 1000.0
            typ = b[2]
            prev = stacks
            if typ == "applybuff":
                stacks = 1
            elif typ == "removebuff":
                stacks = 0
            elif typ in ("applybuffstack", "removebuffstack"):
                stacks = b[4] if len(b) > 4 else stacks
            elif typ == "refreshbuff":
                if stacks >= 2:
                    overflow_refresh += 1  # 2충전 상태에서 프록 덮어씀 = 낭비
                continue
            if prev < 2 and stacks >= 2:
                tb_reach2 += 1
                reach2_t = t
            if prev >= 2 and stacks < 2 and reach2_t is not None:
                reach2_t = None
        # 2충전 도달 -> 다음 우레 작렬 시전 지연
        # (위 루프는 상태 검증용; 지연은 별도 패스로 계산)
        stacks = 0
        pend = None
        for b in sorted(v["buffs"], key=lambda x: x[0]):
            if b[1] != TB_BUFF:
                continue
            t = (b[0] - t0) / 1000.0
            typ = b[2]
            prev = stacks
            if typ == "applybuff":
                stacks = 1
            elif typ == "removebuff":
                stacks = 0
            elif typ in ("applybuffstack", "removebuffstack"):
                stacks = b[4] if len(b) > 4 else stacks
            else:
                continue
            if prev < 2 and stacks >= 2:
                pend = t
            if pend is not None and stacks < 2:
                # 스택이 줄었다 = 소모(우레 작렬 시전) 또는 만료
                nxt = next((x for x in tb_c if x >= pend), None)
                if nxt is not None and nxt <= t + 0.2:
                    tb_delays.append(nxt - pend)
                else:
                    tb_no_consume += 1
                pend = None
    have_d = [d for d in deltas if d is not None]
    sync3 = sum(1 for d in have_d if abs(d) <= 3)
    for bb in av_by_bin.values():
        bb["synced3_rate"] = round(bb["synced3"] / bb["n"], 3) if bb["n"] else None
    for vv in cyc.values():
        vv["synced3_rate"] = round(vv["synced3"] / vv["n"], 3) if vv["n"] else None
    res["avatar_vs_reck"] = {
        "n_avatar_casts": av_total,
        "in_reck_realbuff_rate": round(av_in_reck / av_total, 3) if av_total else None,
        "synced_abs3_rate": round(sync3 / len(have_d), 3) if have_d else None,
        "delta_dist_avatar_minus_reck": dist(have_d, [
            ("<-10s", -float("inf"), -10), ("-10..-3s", -10, -3),
            ("-3..0s", -3, 0), ("0..1s", 0, 1), ("1..3s", 1, 3),
            ("3..10s", 3, 10), (">10s", 10, float("inf"))]),
        "by_fight_time": av_by_bin,
        "cycles": {"gap_summary": summ(gap_vals),
                   "gap_histogram": dist(gap_vals, [
                       ("<80s", 0, 80), ("80-95s", 80, 95), ("95-110s", 95, 110),
                       ("110-130s", 110, 130), ("130s+", 130, float("inf"))]),
                   "by_cycle": cyc},
        "주의": "투신 시전 이벤트만 집계 — 폭풍의 화신 4초 미니 투신 프록은 시전이 아니라 버프라 여기 안 섞임.",
    }
    d_sorted = sorted(tb_delays)
    n = len(d_sorted)
    res["thunder_blast_2charge"] = {
        "n_reach_2stacks": tb_reach2,
        "n_consumed_tracked": n,
        "n_lost_no_cast": tb_no_consume,
        "consume_delay_s": {"med": round(statistics.median(d_sorted), 2) if n else None,
                            "p75": round(d_sorted[3 * n // 4], 2) if n else None,
                            "p90": round(d_sorted[9 * n // 10], 2) if n else None},
        "within_1gcd_pct": round(100.0 * sum(1 for x in d_sorted if x <= 1.5) / n, 1) if n else None,
        "within_3s_pct": round(100.0 * sum(1 for x in d_sorted if x <= 3.0) / n, 1) if n else None,
        "overflow_refresh_at_2stacks": overflow_refresh,
        "설명": "2충전 도달 -> 다음 우레 작렬 시전까지 지연. overflow = 2충전 상태에서 refreshbuff(새 프록 덮어씀=낭비).",
    }
    res["odyn"] = {
        "n_casts": odyn_total,
        "in_reck_realbuff_rate": round(odyn_in_reck / odyn_total, 3) if odyn_total else None,
        "in_avatar_cast20_rate": round(odyn_in_av20 / odyn_total, 3) if odyn_total else None,
        "gap_summary": summ(odyn_gaps),
    }
    return res


# ---------------- 메인 ----------------

def main():
    data = json.load(open(SCRATCH, encoding="utf-8"))
    slayer = {k: v for k, v in data.items() if any(c[1] == BS for c in v["casts"])}
    thane = {k: v for k, v in data.items() if any(c[1] == TB_CAST for c in v["casts"])}
    assert not set(slayer) & set(thane)

    result = {"_meta": {
        "generated_by": "tmp_mine_fury_procprio.py",
        "input": "scratchpad fury_cd_events.json — top100 296킬: 학살자 %d(칼날폭풍 446035) / 산왕 %d(우레 작렬 435222), 상호배타 실측 확인" % (len(slayer), len(thane)),
        "state_defs": {
            "enr": "격노 184362 활성 (시전 1ms 전 기준)",
            "sd": "급살 52437 활성",
            "btr": "피의 갈증 준비 근사 — 마지막 수동 피갈/피범벅 후 경과 >= 킬별 추정 쿨(깨끗한 간격 p25, 2400~4600ms 클램프). 산왕은 폭발적인 힘 437121 활성 시 True 강제",
            "reck": "무모한 희생 1719 실측 버프 창(applybuff→removebuff, 실측 ~18초)",
            "phase": "exec = 전투 시간 마지막 25% (대학살 HP<35%의 시간 근사)",
        },
        "buttons": {
            "rampage": RAMPAGE, "bt": BT, "bloodbath": BLOODBATH, "rb": RB,
            "crushing_blow": CRUSHING, "execute": [EXEC1, EXEC2], "thunder_clap": TC,
            "thunder_blast": TB_CAST, "whirlwind": WW, "bladestorm": BS,
            "avatar": AVATAR, "odyns_fury": ODYN, "recklessness": RECK_CAST,
        },
        "transform_check": "피범벅(335096)·분쇄의 타격(335097)은 무희 버프 창 안에서만 발생(실측: 피범벅 창 밖 0건) — 막무가내 버튼 변신 확정",
        "auto_bt_removal": "불안정한 정신(386628): 칼폭 채널 중 자동 피갈/피범벅. 격렬한 희열 1270731 applybuff가 칼폭 종료 시점 마커(실측) → [칼폭 시전, 종료+100ms] 창 안의 23881/335096 제외",
        "odyn_subevents": "385060/385061/385062 = 385059와 동일 타임스탬프 하위 이벤트 — 제외",
        "caveats": [
            "분노는 이벤트에 없음 — 특히 Q1(비격노)에서 광란이 안 나간 GCD는 분노<80일 가능성. 분포 그대로 보고.",
            "피갈 준비(btr)는 시전 간격 기반 근사 — 쿨 4.5초가 가속 스케일이라 킬별 p25로 추정(실측 중앙 ~3.1초). 4.5초 고정 결과를 sensitivity_flat4500에 병기.",
            "분노의 강타는 2충전+25% 초기화(연마)라 준비 상태 추정 불가 — Q3 '피갈 쿨 X'에서 분강이 나왔다고 분강 쿨이 돌았단 뜻은 아님.",
            "처형구간은 HP가 아닌 시간(마지막 25%) 근사.",
            "칼폭 채널 직후 첫 수동 피갈이 채널 창 +100ms에 걸치면 극소수 제외될 수 있음 — 표본 손실, 편향 작음.",
            "자동 피갈이 피갈 쿨을 실제로 돌리는지 불명(실측 애매) — btr의 last_bt는 수동 시전만 추적.",
        ],
    }}

    for hero, kills in (("slayer", slayer), ("thane", thane)):
        r = run_prio(kills, hero, "adaptive")
        rf = run_prio(kills, hero, "flat")
        views = prio_views(r, hero)
        durs = []
        for v in kills.values():
            cs = sorted(v["casts"], key=lambda c: c[0])
            durs.append((cs[-1][0] - cs[0][0]) / 1000.0)
        hero_out = {
            "n_kills": len(kills),
            "fight_len_s": summ(durs),
            "bt_ready_thr_ms": {"med": statistics.median(r["thr_used"]),
                                "min": min(r["thr_used"]), "max": max(r["thr_used"])},
            **views,
            "sensitivity_flat4500": {
                "Q2b_sdX_btrO_all": pack(merge_bins(rf["bins"], sd=False, btr=True)),
                "Q3_all_off_all": pack(merge_bins(rf["bins"], enr=True, sd=False, btr=False)),
            },
            "other_cast_ids_top": dict(r["other_ids"].most_common(12)),
            "full_state_table": {
                "enr=%d,sd=%d,btr=%d,reck=%d,%s" % (e, s, bt_, rk, ph):
                    pack(r["bins"][(bool(e), bool(s), bool(bt_), bool(rk), ph)])
                for e in (0, 1) for s in (0, 1) for bt_ in (0, 1) for rk in (0, 1)
                for ph in ("normal", "exec")
                if sum(r["bins"][(bool(e), bool(s), bool(bt_), bool(rk), ph)].values()) > 0
            },
        }
        if hero == "slayer":
            cd = r["channel_durs"]
            hero_out["auto_bt_removal"] = {
                "autos_removed": r["auto_removed"],
                "n_bs_casts": sum(1 for v in kills.values() for c in v["casts"] if c[1] == BS),
                "channel_ms": {"med": statistics.median(cd), "p90": sorted(cd)[9 * len(cd) // 10],
                               "max": max(cd)} if cd else None,
                "end_marker_missing": r["channel_end_marker_missing"],
            }
            hero_out["drift"] = drift_slayer(kills)
        else:
            hero_out["auto_bt_removal"] = {"autos_removed": r["auto_removed"],
                                           "note": "산왕은 불안정한 정신 없음 — 자동 피갈 오염 없음(0이어야 정상)"}
            hero_out["drift"] = drift_thane(kills)
        result[hero] = hero_out

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("saved", OUT)
    for hero in ("slayer", "thane"):
        h = result[hero]
        brief = {k: h[k] for k in ("n_kills", "bt_ready_thr_ms", "Q1_not_enraged",
                                   "Q2_sd_on", "Q2b_sdX_btrO", "Q3_all_off",
                                   "Q4_reck_window", "auto_bt_removal", "drift")}
        print("=" * 20, hero, "=" * 20)
        print(json.dumps(brief, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
