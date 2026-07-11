# -*- coding: utf-8 -*-
"""고통 흑마 빌드별 조건부 상태표 실측 — 전사 procprio 방법론 이식.
입력: 스크래치패드 aff_pp_events.json / aff_pp_meta.json (top100 백필 298킬)
출력: data/aff_procprio.json

빌드 축 (aff_talent_splits.json 마커, tmp_mine_aff_pp_extract.py 에서 태깅):
  단일   = 109865 자비우스의 계략 / 109852 치명적인 메아리   (204킬)
  씨앗광 = 109854 씨앗 뿌리기 / 109853 최초 감염자 / 109866 파괴의 씨앗 (94킬)

상태 태깅 (각 버튼의 '결정 시점' 직전, t-1ms):
  sun = 일몰 활성 (264571 단일변형 / 1260279 씨앗변형 — 중첩형, >=1)
  si  = 조각의 불안정성 1260269 활성 (씨앗광은 채택 0~5%라 사실상 단일 전용)
  dg  = 암흑시선 소환 205180 창 (버프 apply→remove 실측)
  phase exec = 전투 시간 마지막 25% (죽음의 은총 35% HP 의 시간 근사)
  ★영혼의 조각 수는 이벤트에 없어 관측 불가 — 조각 상태 축은 없음(명시적 한계)★

결정 시점: 시전시간 있는 주문(불안정한 고통/부패의 씨앗/어둠의 화살/유령 출몰)은
cast 완료가 아니라 begincast 시각이 버튼 판단 시점 — begincast↔cast 페어링해
하드캐스트는 begincast 시각, 페어 없는 cast 는 즉시시전(프록)으로 태깅.

오염 확인: 600ms 미만 연속 시전은 '하드캐스트 완료→즉발 프록 연계'로 설명되는지 검증
(전사의 오딘 트리플 같은 자동시전 오염은 고통엔 없음 — 수치로 확인해 보고).
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from collections import Counter, defaultdict
from statistics import median

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(__file__).parent / "data"
SCRATCH = Path(r"C:\Users\MKSEORTV\AppData\Local\Temp\claude"
               r"\C--Users-MKSEORTV-Desktop-WowAnalyzer"
               r"\30b0abb8-5226-4b13-9c1c-14e4a1562211\scratchpad")
OUT = DATA / "aff_procprio.json"

# ── 스펠 ID (spell_db.json 공식 한글명) ──
AGONY = 980          # 고통 (18s DoT, 조각 생성)
CORR = 172           # 부패 (완전한 부패 채택 시 무한 — 1회 시전 후 방치)
UA = 1259790         # 불안정한 고통 (조각 1 소비)
SEED = 27243         # 부패의 씨앗 (조각 1 소비)
SBOLT = 686          # 어둠의 화살
DRAIN = 198590       # 영혼 흡수 (어둠의 화살 대체 CHOICE)
GRIP = 1261153       # 재앙의 손아귀 (암흑시선 창 중 어둠의 화살 변신)
HAUNT = 48181        # 유령 출몰 (15s쿨)
DG = 205180          # 암흑시선 소환 (2분쿨/20s)
HARVEST = 1257052    # 암흑의 수확 (1분쿨, 3s 정신집중)

BUTTONS = {
    AGONY: "agony", CORR: "corruption", UA: "ua", SEED: "seed",
    SBOLT: "sbolt", DRAIN: "drain", GRIP: "grip", HAUNT: "haunt",
    DG: "darkglare", HARVEST: "harvest",
}
NAMES_KO = {
    "agony": "고통", "corruption": "부패", "ua": "불안정한 고통",
    "seed": "부패의 씨앗", "sbolt": "어둠의 화살", "drain": "영혼 흡수",
    "grip": "재앙의 손아귀", "haunt": "유령 출몰",
    "darkglare": "암흑시선 소환", "harvest": "암흑의 수확", "other": "기타",
}
# 비순환/이동/유틸/소모품/펫 — 상태별 분포에서 제외
EXCLUDE = {111400, 108416, 48020, 48018, 104773, 6789, 385899, 452930,
           33702, 119905, 119910, 26297, 1714, 702, 333889, 20707, 6201,
           691, 688, 30283, 358733, 103740, 346059, 176890, 229837,
           1236616, 1236994, 1234768, 1250508, 306318, 1253050, 1260459,
           1271802, 1234969, 445468, 697, 712, 30146}

SUNSET_IDS = {264571, 1260279}  # 일몰 (특성 분기, 한 판 내 상호배타)
SI_BUFF = 1260269               # 조각의 불안정성
HARDCAST_SPELLS = {UA, SEED, SBOLT, HAUNT}  # begincast 있는 주문
SUNSET_CONSUMERS = {"sbolt", "drain", "grip", "seed"}

AGONY_DUR = 18.0
UA_DUR = 8.0
PANDEMIC = 0.30


# ---------------- 공용 ----------------

def build_stacks(buffs, ids, t0):
    """중첩형 버프 타임라인 [(t, stacks)] — 일몰/조각의 불안정성."""
    tl, cur = [(t0 - 10_000, 0)], 0
    for b in buffs:
        if b[1] not in ids: continue
        t, typ = b[0], b[2]
        if typ == "applybuff": cur = 1
        elif typ == "applybuffstack": cur = b[4] if len(b) > 4 and isinstance(b[4], int) else cur + 1
        elif typ == "removebuffstack": cur = b[4] if len(b) > 4 and isinstance(b[4], int) else max(0, cur - 1)
        elif typ == "removebuff": cur = 0
        elif typ == "refreshbuff": tl.append((t, max(cur, 1))); continue
        tl.append((t, cur))
    return tl


def stacks_at(tl, t):
    s = 0
    for tt, v in tl:
        if tt <= t: s = v
        else: break
    return s


def build_intervals(buffs, buff_id, t0, t_end):
    iv, start = [], None
    for b in buffs:
        if b[1] != buff_id: continue
        t, typ = b[0], b[2]
        if typ == "applybuff":
            if start is None: start = t
        elif typ == "removebuff":
            if start is None: start = t0
            iv.append((start, t)); start = None
    if start is not None: iv.append((start, t_end))
    return iv


def active_at(iv, t):
    return any(a <= t <= b for a, b in iv)


def pack(counter, kmap=None):
    n = sum(counter.values())
    if n == 0: return {"n": 0}
    out = {"n": n}
    for btn, c in counter.most_common():
        out[btn] = {"count": c, "pct": round(100.0 * c / n, 1)}
    return out


def q(vals, p):
    if not vals: return None
    v = sorted(vals)
    return round(v[min(len(v) - 1, max(0, int(round(p * (len(v) - 1)))))], 2)


# ---------------- 액션 스트림 (begincast 페어링) ----------------

def action_stream(e):
    """완료된 cast 마다 결정 시점(action t)을 부여한 스트림.
    하드캐스트 가능 주문은 직전 begincast(6s 내, 미소비)를 페어링.
    ★즉시시전(일몰/조각의 불안정성/밤의 수혜)은 begincast+cast 가 같은 타임스탬프로
    둘 다 찍힘(실측) — 페어 간격 <500ms 는 하드캐스트가 아니라 즉시시전으로 분류★
    (최저 실질 시전시간은 가속 만렙이어도 1초 이상)."""
    casts = sorted((c for c in e["casts"] if len(c) >= 3), key=lambda c: c[0])
    bc_by = defaultdict(list)
    for c in casts:
        if c[2] == "begincast": bc_by[c[1]].append(c[0])
    used = {sid: 0 for sid in bc_by}
    out = []  # (action_t, cast_t, sid, hardcast)
    for c in casts:
        if c[2] != "cast": continue
        t, sid = c[0], c[1]
        if sid in HARDCAST_SPELLS and sid in bc_by:
            lst, i = bc_by[sid], used[sid]
            best = None
            while i < len(lst) and lst[i] <= t:
                if t - lst[i] <= 6000: best = i
                i += 1
            if best is not None and best >= used[sid] and t - lst[best] >= 500:
                out.append((lst[best], t, sid, True))
                used[sid] = best + 1
                continue
            if best is not None and t - lst[best] < 500:
                used[sid] = best + 1  # 같은 ms 의 짝 begincast 소진(즉시시전 로그 서명)
        out.append((t, t, sid, False))
    out.sort(key=lambda x: x[0])
    return out


# ---------------- 킬 단위 분석 ----------------

def analyze(kills, build):
    bins = defaultdict(Counter)           # (sun, si, phase) → 버튼
    d_dg = {"dgO": Counter(), "dgX": Counter()}   # 전부꺼짐 상태의 암흑시선 창 안/밖
    e_bin = Counter()                     # sun O + si O
    other_ids = Counter()
    hard_ratio = defaultdict(lambda: [0, 0])  # sid → [instant, hardcast]
    echo_removed = Counter()              # 동일 스킬 ≤50ms 연속 완료(자동 에코) 제거
    btn_totals = Counter()
    total_min = 0.0

    sun_gain = sun_consumed = sun_expired = 0
    sun_delays = []
    si_gain = si_consumed = si_expired = 0
    si_delays = []

    agony_gaps, ua_gaps, corr_per_fight = [], [], []
    agony_gaps_by_boss = defaultdict(list)
    agony_upt = []

    dg_prev3 = Counter()
    dg_pre_agony = dg_pre_ua = dg_n = 0
    dg_first, dg_gapall = [], []
    ua_in_win = ua_tot = 0
    win_share_num = win_share_den = 0.0
    grip_in_win = grip_tot = 0
    harvest_in_win = harvest_tot = 0

    seed_runs = Counter()
    seed_run_gaps, seed_intra = [], []
    seed_instant = [0, 0]

    rapid_pairs = Counter()   # (첫캐스트 하드?, 둘째 즉발?) — 600ms 미만 연속 시전 설명

    filler_pref = Counter()   # 킬 단위 어둠의 화살 vs 영혼 흡수 채택

    for k, e, m in kills:
        t0, t1 = m["t0"], m["t1"]
        dur_s = (t1 - t0) / 1000
        if dur_s < 60: continue
        buffs = sorted((b for b in e["buffs"] if len(b) >= 3), key=lambda b: b[0])
        stream = action_stream(e)
        if len(stream) < 20: continue
        # ── 자동 에코 제거: 같은 스킬이 직전 완료 후 ≤50ms 에 다시 완료 (씨앗 뿌리기
        #    추가 심기 등 — 버튼 입력일 수 없는 간격, 전사 오딘 트리플 상당) ──
        clean, last_done = [], {}
        for at, ct, sid, hard in stream:
            if sid in last_done and 0 <= ct - last_done[sid] <= 50:
                echo_removed[BUTTONS.get(sid, sid)] += 1
                last_done[sid] = ct
                continue
            last_done[sid] = ct
            clean.append((at, ct, sid, hard))
        stream = clean
        total_min += dur_s / 60
        exec_start = t0 + 0.75 * (t1 - t0)

        sun_tl = build_stacks(buffs, SUNSET_IDS, t0)
        si_tl = build_stacks(buffs, {SI_BUFF}, t0)
        dg_iv = build_intervals(buffs, DG, t0, t1)

        # 킬 단위 필러 선호 (어둠의 화살 연마 vs 영혼 흡수 CHOICE)
        n_sb = sum(1 for a in stream if a[2] == SBOLT)
        n_dr = sum(1 for a in stream if a[2] == DRAIN)
        if n_sb + n_dr >= 5:
            filler_pref["drain" if n_dr > n_sb else "sbolt"] += 1

        # ── 상태표 ──
        rot = []  # 순환 버튼만 (결정시각 순)
        for at, ct, sid, hard in stream:
            if sid in EXCLUDE: continue
            btn = BUTTONS.get(sid, "other")
            if btn == "other":
                other_ids[sid] += 1
                continue
            if sid in HARDCAST_SPELLS:
                hard_ratio[sid][1 if hard else 0] += 1
            eps = at - 1
            sun = stacks_at(sun_tl, eps) > 0
            si = stacks_at(si_tl, eps) > 0
            dg_on = active_at(dg_iv, eps)
            phase = "exec" if at >= exec_start else "normal"
            bins[(sun, si, phase)][btn] += 1
            btn_totals[btn] += 1
            if sun and si: e_bin[btn] += 1
            if not sun and not si:
                d_dg["dgO" if dg_on else "dgX"][btn] += 1
            rot.append((at, ct, sid, btn))

        # ── 600ms 미만 연속 시전 오염 검증 ──
        comp = sorted((ct, sid, hard) for at, ct, sid, hard in stream)
        for (ta, ia, ha), (tb, ib, hb) in zip(comp, comp[1:]):
            if 0 <= tb - ta < 600 and ia not in EXCLUDE and ib not in EXCLUDE:
                key = ("first_hard" if ha else "first_instant",
                       "second_hard" if hb else "second_instant")
                rapid_pairs[key] += 1

        # ── 프록 소모: 일몰 — 획득→이후 첫 소비자 시전(완료), 8s 내 없으면 만료/낭비 ──
        gains = [b[0] for b in buffs if b[1] in SUNSET_IDS and b[2] in ("applybuff", "applybuffstack")]
        cons_t = sorted(ct for at, ct, sid, hard in stream if BUTTONS.get(sid) in SUNSET_CONSUMERS)
        sun_gain += len(gains)
        ci = 0
        for g in gains:
            while ci < len(cons_t) and cons_t[ci] < g: ci += 1
            # ci 를 되돌리지 않는 단조 매칭(프록 1개당 소비 1회)
            if ci < len(cons_t) and cons_t[ci] - g <= 8000:
                sun_consumed += 1
                sun_delays.append((cons_t[ci] - g) / 1000)
                ci += 1
            else:
                sun_expired += 1

        # ── 프록 소모: 조각의 불안정성 → 불안정한 고통 ──
        si_gains = [b[0] for b in buffs if b[1] == SI_BUFF and b[2] in ("applybuff", "applybuffstack", "refreshbuff")]
        ua_t = sorted(ct for at, ct, sid, hard in stream if sid == UA)
        si_gain += len(si_gains)
        ci = 0
        for g in si_gains:
            while ci < len(ua_t) and ua_t[ci] < g: ci += 1
            if ci < len(ua_t) and ua_t[ci] - g <= 8000:
                si_consumed += 1
                si_delays.append((ua_t[ci] - g) / 1000)
                ci += 1
            else:
                si_expired += 1

        # ── DoT 갱신 ──
        ag_t = sorted(ct for at, ct, sid, hard in stream if sid == AGONY)
        g_list = [(b - a) / 1000 for a, b in zip(ag_t, ag_t[1:]) if (b - a) / 1000 < 60]
        agony_gaps += g_list
        agony_gaps_by_boss[m["boss"]] += g_list
        # 근사 업타임(합집합 [cast, cast+18] / 전투시간) — 멀티도트 보스는 과대
        if ag_t:
            cov, cur_a, cur_b = 0.0, None, None
            for t in ag_t:
                a, b = t, min(t + AGONY_DUR * 1000, t1)
                if cur_b is None or a > cur_b:
                    if cur_b is not None: cov += cur_b - cur_a
                    cur_a, cur_b = a, b
                else:
                    cur_b = max(cur_b, b)
            cov += (cur_b - cur_a) if cur_b is not None else 0
            agony_upt.append(cov / (t1 - t0))
        ua_gaps += [(b - a) / 1000 for a, b in zip(ua_t, ua_t[1:]) if (b - a) / 1000 < 60]
        corr_per_fight.append(sum(1 for at, ct, sid, hard in stream if sid == CORR))

        # ── 암흑시선 정렬 ──
        dg_t = [ct for at, ct, sid, hard in stream if sid == DG]
        dg_n += len(dg_t)
        if dg_t: dg_first.append((dg_t[0] - t0) / 1000)
        dg_gapall += [(b - a) / 1000 for a, b in zip(dg_t, dg_t[1:])]
        rot_t = [(at, btn) for at, ct, sid, btn in rot]
        for t in dg_t:
            prev = [btn for at, btn in rot_t if t - 15000 <= at < t and btn != "darkglare"][-3:]
            dg_prev3[tuple(prev)] += 1
            if any(at for at, b2 in rot_t if b2 == "agony" and 0 < t - at <= 10000): dg_pre_agony += 1
            if any(at for at, b2 in rot_t if b2 == "ua" and 0 < t - at <= 6000): dg_pre_ua += 1
        win_share_num += sum(b - a for a, b in dg_iv)
        win_share_den += (t1 - t0)
        for t in ua_t:
            ua_tot += 1
            if active_at(dg_iv, t): ua_in_win += 1
        for at, ct, sid, hard in stream:
            if sid == GRIP:
                grip_tot += 1
                if active_at(dg_iv, ct): grip_in_win += 1
            elif sid == HARVEST:
                harvest_tot += 1
                if active_at(dg_iv, ct): harvest_in_win += 1

        # ── 씨앗 연타 (순환 스트림에서 seed 연속 런) ──
        run = 0
        last_run_end = None
        run_start = None
        for i, (at, ct, sid, btn) in enumerate(rot):
            if btn == "seed":
                if run > 0: seed_intra.append((at - rot[i - 1][0]) / 1000)
                if run == 0:
                    run_start = at
                    if last_run_end is not None:
                        seed_run_gaps.append((at - last_run_end) / 1000)
                run += 1
            else:
                if run > 0:
                    seed_runs[min(run, 8)] += 1
                    last_run_end = rot[i - 1][0]
                run = 0
        if run > 0: seed_runs[min(run, 8)] += 1
        for at, ct, sid, hard in stream:
            if sid == SEED: seed_instant[0 if not hard else 1] += 1

    # ── 정리 ──
    def gapstat(g, dur=None):
        if not g: return None
        s = {"n": len(g), "p25": q(g, .25), "med": q(g, .5), "p75": q(g, .75), "p90": q(g, .9)}
        if dur:
            rem = [dur - x for x in g if 4 <= x <= dur * 1.3]
            pan = dur * PANDEMIC
            s["remaining_at_recast_s"] = {
                "n": len(rem), "med": q(rem, .5), "p25": q(rem, .25), "p75": q(rem, .75),
                "pandemic_창_s": round(pan, 1),
                "판데믹내_갱신_pct": round(100 * sum(1 for r in rem if 0 <= r <= pan) / len(rem), 1) if rem else None,
                "조기갱신_pct(남은시간>판데믹)": round(100 * sum(1 for r in rem if r > pan) / len(rem), 1) if rem else None,
            }
            s["만료후_공백_pct(gap>dur+2s)"] = round(100 * sum(1 for x in g if x > dur + 2) / len(g), 1)
        return s

    n_kills = len({k for k, e, m in kills})
    res = {
        "n_kills": n_kills,
        "total_min": round(total_min, 1),
        "buttons_per_min": {
            NAMES_KO.get(b, b): round(c / total_min, 2)
            for b, c in btn_totals.most_common() if total_min
        },
        "echo_auto_events_removed": {str(NAMES_KO.get(b, b)): c for b, c in echo_removed.most_common()},
        "state_table": {},
        "proc_consumption": {
            "일몰": {
                "gains": sun_gain,
                "consumed_pct": round(100 * sun_consumed / max(1, sun_gain), 1),
                "expired_or_wasted_pct": round(100 * sun_expired / max(1, sun_gain), 1),
                "consume_delay_s": {"med": q(sun_delays, .5), "p75": q(sun_delays, .75), "p90": q(sun_delays, .9)},
                "within_2s_pct": round(100 * sum(1 for d in sun_delays if d <= 2) / max(1, len(sun_delays)), 1),
            },
            "조각의_불안정성": {
                "gains": si_gain,
                "consumed_pct": round(100 * si_consumed / max(1, si_gain), 1),
                "expired_or_wasted_pct": round(100 * si_expired / max(1, si_gain), 1),
                "consume_delay_s": {"med": q(si_delays, .5), "p75": q(si_delays, .75), "p90": q(si_delays, .9)},
                "within_2s_pct": round(100 * sum(1 for d in si_delays if d <= 2) / max(1, len(si_delays)), 1),
            } if si_gain else {"gains": 0, "note": "이 빌드는 조각의 불안정성 채택 없음(또는 극소수)"},
        },
        "dots": {
            "고통_18s": gapstat(agony_gaps, AGONY_DUR),
            "고통_추정업타임": {"med_pct": round(100 * (q(agony_upt, .5) or 0), 1),
                          "p25_pct": round(100 * (q(agony_upt, .25) or 0), 1),
                          "주의": "합집합 근사(대상 구분 없음) — 멀티도트 보스는 과대, 단일 보스만 신뢰"},
            "불안정한_고통_시전주기": gapstat(ua_gaps),
            "부패_판당시전": {"med": q(corr_per_fight, .5), "p90": q(corr_per_fight, .9),
                        "note": "완전한 부패(무한 지속) 표준 — 1회 깔고 방치가 정상"},
        },
        "darkglare": {
            "n_casts": dg_n,
            "first_s_med": q(dg_first, .5),
            "gap_s_med": q(dg_gapall, .5),
            "직전_고통갱신_10s내_pct": round(100 * dg_pre_agony / max(1, dg_n), 1),
            "직전_불안정한고통_6s내_pct": round(100 * dg_pre_ua / max(1, dg_n), 1),
            "직전_3버튼_top6": [{"seq": [NAMES_KO.get(b, b) for b in s], "n": c}
                            for s, c in dg_prev3.most_common(6)],
            "창내_불안정한고통_pct": round(100 * ua_in_win / max(1, ua_tot), 1),
            "창_시간비중_pct": round(100 * win_share_num / max(1, win_share_den), 1),
            "재앙의_손아귀_창내_pct": round(100 * grip_in_win / max(1, grip_tot), 1) if grip_tot else None,
            "암흑의_수확_창내_pct": round(100 * harvest_in_win / max(1, harvest_tot), 1) if harvest_tot else None,
        },
        "hardcast_vs_instant": {
            NAMES_KO.get(BUTTONS.get(sid), str(sid)): {
                "instant": v[0], "hardcast": v[1],
                "instant_pct": round(100 * v[0] / max(1, v[0] + v[1]), 1)}
            for sid, v in sorted(hard_ratio.items())
        },
        "filler_choice_kills": dict(filler_pref),
        "rapid_600ms_pairs": {f"{a}->{b}": c for (a, b), c in rapid_pairs.most_common()},
        "other_cast_ids_top": dict(other_ids.most_common(10)),
        "agony_gap_by_boss": {
            b: gapstat(g, AGONY_DUR) for b, g in sorted(agony_gaps_by_boss.items(), key=lambda x: -len(x[1]))
            if len(g) >= 100
        },
    }
    if build == "씨앗광" or sum(seed_runs.values()) >= 50:
        tot_runs = sum(seed_runs.values())
        res["seed_pattern"] = {
            "runs_total": tot_runs,
            "run_len_dist": {str(k): {"count": v, "pct": round(100 * v / tot_runs, 1)}
                             for k, v in sorted(seed_runs.items())},
            "run_len_med": None,
            "intra_run_gap_s_med": q(seed_intra, .5),
            "inter_run_gap_s": {"med": q(seed_run_gaps, .5), "p25": q(seed_run_gaps, .25), "p75": q(seed_run_gaps, .75)},
            "instant_seed_pct": round(100 * seed_instant[0] / max(1, sum(seed_instant)), 1),
            "note": "run = 순환 버튼 스트림에서 부패의 씨앗 연속 구간. instant = begincast 페어 없는 완료(밤의 수혜 공짜+즉발)",
        }
        lens = [k for k, v in seed_runs.items() for _ in range(v)]
        res["seed_pattern"]["run_len_med"] = q(lens, .5)

    # 상태표 뷰
    def m_any(sun=None, si=None, ph=None):
        c = Counter()
        for (s, i2, p), cnt in bins.items():
            if sun is not None and s != sun: continue
            if si is not None and i2 != si: continue
            if ph is not None and p != ph: continue
            c += cnt
        return c

    res["state_table"] = {
        "A_일몰O": {"all": pack(m_any(sun=True)),
                  "normal": pack(m_any(sun=True, ph="normal")),
                  "exec": pack(m_any(sun=True, ph="exec"))},
        "B_일몰X_조각불안정O": {"all": pack(m_any(sun=False, si=True)),
                        "normal": pack(m_any(sun=False, si=True, ph="normal")),
                        "exec": pack(m_any(sun=False, si=True, ph="exec"))},
        "C_일몰O_조각불안정O": pack(e_bin),
        "D_전부꺼짐": {"normal": pack(m_any(sun=False, si=False, ph="normal")),
                   "exec": pack(m_any(sun=False, si=False, ph="exec")),
                   "암흑시선창_안": pack(d_dg["dgO"]),
                   "암흑시선창_밖": pack(d_dg["dgX"])},
        "full": {f"sun={int(s)},si={int(i2)},{p}": pack(bins[(s, i2, p)])
                 for s in (False, True) for i2 in (False, True) for p in ("normal", "exec")},
    }
    return res


def main():
    ev = json.load(open(SCRATCH / "aff_pp_events.json", encoding="utf-8"))
    meta = json.load(open(SCRATCH / "aff_pp_meta.json", encoding="utf-8"))
    groups = defaultdict(list)
    boss_by_build = defaultdict(Counter)
    for k, e in ev.items():
        m = meta.get(k)
        if not m: continue
        groups[m["build"]].append((k, e, m))
        boss_by_build[m["build"]][m["boss"]] += 1

    result = {
        "_meta": {
            "generated_by": "tmp_mine_aff_procprio.py",
            "input": "scratchpad aff_pp_events.json — v2_cache_events 백필 중 고통 %d킬 "
                     "(pf 캐시 고통 노드 식별, 오늘자 CSV와 (report,fight,char) 키 불일치로 "
                     "pf/meta 캐시 자체 매칭 — 표본은 2026-07-05 top100 백필분)" % len(ev),
            "build_markers": {
                "단일": "109865 자비우스의 계략 + 109852 치명적인 메아리 + 109857 조각의 불안정성 (전원 동반)",
                "씨앗광": "109854 씨앗 뿌리기 + 109853 최초 감염자 + 109866 파괴의 씨앗 + 109851 밤의 수혜 (조각의 불안정성 X)",
                "씨앗_조각불안정_변형": "씨앗 마커 + 109857 조각의 불안정성 병행 — 카이메루스 위주 소수 변형",
                "근거": "data/aff_talent_splits.json swap_relations + 추출 298킬 마커 crosstab — 단일/씨앗 계열 상호 with_rate 0%",
            },
            "state_defs": {
                "sun": "일몰 264571(단일변형)/1260279(씨앗변형) 중첩>=1 (결정시점 1ms 전)",
                "si": "조각의 불안정성 1260269 활성",
                "dg": "암흑시선 소환 205180 버프 창(실측 apply→remove)",
                "phase": "exec = 전투 시간 마지막 25% (죽음의 은총 35% HP 시간 근사)",
                "결정시점": "하드캐스트(불안정한 고통/부패의 씨앗/어둠의 화살/유령 출몰)는 begincast 시각, "
                        "페어 없는 완료는 즉시시전으로 cast 시각",
            },
            "buttons": {v: {"id": k, "ko": NAMES_KO[v]} for k, v in BUTTONS.items()},
            "caveats": [
                "영혼의 조각 수는 이벤트에 없음 — 조각 축 관측 불가. UA/씨앗 시전 주기가 조각 수급의 간접 지표.",
                "대상 디버프 타임라인 없음(자기 버프+캐스트만) — 도트 '남은 시간'은 같은 스킬 재시전 간격으로 근사. "
                "멀티도트 보스에선 대상이 섞여 간격이 압축됨 — 단일 보스(보라시우스/우주의 왕관/벨로렌) 수치가 진짜 갱신 규율.",
                "처형구간은 HP가 아닌 시간(마지막 25%) 근사.",
                "빌드 그룹은 보스 구성이 다름(단일=단일 보스, 씨앗광=바엘고어·선봉대) — 상태표 차이에 보스 특성이 섞임.",
                "표본은 백필 시점(2026-07-05 무렵) top100 스냅샷 — 오늘자 CSV와 (report,fight) 키가 어긋나 랭크 밴드 미부여. "
                "카이메루스는 이 표본에서 단일 16 vs 씨앗변형 18로 갈린 과도기 전략(최신 채택률은 단일 97%).",
                "즉시시전 판정: begincast+cast 같은 타임스탬프(실측 로그 서명) 또는 begincast 페어 부재. "
                "같은 스킬 ≤50ms 연속 완료는 자동 에코(씨앗 뿌리기 추가 심기 등)로 제거 — echo_auto_events_removed 참조.",
            ],
            "builds_by_boss": {b: dict(c.most_common()) for b, c in boss_by_build.items()},
        },
    }
    for build in ("단일", "씨앗광", "씨앗_조각불안정_변형"):
        if groups[build]:
            result[build] = analyze(groups[build], build)

    result["flow_verdict"] = (
        "빌드 2탭 신설 타당 — 주력 버튼 자체가 다름: 단일은 불안정한 고통 17.2/분·부패의 씨앗 0.33/분, "
        "씨앗광은 부패의 씨앗 21.6/분·불안정한 고통 1.8/분. 상태표 1순위도 전 상태에서 갈림"
        "(단일=불안정한 고통, 씨앗광=부패의 씨앗). 카이메루스 '씨앗+조각의 불안정성' 변형(18킬)은 "
        "별도 탭 불필요 — 씨앗광 탭에 각주(불안정한 고통 10.9/분 + 씨앗 8.5/분 하이브리드)면 충분.")
    result["단일"]["guide_lines"] = [
        "조각 소비 최우선: 어떤 프록 상태든 다음 버튼 1순위는 불안정한 고통(일몰O 41%·조각의 불안정성O 57%·전부 꺼짐 38%) — 프록보다 영혼의 조각이 항상 위.",
        "일몰: 분당 7.3회 획득, 84% 소모(중앙 2.2초) — 조각 소비 사이 첫 필러(어둠의 화살/영혼 흡수)를 즉발로. 낭비 16%는 2중첩 허용 덕에 큰 손해 아님.",
        "조각의 불안정성: 95% 소모, 중앙 1.4초(2초 내 68%) — 뜨면 다음 불안정한 고통이 공짜+즉발이라 즉시 소비.",
        "고통 갱신: 순수 단일 보스(보라시우스) 실측 '남은 3.1초'에 갱신 — 판데믹 창(5.4초) 안 갱신이 규율, 만료 공백은 5% 미만. 멀티도트 보스는 대상 순회로 간격이 절반쯤으로 압축.",
        "부패: 완전한 부패(무한 지속)라 판당 중앙 4회 — 개막+대상 교체 시만.",
        "암흑시선 소환: 첫 사용 중앙 5.8초(고통→부패→불안정한 고통 셋업 직후), 이후 쿨마다(간격 중앙 122.8초). 시전 직전 10초 내 고통 갱신 83%·6초 내 불안정한 고통 69% — 도트 정비를 마치고 창을 연다.",
        "암흑시선 창 = 조각 몰아쓰기: 창 안 불안정한 고통 비중 30.4% vs 창 시간 비중 22.5%.",
        "재앙의 손아귀: 시전 100%가 암흑시선 창 안 — 창이 열리면 필러가 재앙의 손아귀로 대체된다(전부 꺼짐·창 안 분포에서 21%).",
        "필러 선택은 반반(어둠의 화살 연마 93킬 vs 영혼 흡수 109킬) — 순위 구조는 동일.",
        "유령 출몰: 15초 쿨 거의 쿨마다(3.3/분).",
    ]
    result["씨앗광"]["guide_lines"] = [
        "부패의 씨앗이 주력 버튼(21.6/분, 순환 GCD의 절반) — 조각이 생기는 대로 계속 시전.",
        "일몰(밤의 수혜): 98% 소모, 중앙 0.8초(2초 내 81%) — 뜨는 즉시 공짜+즉발 씨앗. 단일빌드보다 훨씬 타이트하게 소비.",
        "씨앗 연타 구조: 1연 39%·2연 24%·3연 15%·4연+ 22%, 연타 묶음 간격 중앙 3.7초 — 웨이브를 기다렸다 몰아치는 패턴이 아니라 상시 연사(대기 신호 없음).",
        "불안정한 고통은 1.8/분(유지 수준), 어둠의 화살/영혼 흡수는 3.5/분 보조 필러 — 전부 꺼짐 상태에서도 씨앗 51%.",
        "고통 7.5/분 — 바엘고어&에조라크·선봉대 2타겟 멀티도트 순회(갱신 규율은 단일과 동일 판데믹).",
        "암흑시선 소환: 첫 사용 중앙 4.1초, 직전 10초 내 고통 갱신 89.7% — 단일과 같은 '도트 정비 후 오픈'. 재앙의 손아귀 미채택이라 창 중에도 씨앗 연사.",
        "처형 구간(마지막 25%)에도 씨앗 1순위(56%) — 필러 전환 없음.",
    ]

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", OUT)
    for build in ("단일", "씨앗광", "씨앗_조각불안정_변형"):
        if build not in result: continue
        r = result[build]
        print(f"\n===== {build} (n={r['n_kills']}) =====")
        st = r["state_table"]
        for k in ("A_일몰O", "B_일몰X_조각불안정O", "D_전부꺼짐"):
            v = st[k]
            vv = v.get("all") or v.get("normal")
            top = [(b, vv[b]["pct"]) for b in vv if b != "n"][:4]
            print(f"  {k}: n={vv['n']} top={top}")
        print("  C_일몰O_조각불안정O:", {b: v for b, v in list(st["C_일몰O_조각불안정O"].items())[:5]})
        print("  일몰:", r["proc_consumption"]["일몰"])
        print("  조각불안정:", r["proc_consumption"]["조각의_불안정성"])
        print("  고통:", r["dots"]["고통_18s"] and {kk: r["dots"]["고통_18s"][kk] for kk in ("n", "med", "remaining_at_recast_s")})
        print("  암흑시선:", {kk: r["darkglare"][kk] for kk in ("n_casts", "first_s_med", "직전_고통갱신_10s내_pct", "직전_불안정한고통_6s내_pct", "창내_불안정한고통_pct", "창_시간비중_pct")})
        print("  rapid pairs:", r["rapid_600ms_pairs"])
        print("  echo removed:", r["echo_auto_events_removed"])
        print("  per_min:", r["buttons_per_min"])
        print("  hardcast/instant:", r["hardcast_vs_instant"])
        if "seed_pattern" in r:
            print("  seed_pattern:", {kk: r["seed_pattern"][kk] for kk in ("run_len_dist", "run_len_med", "inter_run_gap_s", "instant_seed_pct")})


if __name__ == "__main__":
    main()
