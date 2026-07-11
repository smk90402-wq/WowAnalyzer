# -*- coding: utf-8 -*-
"""
무기 전사(Arms) 프록 상태별 조건부 우선순위 실측 — 학살자 킬 한정.
입력: 스크래치패드 arms_cd_events.json (top100 296킬 casts/buffs)
출력: data/arms_procprio.json

상태 태깅 (각 GCD 시전 직전, t-1ms 기준):
  hs  = 전쟁의 지배자 프록 버프 1269391 활성
  sd  = 급살 버프 52437 활성
  msr = 필사의 일격 준비 근사: 마지막 '수동' 12294 시전 후 경과 >= 킬별 추정 쿨
        (킬별 깨끗한 필사 간격 p25, 3600~5500ms 클램프. 민감도로 5.0초 고정도 병기)
  ep2 = 집행자의 정밀함 386633 2중첩
처형구간 = 전투 시간 마지막 25% (대학살 35% HP의 시간 근사).

주의: 불안정한 정신(109815, 학살자 99% 채택) 때문에 칼날폭풍 채널 중 필사의
일격(12294)이 '자동 시전'으로 찍힘(칼폭 후 0.5/1.5/2.5/3.5/4.5초 틱 실측).
→ 칼폭 시전 후 4.75초 안의 12294는 자동으로 보고 분포·쿨 추적에서 제외.
"""
import json
import os
from collections import Counter, defaultdict
from statistics import median

SCRATCH = r"C:\Users\MKSEORTV\AppData\Local\Temp\claude\C--Users-MKSEORTV-Desktop-WowAnalyzer\30b0abb8-5226-4b13-9c1c-14e4a1562211\scratchpad\arms_cd_events.json"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "arms_procprio.json")

HS_CAST = 1269383   # 영웅의 일격
MS_CAST = 12294     # 필사의 일격
EX_CAST = 281000    # 마무리 일격(학살자)
OP_CAST = 7384      # 제압
SLAM_CAST = 1464    # 격돌
REND_CAST = 772     # 분쇄
CLEAVE_CAST = 845   # 회전베기
BLADESTORM = 446035 # 칼날폭풍(학살자 마커)

BUTTONS = {
    HS_CAST: "hs", MS_CAST: "ms", EX_CAST: "execute", OP_CAST: "op",
    SLAM_CAST: "slam", REND_CAST: "rend", CLEAVE_CAST: "cleave",
    167105: "cs",        # 거인의 강타
    BLADESTORM: "bladestorm",
    260708: "sweep",     # 휩쓸기 일격
    107574: "avatar",    # 투신
}
# 비순환/이동/유틸(글쿨 밖 포함) — 상태별 '선택' 분포에서 제외
EXCLUDE = {6552, 23920, 355, 100, 126664, 97462, 118038, 52174, 57755,
           6673, 202168, 20572, 12323, 384110, 2565, 1236994, 1236616,
           1234768, 386208, 107570}

HS_BUFF = 1269391   # 전쟁의 지배자 프록
SD_BUFF = 52437     # 급살
EP_BUFF = 386633    # 집행자의 정밀함

BS_AUTO_WIN = 4750  # 칼폭 후 이 창 안의 12294 = 불안정한 정신 자동 시전으로 간주
GCD_MS = 1500
FLAT_THR = 5000     # 민감도 비교용 고정 임계값


def build_intervals(events, buff_id, t0):
    iv, start = [], None
    for ev in events:
        t, bid, typ = ev[0], ev[1], ev[2]
        if bid != buff_id:
            continue
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


def build_stacks(events, buff_id, t0):
    tl, cur = [(t0 - 1, 0)], 0
    for ev in events:
        t, bid, typ = ev[0], ev[1], ev[2]
        if bid != buff_id:
            continue
        if typ == "applybuff":
            cur = 1
        elif typ == "removebuff":
            cur = 0
        elif typ in ("applybuffstack", "removebuffstack"):
            cur = ev[4] if len(ev) > 4 else cur
        elif typ == "refreshbuff":
            continue
        tl.append((t, cur))
    return tl


def active_at(iv, t):
    return any(a <= t <= b for a, b in iv)


def stacks_at(tl, t):
    s = 0
    for tt, v in tl:
        if tt <= t:
            s = v
        else:
            break
    return s


