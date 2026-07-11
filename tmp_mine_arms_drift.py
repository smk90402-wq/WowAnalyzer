# -*- coding: utf-8 -*-
"""Arms Slayer cooldown-drift mining.

Reads scratchpad arms_cd_events.json (read-only), writes data/arms_cd_drift.json.

Approximations (no resource/CD data available):
- Avatar(107574) window: cast +20s (cross-checked against real applybuff/removebuff pairs).
- Colossus Smash / Warbreaker debuff(167105) window: cast +10s AND +15s (tier extension), both reported.
- Bladestorm(446035) effective CD ~36s; a gap >= 56s (36+20) counts as a "hold".
Fight-relative time = timestamp - first cast in the kill.
"""
import json
import os
import statistics

SRC = r"C:\Users\MKSEORTV\AppData\Local\Temp\claude\C--Users-MKSEORTV-Desktop-WowAnalyzer\30b0abb8-5226-4b13-9c1c-14e4a1562211\scratchpad\arms_cd_events.json"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "arms_cd_drift.json")

AVATAR = 107574
CS = 167105
BS = 446035
AV_WIN = 20.0
CS_WINS = (10.0, 15.0)
BS_HOLD = 56.0  # 36s effective CD + 20s slack


def dist(vals, bins):
    """bins: list of (label, lo, hi) half-open [lo, hi)."""
    out = {label: 0 for label, _, _ in bins}
    for v in vals:
        for label, lo, hi in bins:
            if lo <= v < hi:
                out[label] += 1
                break
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


def last_before(times, t):
    """Largest x in sorted times with x <= t, else None."""
    prev = None
    for x in times:
        if x <= t:
            prev = x
        else:
            break
    return prev