def pack(counter):
    n = sum(counter.values())
    if n == 0:
        return {"n": 0}
    out = {"n": n}
    for btn, c in counter.most_common():
        out[btn] = {"count": c, "pct": round(100.0 * c / n, 1)}
    return out


def run(slayer, mode):
    """mode: 'adaptive'(킬별 p25 쿨 추정) | 'flat'(5.0초 고정)."""
    bins = defaultdict(Counter)
    e_bin = defaultdict(Counter)
    f_bin, f_ref = Counter(), Counter()
    other_ids = Counter()
    thr_used = []

    for kill, v in slayer.items():
        casts = sorted(v["casts"], key=lambda c: c[0])
        buffs = sorted(v["buffs"], key=lambda b: b[0])
        if not casts:
            continue
        t0 = min(casts[0][0], buffs[0][0] if buffs else casts[0][0])
        t1 = casts[-1][0]
        exec_start = t0 + 0.75 * (t1 - t0)

        hs_iv = build_intervals(buffs, HS_BUFF, t0)
        sd_iv = build_intervals(buffs, SD_BUFF, t0)
        ep_tl = build_stacks(buffs, EP_BUFF, t0)

        bs_times = [c[0] for c in casts if c[1] == BLADESTORM]

        def is_auto_ms(t):
            return any(0 <= t - b <= BS_AUTO_WIN for b in bs_times)

        manual_ms = [c[0] for c in casts if c[1] == MS_CAST and not is_auto_ms(c[0])]
        if mode == "adaptive":
            gaps = [b - a for a, b in zip(manual_ms, manual_ms[1:]) if 2500 <= b - a <= 9000]
            if len(gaps) >= 8:
                gaps.sort()
                thr = min(max(gaps[len(gaps) // 4], 3600), 5500)
            else:
                thr = 4600
        else:
            thr = FLAT_THR
        thr_used.append(thr)

        last_ms = None
        for c in casts:
            t, sid = c[0], c[1]
            if sid in EXCLUDE:
                continue
            if sid == MS_CAST and is_auto_ms(t):
                continue  # 불안정한 정신 자동 시전 — 버튼 입력 아님
            btn = BUTTONS.get(sid, "other")
            if btn == "other":
                other_ids[sid] += 1
            eps = t - 1
            hs = active_at(hs_iv, eps)
            sd = active_at(sd_iv, eps)
            msr = last_ms is None or (t - last_ms) >= thr
            ep2 = stacks_at(ep_tl, eps) >= 2
            phase = "exec" if t >= exec_start else "normal"

            bins[(hs, msr, sd, phase)][btn] += 1
            if hs and msr:
                e_bin[phase][btn] += 1
            if msr and phase == "exec":
                (f_bin if ep2 else f_ref)[btn] += 1
            if sid == MS_CAST:
                last_ms = t

    return bins, e_bin, f_bin, f_ref, other_ids, thr_used


def colossus_quick(data):
    """거신 소분석 — 마무리 일격 163201, 칼폭 없음(불안정한 정신 미채택).
    주의: 전투군주(386630, 거신 100%)가 제압으로 필사 쿨을 35% 확률 초기화하므로
    간격 기반 msr 근사가 학살자보다 훨씬 약함(리셋된 준비 상태를 X로 오판)."""
    kills = {k: v for k, v in data.items()
             if not any(c[1] == BLADESTORM for c in v["casts"])
             and any(c[1] == 163201 for c in v["casts"])}
    EX = 163201
    btn_map = dict(BUTTONS)
    btn_map[EX] = "execute"
    btn_map[436358] = "demolish"  # 쇄파
    bins = defaultdict(Counter)
    e_bin = Counter()
    for kill, v in kills.items():
        casts = sorted(v["casts"], key=lambda c: c[0])
        buffs = sorted(v["buffs"], key=lambda b: b[0])
        if not casts:
            continue
        t0 = min(casts[0][0], buffs[0][0] if buffs else casts[0][0])
        hs_iv = build_intervals(buffs, HS_BUFF, t0)
        sd_iv = build_intervals(buffs, SD_BUFF, t0)
        ms_t = [c[0] for c in casts if c[1] == MS_CAST]
        gaps = sorted(b - a for a, b in zip(ms_t, ms_t[1:]) if 2500 <= b - a <= 9000)
        thr = min(max(gaps[len(gaps) // 4], 3600), 5500) if len(gaps) >= 8 else 4600
        last_ms = None
        for c in casts:
            t, sid = c[0], c[1]
            if sid in EXCLUDE:
                continue
            btn = btn_map.get(sid, "other")
            eps = t - 1
            hs = active_at(hs_iv, eps)
            sd = active_at(sd_iv, eps)
            msr = last_ms is None or (t - last_ms) >= thr
            key = ("hs" if hs else
                   "msr" if msr else
                   "sd" if sd else "none")
            bins[key][btn] += 1
            if hs and msr:
                e_bin[btn] += 1
            if sid == MS_CAST:
                last_ms = t
    return {
        "n_kills": len(kills),
        "note": "우선 상태 1개로 접은 요약(hs > msr > sd > none). 전투군주 리셋 때문에 msr 근사 오차 큼 — 참고용.",
        "A_hs_active": pack(bins["hs"]),
        "B_hsX_msrO": pack(bins["msr"]),
        "C_hsX_msrX_sdO": pack(bins["sd"]),
        "D_all_X": pack(bins["none"]),
        "E_hsO_msrO": pack(e_bin),
    }


def main():
    data = json.load(open(SCRATCH, encoding="utf-8"))
    slayer = {k: v for k, v in data.items()
              if any(c[1] == BLADESTORM for c in v["casts"])}

    # A. 프록 소모 지표 (임계값 무관)
    hs_consume = {"n_procs": 0, "consumed": 0, "within_1gcd": 0, "delays": []}
    clean_gaps = []
    for kill, v in slayer.items():
        casts = sorted(v["casts"], key=lambda c: c[0])
        buffs = sorted(v["buffs"], key=lambda b: b[0])
        bs_times = [c[0] for c in casts if c[1] == BLADESTORM]
        hs_casts = [c[0] for c in casts if c[1] == HS_CAST]
        applies = [b[0] for b in buffs if b[1] == HS_BUFF and b[2] == "applybuff"]
        removes = [b[0] for b in buffs if b[1] == HS_BUFF and b[2] == "removebuff"]
        for ap in applies:
            hs_consume["n_procs"] += 1
            rm = next((r for r in removes if r >= ap), float("inf"))
            nxt = next((h for h in hs_casts if h >= ap), None)
            if nxt is not None and nxt <= rm + 150:
                hs_consume["consumed"] += 1
                d = nxt - ap
                hs_consume["delays"].append(d)
                if d <= GCD_MS:
                    hs_consume["within_1gcd"] += 1
        manual_ms = [c[0] for c in casts if c[1] == MS_CAST
                     and not any(0 <= c[0] - b <= BS_AUTO_WIN for b in bs_times)]
        clean_gaps += [b - a for a, b in zip(manual_ms, manual_ms[1:])]

    bins, e_bin, f_bin, f_ref, other_ids, thr_used = run(slayer, "adaptive")
    fbins, fe_bin, ff_bin, ff_ref, _, _ = run(slayer, "flat")

    def merged(b, hs, msr, sd):
        c = Counter()
        for ph in ("normal", "exec"):
            c += b[(hs, msr, sd, ph)]
        return c

    def view(b, e):
        return {
            "A_next_button_when_hs": pack(
                merged(b, True, True, True) + merged(b, True, True, False)
                + merged(b, True, False, True) + merged(b, True, False, False)),
            "B_hsX_msrO": {
                "all": pack(merged(b, False, True, True) + merged(b, False, True, False)),
                "normal": pack(b[(False, True, True, "normal")] + b[(False, True, False, "normal")]),
                "exec": pack(b[(False, True, True, "exec")] + b[(False, True, False, "exec")]),
            },
            "C_hsX_msrX_sdO": {
                "all": pack(merged(b, False, False, True)),
                "normal": pack(b[(False, False, True, "normal")]),
                "exec": pack(b[(False, False, True, "exec")]),
            },
            "D_hsX_msrX_sdX": {
                "all": pack(merged(b, False, False, False)),
                "normal": pack(b[(False, False, False, "normal")]),
                "exec": pack(b[(False, False, False, "exec")]),
            },
            "E_hsO_msrO": {ph: pack(e[ph]) for ph in ("normal", "exec")},
            "E_hsO_msrO_all": pack(e["normal"] + e["exec"]),
        }

    clean_gaps.sort()
    n = len(clean_gaps)
    result = {
        "_meta": {
            "generated_by": "tmp_mine_arms_procprio.py",
            "input": "scratchpad arms_cd_events.json — top100 296킬 중 학살자 %d킬(칼날폭풍 446035 시전 기준)" % len(slayer),
            "state_defs": {
                "hs": "전쟁의 지배자 프록 1269391 활성 (시전 1ms 전 기준)",
                "msr": "필사의 일격 준비 근사 — 마지막 수동 12294 후 경과 >= 킬별 추정 쿨(깨끗한 간격 p25, 3600~5500ms 클램프)",
                "sd": "급살 52437 활성",
                "ep2": "집행자의 정밀함 386633 >= 2중첩",
                "phase": "exec = 전투 시간 마지막 25% (대학살 HP<35%의 시간 근사)",
            },
            "buttons": {v: k for k, v in BUTTONS.items()},
            "bladestorm_auto_ms": "불안정한 정신(109815) 때문에 칼폭 후 %dms 안의 12294는 자동 시전으로 간주해 제외 — 칼폭 기준 0.5/1.5/2.5/3.5/4.5초 틱 실측" % BS_AUTO_WIN,
            "ms_ready_thr_ms": {"med": median(thr_used), "min": min(thr_used), "max": max(thr_used)},
            "caveats": [
                "필사 준비는 시전 간격 기반 근사 — 가속 변동(격렬한 희열 등) 창에서 오차. 5.0초 고정 임계값 결과를 sensitivity_flat5000에 병기.",
                "분노는 이벤트에 없음 — D 조합(모든 프록 X)의 분포는 분노 상태 미상. 단정 대신 분포 그대로 보고.",
                "처형구간은 HP가 아닌 시간(마지막 25%) 근사.",
                "칼폭 창 끝자락(4.5~4.75초)의 진짜 수동 필사(잔혹한 마무리 연계)도 일부 같이 제외됨 — 표본 손실이며 편향은 작음.",
            ],
        },
        "A_hs_proc_consumption": {
            "n_procs": hs_consume["n_procs"],
            "consumed_pct": round(100.0 * hs_consume["consumed"] / max(1, hs_consume["n_procs"]), 1),
            "within_1gcd_pct_of_consumed": round(100.0 * hs_consume["within_1gcd"] / max(1, hs_consume["consumed"]), 1),
            "consume_delay_ms_med": median(hs_consume["delays"]) if hs_consume["delays"] else None,
        },
        **view(bins, e_bin),
        "F_ep2_msrO_exec": pack(f_bin),
        "F_ref_epLT2_msrO_exec": pack(f_ref),
        "manual_ms_gap_ms": {
            "n": n,
            "p10": clean_gaps[int(0.10 * n)] if n else None,
            "p25": clean_gaps[int(0.25 * n)] if n else None,
            "med": median(clean_gaps) if n else None,
        },
        "other_cast_ids_top": dict(other_ids.most_common(15)),
        "sensitivity_flat5000": {
            "B_hsX_msrO_all": pack(merged(fbins, False, True, True) + merged(fbins, False, True, False)),
            "D_hsX_msrX_sdX_all": pack(merged(fbins, False, False, False)),
            "E_hsO_msrO_all": pack(fe_bin["normal"] + fe_bin["exec"]),
            "F_ep2_msrO_exec": pack(ff_bin),
        },
        "full_state_table": {
            "hs=%d,msr=%d,sd=%d,%s" % (h, m, s, ph): pack(bins[(bool(h), bool(m), bool(s), ph)])
            for h in (0, 1) for m in (0, 1) for s in (0, 1) for ph in ("normal", "exec")
        },
        "colossus_side_note": colossus_quick(data),
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("saved", OUT)
    keys = ["A_hs_proc_consumption", "A_next_button_when_hs", "B_hsX_msrO",
            "C_hsX_msrX_sdO", "D_hsX_msrX_sdX", "E_hsO_msrO_all", "E_hsO_msrO",
            "F_ep2_msrO_exec", "F_ref_epLT2_msrO_exec", "manual_ms_gap_ms",
            "sensitivity_flat5000"]
    print(json.dumps({k: result[k] for k in keys}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