def main():
    data = json.load(open(SRC, encoding="utf-8"))
    kills = {}
    for key, v in data.items():
        casts = sorted(v["casts"], key=lambda c: c[0])
        if not any(c[1] == BS for c in casts):
            continue
        t0 = casts[0][0]
        av = [(c[0] - t0) / 1000.0 for c in casts if c[1] == AVATAR]
        cs = [(c[0] - t0) / 1000.0 for c in casts if c[1] == CS]
        bs = [(c[0] - t0) / 1000.0 for c in casts if c[1] == BS]
        # real avatar buff intervals (applybuff -> removebuff)
        av_ivals = []
        start = None
        for b in sorted(v["buffs"], key=lambda b: b[0]):
            if b[1] != AVATAR:
                continue
            t = (b[0] - t0) / 1000.0
            if b[2] == "applybuff":
                start = t
            elif b[2] == "removebuff" and start is not None:
                av_ivals.append((start, t))
                start = None
        if start is not None:
            av_ivals.append((start, start + AV_WIN))  # truncated by fight end
        kills[key] = {"av": av, "cs": cs, "bs": bs, "av_ivals": av_ivals}

    res = {"n_kills": len(kills),
           "assumptions": {"avatar_window_s": AV_WIN, "cs_windows_s": list(CS_WINS),
                           "bs_effective_cd_s": 36, "bs_hold_threshold_s": BS_HOLD,
                           "fight_time_zero": "first cast in kill"}}

    time_bins = [("0-30s", 0, 30), ("30-120s", 30, 120), ("120s+", 120, float("inf"))]

    def tbin(t):
        for label, lo, hi in time_bins:
            if lo <= t < hi:
                return label

    # ---------- Q1: CS casts vs Avatar window ----------
    cs_dts = []           # elapsed since last avatar cast (None = no prior avatar)
    cs_in_buf = 0         # inside a real avatar buff interval
    cs_total = 0
    q1_by_bin = {label: {"n": 0, "in20": 0} for label, _, _ in time_bins}
    for k in kills.values():
        for t in k["cs"]:
            cs_total += 1
            prev = last_before(k["av"], t)
            dt = None if prev is None else t - prev
            cs_dts.append(dt)
            if any(a <= t <= b for a, b in k["av_ivals"]):
                cs_in_buf += 1
            b = q1_by_bin[tbin(t)]
            b["n"] += 1
            if dt is not None and dt <= AV_WIN:
                b["in20"] += 1
    have = [d for d in cs_dts if d is not None]
    n_in20 = sum(1 for d in have if d <= AV_WIN)
    res["q1_cs_vs_avatar"] = {
        "n_cs_casts": cs_total,
        "no_prior_avatar": cs_total - len(have),
        "in_avatar_cast20_n": n_in20,
        "in_avatar_cast20_rate": round(n_in20 / cs_total, 3),
        "in_avatar_realbuff_n": cs_in_buf,
        "in_avatar_realbuff_rate": round(cs_in_buf / cs_total, 3),
        "elapsed_since_avatar_dist": dist(have, [
            ("0-5s", 0, 5), ("5-10s", 5, 10), ("10-15s", 10, 15), ("15-20s", 15, 20),
            ("20-30s", 20, 30), ("30-40s", 30, 40), ("40s+", 40, float("inf"))]),
        "elapsed_since_avatar_summary": summ(have),
    }

    # ---------- Q2: Avatar timing relative to CS ----------
    deltas = []  # avatar_t - nearest cs_t
    for k in kills.values():
        for t in k["av"]:
            if not k["cs"]:
                deltas.append(None)
                continue
            nearest = min(k["cs"], key=lambda c: abs(c - t))
            deltas.append(t - nearest)
    have_d = [d for d in deltas if d is not None]
    sync3 = sum(1 for d in have_d if abs(d) <= 3)
    after03 = sum(1 for d in have_d if 0 <= d <= 3)
    res["q2_avatar_vs_cs"] = {
        "n_avatar_casts": len(deltas),
        "no_cs_in_kill": len(deltas) - len(have_d),
        "delta_dist_avatar_minus_cs": dist(have_d, [
            ("<-10s (avatar way first)", -float("inf"), -10),
            ("-10..-3s", -10, -3), ("-3..0s (avatar just first)", -3, 0),
            ("0..1s", 0, 1), ("1..3s", 1, 3), ("3..10s", 3, 10),
            (">10s (avatar way after)", 10, float("inf"))]),
        "synced_abs3_rate": round(sync3 / len(have_d), 3),
        "avatar_0to3_after_cs_rate": round(after03 / len(have_d), 3),
    }
    # avatar cycle gaps: did delayed (>=65s) avatars land synced with CS?
    cyc = {"normal_lt65": {"n": 0, "synced3": 0}, "delayed_ge65": {"n": 0, "synced3": 0}}
    gap_vals = []
    for k in kills.values():
        for a, b in zip(k["av"], k["av"][1:]):
            gap = b - a
            gap_vals.append(gap)
            key = "delayed_ge65" if gap >= 65 else "normal_lt65"
            cyc[key]["n"] += 1
            if k["cs"] and abs(min(k["cs"], key=lambda c: abs(c - b)) - b) <= 3:
                cyc[key]["synced3"] += 1
    for v in cyc.values():
        v["synced3_rate"] = round(v["synced3"] / v["n"], 3) if v["n"] else None
    res["q2_avatar_cycles"] = {"gap_summary": summ(gap_vals), "by_cycle": cyc}

    # ---------- Q3: Bladestorm companionship ----------
    q3 = {}
    bs_total = sum(len(k["bs"]) for k in kills.values())
    q4_bs = {w: {label: {"n": 0, "both": 0, "cs_only": 0, "outside_cs": 0}
                 for label, _, _ in time_bins} for w in CS_WINS}
    for w in CS_WINS:
        cls = {"both": 0, "cs_only": 0, "av_only": 0, "neither": 0}
        solo_since_cs = []
        for k in kills.values():
            for t in k["bs"]:
                in_cs = any(0 <= t - c <= w for c in k["cs"])
                in_av = any(0 <= t - a <= AV_WIN for a in k["av"])
                if in_cs and in_av:
                    c4 = "both"
                elif in_cs:
                    c4 = "cs_only"
                elif in_av:
                    c4 = "av_only"
                else:
                    c4 = "neither"
                cls[c4] += 1
                bb = q4_bs[w][tbin(t)]
                bb["n"] += 1
                bb["both" if c4 == "both" else ("cs_only" if c4 == "cs_only" else "outside_cs")] += 1
                if not in_cs:
                    prev = last_before(k["cs"], t)
                    solo_since_cs.append(None if prev is None else t - prev)
        have_s = [d for d in solo_since_cs if d is not None]
        q3[f"cs_window_{int(w)}s"] = {
            "both_avatar_and_cs": cls["both"],
            "cs_only": cls["cs_only"],
            "avatar_only_no_cs": cls["av_only"],
            "neither": cls["neither"],
            "rates": {kk: round(vv / bs_total, 3) for kk, vv in cls.items()},
            "outside_cs_rate": round((cls["av_only"] + cls["neither"]) / bs_total, 3),
            "solo_elapsed_since_cs_dist": dist(have_s, [
                (f"{int(w)}-15s", w, 15), ("15-20s", 15, 20), ("20-30s", 20, 30),
                ("30-45s", 30, 45), ("45s+", 45, float("inf"))]),
            "solo_no_prior_cs": len(solo_since_cs) - len(have_s),
            "solo_elapsed_summary": summ(have_s),
        }
    res["q3_bladestorm_classes"] = {"n_bs_casts": bs_total, **q3}

    # ---------- Q4: by fight-time bin ----------
    for label in q1_by_bin:
        b = q1_by_bin[label]
        b["in20_rate"] = round(b["in20"] / b["n"], 3) if b["n"] else None
    for w in CS_WINS:
        for label, b in q4_bs[w].items():
            if b["n"]:
                for kk in ("both", "cs_only", "outside_cs"):
                    b[kk + "_rate"] = round(b[kk] / b["n"], 3)
    # cast intervals per bin (attributed to the later cast)
    ivals = {label: {"cs": [], "bs": []} for label, _, _ in time_bins}
    for k in kills.values():
        for a, b in zip(k["cs"], k["cs"][1:]):
            ivals[tbin(b)]["cs"].append(b - a)
        for a, b in zip(k["bs"], k["bs"][1:]):
            ivals[tbin(b)]["bs"].append(b - a)
    q4_ivals = {}
    for label, v in ivals.items():
        q4_ivals[label] = {
            "cs_interval": summ(v["cs"]),
            "cs_interval_gt55s_n": sum(1 for x in v["cs"] if x > 55),
            "bs_interval": summ(v["bs"]),
            "bs_interval_gt56s_n": sum(1 for x in v["bs"] if x > BS_HOLD),
        }
    res["q4_by_fight_time"] = {
        "q1_cs_in_avatar20": q1_by_bin,
        "q3_bs_classes": {f"cs_window_{int(w)}s": q4_bs[w] for w in CS_WINS},
        "cast_intervals": q4_ivals,
    }

    # ---------- Q5: Bladestorm holds -> realignment ----------
    # Note: assumed effective CD 36s turned out unrealistic; observed cadence
    # median ~58s. Report both spec threshold (56s) and data-driven (78s).
    all_gaps = []
    pairs = []  # (gap, end_alignment flags)
    for k in kills.values():
        for a, b in zip(k["bs"], k["bs"][1:]):
            gap = b - a
            all_gaps.append(gap)
            pairs.append((gap,
                          any(0 <= b - c <= 10 for c in k["cs"]),
                          any(0 <= b - c <= 15 for c in k["cs"]),
                          any(0 <= b - a2 <= AV_WIN for a2 in k["av"])))

    def hold_analysis(thr):
        hold = {"n": 0, "in_cs10": 0, "in_cs15": 0, "in_av20": 0}
        norm = {"n": 0, "in_cs10": 0, "in_cs15": 0, "in_av20": 0}
        hgaps = []
        for gap, c10, c15, av in pairs:
            tgt = hold if gap >= thr else norm
            tgt["n"] += 1
            tgt["in_cs10"] += c10
            tgt["in_cs15"] += c15
            tgt["in_av20"] += av
            if gap >= thr:
                hgaps.append(gap)
        for tgt in (hold, norm):
            for kk in ("in_cs10", "in_cs15", "in_av20"):
                tgt[kk + "_rate"] = round(tgt[kk] / tgt["n"], 3) if tgt["n"] else None
        return {"threshold_s": thr, "holds_n": hold["n"],
                "holds_share": round(hold["n"] / len(pairs), 3) if pairs else None,
                "hold_gap_summary": summ(hgaps),
                "hold_end_alignment": hold, "normal_end_alignment": norm}

    res["q5_bs_holds"] = {
        "n_bs_intervals": len(all_gaps),
        "gap_summary": summ(all_gaps),
        "gap_histogram": dist(all_gaps, [
            ("<40s", 0, 40), ("40-50s", 40, 50), ("50-56s", 50, 56),
            ("56-65s", 56, 65), ("65-78s", 65, 78), ("78-100s", 78, 100),
            ("100s+", 100, float("inf"))]),
        "spec_threshold_56s": hold_analysis(BS_HOLD),
        "data_threshold_78s": hold_analysis(78.0),
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
