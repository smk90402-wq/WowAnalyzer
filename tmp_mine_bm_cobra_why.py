# -*- coding: utf-8 -*-
"""BM 필러 미스터리 규명 — '날사 충전이 있어도 왜 코브라 먼저?'

가설 3개를 top100 신화 362킬 실측(스크래치패드 bm_alt_events.json 재사용)으로 판정:
  H1 광기 페이싱 — 날사가 펫 광기 유지를 위해 균등 간격으로 쓰인다?
  H2 쿨감 낭비 방지 — 살상 직후=날사 / 살상 직전=코브라 가 최적이라 그렇게 친다?
  H3 조련술의 거장(42%) 채택자와 미채택자의 필러 패턴이 다르다?
+ 트리 기반 집중 경제 해석.

출력: data/bm_cobra_why.json  (기존 파일 수정 없음, WCL API 사용 없음)
"""
from __future__ import annotations
import json, sys, csv, re, statistics
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze\data")
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")

KC = 34026        # 살상 명령
BARB = 217200     # 날카로운 사격
COBRA = 193455    # 코브라 사격
BW = 19574        # 야수의 격노
FRENZY = 272790   # 광기 (공속 20% 버프)

# 특성 노드
N_MASTER = 102359     # 조련술의 거장: 날사 출혈 틱당 살명 쿨 -0.5s
N_WAR = 102343        # 전쟁 명령: 날사 사용 시 살명 쿨 -3s
N_SCALES = 102353     # 날카로운 비늘: 코브라 시전 시 날사 쿨 -2s
N_ALPHA = 102368      # 우두머리 포식자: 살명 2충전
N_SCENT = 102342      # 피의 향기: 격노 시 날사 +1충전
N_PACK = 102374       # 무리 전술: 날사 즉시 집중 25
N_VIPER = 102372      # 독사의 일격: 코브라 치명타 시 집중 10 반환
N_KCOBRA = 102375     # 살상 코브라: 격노 중 코브라가 살명 쿨 초기화
N_CHOICE_CQ = 102344  # 선택: 뱀가죽 화살통 / 코브라 감각(-5 집중)
N_DIRECMD = 102365    # 광포한 명령: 살명 20% 확률 광포한 야수 소환

BOSS_KO = {3176: "아베르지안", 3177: "보라시우스", 3178: "바엘고어", 3179: "살라다르",
           3180: "선봉대", 3181: "우주의왕관", 3182: "벨로렌", 3183: "한밤의도래(르우라)",
           3306: "카이메루스"}

TSK_BUCKETS = [(0, 1.5), (1.5, 3.0), (3.0, 4.5), (4.5, 7.0), (7.0, 999)]


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
        nodes = set(p.get("nodes") or [])
        wanted[key] = {
            "boss": BOSS_KO.get(int(r["encounter_id"]), r["encounter_name"]),
            "rank": int(r["rank"]), "char": ch,
            "t0": f["startTime"], "t1": f["endTime"],
            "master": N_MASTER in nodes,
            "nodes": nodes, "talents": set(p.get("talents") or []),
        }
    return wanted


def detect_offgcd(fights):
    dt_by_id = defaultdict(list)
    for casts in fights:
        for i in range(1, len(casts)):
            dt = (casts[i][0] - casts[i-1][0]) / 1000
            dt_by_id[casts[i][1]].append(dt)
    off = set()
    for sid, dts in dt_by_id.items():
        if len(dts) < 50: continue
        if sum(1 for d in dts if d < 0.6) / len(dts) > 0.5:
            off.add(sid)
    return off


def pct(vals, q):
    if not vals: return None
    v = sorted(vals)
    idx = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return round(v[idx], 2)


def bucket_label(x):
    for lo, hi in TSK_BUCKETS:
        if lo <= x < hi:
            return f"{lo}-{hi}s" if hi < 999 else f"{lo}s+"
    return None


def analyze_fight(casts, t0, t1, offgcd):
    seq = sorted((t, i) for t, i in casts if t >= t0 - 1000)
    gseq = [(t, i) for t, i in seq if i not in offgcd]
    dur = (t1 - t0) / 1000
    r = {"dur": dur,
         "single": Counter(), "first": Counter(), "last": Counter(), "mid": Counter(),
         "tsk": defaultdict(Counter), "ttk": defaultdict(Counter),
         "barb_gaps": [], "cobra_gaps": [],
         "barb_n": 0, "cobra_n": 0, "kc_n": 0,
         "bunch_pairs": 0, "bunch_near_bw": 0,
         "bw_n": 0, "barb_in_bw8": 0, "bw8_time": 0.0,
         "kc_gaps_gt_75": 0, "kc_gaps_n": 0}
    kc_idx = [k for k, (t, i) in enumerate(gseq) if i == KC]
    r["kc_n"] = len(kc_idx)
    for a, b in zip(kc_idx, kc_idx[1:]):
        ta, tb = gseq[a][0], gseq[b][0]
        r["kc_gaps_n"] += 1
        if (tb - ta) / 1000 > 7.5: r["kc_gaps_gt_75"] += 1
        fillers = [(t, i) for t, i in gseq[a+1:b] if i in (BARB, COBRA)]
        if len(fillers) == 1:
            r["single"][fillers[0][1]] += 1
        elif len(fillers) >= 2:
            r["first"][fillers[0][1]] += 1
            r["last"][fillers[-1][1]] += 1
            for t, i in fillers[1:-1]:
                r["mid"][i] += 1
        # 위치 그라디언트(2개 이상 창만: 순서 선택이 실제로 존재했던 창)
        if len(fillers) >= 2:
            for t, i in fillers:
                tsk = (t - ta) / 1000
                ttk = (tb - t) / 1000
                bl = bucket_label(tsk)
                if bl: r["tsk"][bl][i] += 1
                bl = bucket_label(ttk)
                if bl: r["ttk"][bl][i] += 1
    barb_ts = [t for t, i in gseq if i == BARB]
    cobra_ts = [t for t, i in gseq if i == COBRA]
    bw_ts = [t for t, i in gseq if i == BW]
    r["barb_n"], r["cobra_n"], r["bw_n"] = len(barb_ts), len(cobra_ts), len(bw_ts)
    r["barb_gaps"] = [(b - a) / 1000 for a, b in zip(barb_ts, barb_ts[1:])]
    r["cobra_gaps"] = [(b - a) / 1000 for a, b in zip(cobra_ts, cobra_ts[1:])]
    # 몰아쓰기(날사 간격 <=2.6s = 사실상 연속 글쿨)와 격노 근접성
    for a, b in zip(barb_ts, barb_ts[1:]):
        if (b - a) / 1000 <= 2.6:
            r["bunch_pairs"] += 1
            if any(0 <= (a - w) / 1000 <= 8 or 0 <= (b - w) / 1000 <= 8 for w in bw_ts):
                r["bunch_near_bw"] += 1
    # 격노 후 8초 창의 날사 밀도
    for w in bw_ts:
        hi = min(w + 8000, t1)
        r["bw8_time"] += max(0.0, (hi - w) / 1000)
        r["barb_in_bw8"] += sum(1 for t in barb_ts if w <= t <= hi)
    return r


def cv(gaps):
    g = [x for x in gaps if 0.5 <= x <= 20]
    if len(g) < 8: return None
    m = statistics.mean(g)
    return statistics.stdev(g) / m if m else None


def norm_share(counter):
    b, c = counter.get(BARB, 0), counter.get(COBRA, 0)
    tot = b + c
    return {"barbed": b, "cobra": c,
            "barbed_pct": round(100 * b / tot, 1) if tot else None}


def agg(items):
    if not items: return None
    tot_min = sum(r["dur"] for _, r in items) / 60
    single = Counter(); first = Counter(); last = Counter(); mid = Counter()
    tsk = defaultdict(Counter); ttk = defaultdict(Counter)
    for _, r in items:
        single.update(r["single"]); first.update(r["first"]); last.update(r["last"]); mid.update(r["mid"])
        for bl, c in r["tsk"].items(): tsk[bl].update(c)
        for bl, c in r["ttk"].items(): ttk[bl].update(c)
    barb_gaps = [g for _, r in items for g in r["barb_gaps"]]
    cvs_b = [cv(r["barb_gaps"]) for _, r in items]
    cvs_b = [x for x in cvs_b if x is not None]
    cvs_c = [cv(r["cobra_gaps"]) for _, r in items]
    cvs_c = [x for x in cvs_c if x is not None]
    bunch = sum(r["bunch_pairs"] for _, r in items)
    bunch_bw = sum(r["bunch_near_bw"] for _, r in items)
    bw8_t = sum(r["bw8_time"] for _, r in items)
    barb_bw8 = sum(r["barb_in_bw8"] for _, r in items)
    barb_n = sum(r["barb_n"] for _, r in items)
    tot_s = sum(r["dur"] for _, r in items)
    out_rate = (barb_n - barb_bw8) / max(1e-9, tot_s - bw8_t) * 60
    in_rate = barb_bw8 / max(1e-9, bw8_t) * 60
    kcg = sum(r["kc_gaps_n"] for _, r in items)
    kcg75 = sum(r["kc_gaps_gt_75"] for _, r in items)
    return {
        "n_fights": len(items),
        "rates_per_min": {
            "kill_command": round(sum(r["kc_n"] for _, r in items) / tot_min, 2),
            "barbed": round(barb_n / tot_min, 2),
            "cobra": round(sum(r["cobra_n"] for _, r in items) / tot_min, 2),
            "bestial_wrath": round(sum(r["bw_n"] for _, r in items) / tot_min, 2),
        },
        "window_slots": {
            "note": "살명→살명 사이 창에서 날사/코브라만 셈. single=필러 1개뿐인 창(순서 선택 불가), first/last=필러 2개 이상 창의 첫/마지막 슬롯",
            "single": norm_share(single),
            "first_slot": norm_share(first),
            "mid_slots": norm_share(mid),
            "last_slot": norm_share(last),
        },
        "tsk_gradient": {bl: norm_share(tsk[bl]) for bl in sorted(tsk, key=lambda s: float(s.split("-")[0].rstrip("s+")))},
        "ttk_gradient": {bl: norm_share(ttk[bl]) for bl in sorted(ttk, key=lambda s: float(s.split("-")[0].rstrip("s+")))},
        "barbed_spacing": {
            "gap_p25_s": pct(barb_gaps, 0.25), "gap_median_s": pct(barb_gaps, 0.5),
            "gap_p75_s": pct(barb_gaps, 0.75), "gap_p90_s": pct(barb_gaps, 0.9),
            "cv_median": round(statistics.median(cvs_b), 3) if cvs_b else None,
            "cobra_cv_median": round(statistics.median(cvs_c), 3) if cvs_c else None,
            "n_gaps": len(barb_gaps),
        },
        "bunching": {
            "pairs_le_2p6s": bunch,
            "pairs_per_min": round(bunch / tot_min, 2),
            "near_bw_pct": round(100 * bunch_bw / bunch, 1) if bunch else None,
            "bw8_share_of_time_pct": round(100 * bw8_t / tot_s, 1),
        },
        "barbed_rate_in_bw8_vs_out": {
            "in_bw_8s_per_min": round(in_rate, 2),
            "outside_per_min": round(out_rate, 2),
            "ratio": round(in_rate / out_rate, 2) if out_rate else None,
        },
        "kc_gap_gt_7p5s_pct": round(100 * kcg75 / kcg, 1) if kcg else None,
    }


def frenzy_attribution(ev, db):
    """광기 applybuff가 어떤 시전과 붙어 나타나는지 (150ms 최근접)."""
    near = Counter(); total = 0
    for k, e in ev.items():
        casts = e["casts"]
        for b in e.get("buffs", []):
            if b[1] != FRENZY or b[2] != "applybuff": continue
            total += 1
            best = None
            for ct, cid in casts:
                d = abs(ct - b[0])
                if best is None or d < best[0]: best = (d, cid)
            near[best[1] if best and best[0] <= 150 else 0] += 1
    def nm(sid):
        if sid == 0: return "매칭없음(150ms내 시전 없음)"
        v = db.get(str(sid)) or {}
        return f"{v.get('name_ko', sid)}({sid})"
    grouped = Counter()
    for sid, n in near.items():
        name = nm(sid)
        if "광포한 야수" in name: name = "광포한 야수 소환(여러 id)"
        grouped[name] += n
    return {"applybuff_total": total,
            "nearest_cast_within_150ms": {k: v for k, v in grouped.most_common(10)}}


def main():
    wanted = load_wanted()
    ev = json.load(open(SCRATCH / "bm_alt_events.json", encoding="utf-8"))
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    print(f"wanted {len(wanted)}, events {len(ev)}", flush=True)

    usable = [(k, wanted[k]) for k in ev if k in wanted and len(ev[k].get("casts") or []) >= 30]
    offgcd = detect_offgcd([ev[k]["casts"] for k, _ in usable])

    per = []
    for k, info in usable:
        r = analyze_fight(ev[k]["casts"], info["t0"], info["t1"], offgcd)
        if r["kc_n"] >= 10:
            per.append((info, r))
    print(f"분석 킬: {len(per)}", flush=True)

    # ---- 특성 채택률 (분석 대상 킬 기준) ----
    def adopt(nid):
        n = sum(1 for i, _ in per if nid in i["nodes"])
        return {"n": n, "pct": round(100 * n / len(per), 1)}
    adoption = {
        "전쟁 명령(날사→살명 -3s)": adopt(N_WAR),
        "코브라 사격 내장(코브라→살명 -1s)": {"n": len(per), "pct": 100.0},
        "날카로운 비늘(코브라→날사 쿨 -2s)": adopt(N_SCALES),
        "조련술의 거장(날사 틱당 살명 -0.5s)": adopt(N_MASTER),
        "우두머리 포식자(살명 2충전)": adopt(N_ALPHA),
        "피의 향기(격노 시 날사 +1충전)": adopt(N_SCENT),
        "무리 전술(날사 즉시 집중 25 + 회복 지속효과 +75%)": adopt(N_PACK),
        "독사의 일격(코브라 치명타 시 집중 10 반환)": adopt(N_VIPER),
        "살상 코브라(격노 중 코브라=살명 초기화)": adopt(N_KCOBRA),
        "광포한 명령(살명 20% 광포한 야수 소환)": adopt(N_DIRECMD),
        "note": "선택 노드(102344 뱀가죽/코브라 감각, 102339 야생의 본능/피의 광란)의 옵션 구분은 캐시의 talents id 체계가 트리 talent_id와 달라 판별 불가",
    }

    # ---- H1: 광기 귀속 + 날사 간격 규칙성 ----
    fr = frenzy_attribution(ev, db)

    # ---- 전체/H3 그룹 집계 ----
    overall = agg(per)
    g_master = agg([(i, r) for i, r in per if i["master"]])
    g_nomaster = agg([(i, r) for i, r in per if not i["master"]])

    # H3 보스 통제: 보스별 날사 비중(필러 중) 비교
    per_boss_h3 = {}
    bosses = defaultdict(lambda: {"m": [], "n": []})
    for i, r in per:
        bosses[i["boss"]]["m" if i["master"] else "n"].append((i, r))
    for boss, d in sorted(bosses.items(), key=lambda x: -(len(x[1]["m"]) + len(x[1]["n"]))):
        row = {}
        for lab, lst in (("master", d["m"]), ("no_master", d["n"])):
            if len(lst) < 5:
                row[lab] = {"n_fights": len(lst)}
                continue
            a = agg(lst)
            row[lab] = {
                "n_fights": a["n_fights"],
                "barbed_per_min": a["rates_per_min"]["barbed"],
                "cobra_per_min": a["rates_per_min"]["cobra"],
                "barbed_gap_median_s": a["barbed_spacing"]["gap_median_s"],
                "single_slot_barbed_pct": a["window_slots"]["single"]["barbed_pct"],
                "first_slot_barbed_pct": a["window_slots"]["first_slot"]["barbed_pct"],
                "last_slot_barbed_pct": a["window_slots"]["last_slot"]["barbed_pct"],
            }
        per_boss_h3[boss] = row

    # ---- 집중 경제 산수 (트리+실측 시전율) ----
    r = overall["rates_per_min"]
    cobra_cost = 35  # 코브라 감각(선택) 채택 시 30 — 채택률은 adoption 참고
    spend = r["kill_command"] * 30 + r["cobra"] * cobra_cost
    barb_income = r["barbed"] * (25 + 20)  # 무리 전술 즉시 25 + 8초 걸쳐 20
    focus = {
        "costs": {"살상 명령": 30, "코브라 사격": cobra_cost, "날카로운 사격": 0},
        "income_static": "날사=무리 전술 즉시 25 + 8초에 걸쳐 20 생성(트리/툴팁). 기본 집중 회복 별도(가속 비례).",
        "per_min_spend_est": round(spend, 0),
        "per_min_barbed_income_est": round(barb_income, 0),
        "gap_to_fill_by_regen_est": round(spend - barb_income, 0),
        "note": "로그에 집중 리소스 이벤트가 없어 실측 불가 — 시전율×툴팁 단가 산수. "
                "살명+코브라 소모(분당 약 1000)를 날사 수입(분당 약 500)만으론 못 채움 → 기본 회복이 마저 채움. "
                "코브라는 유일한 집중 소모 필러, 날사는 생성 필러 — 코브라를 안 치면 집중이 넘치고, 날사를 안 치면 코브라를 못 침(맞물린 경제).",
    }

    out = {
        "meta": {
            "date": "2026-07-04",
            "question": "기계적 최적(날사 우선?)과 실제 행동(충전 있어도 코브라 먼저)이 왜 다른가 — 가설 3개 실측 판정",
            "sample": f"12.0.7 top100 신화 BM {len(per)}킬 (bm_alt_events.json 캐시 재사용)",
            "master_handler_kills": sum(1 for i, _ in per if i["master"]),
            "buckets_note": "tsk=직전 살명으로부터 경과, ttk=다음 살명까지 남은 시간. 그라디언트는 필러 2개 이상 창(순서 선택이 실존)만 집계",
        },
        "talent_adoption": adoption,
        "h1_frenzy_pacing": {
            "premise_check": {
                "tree_scan": "BM 트리(class/spec/hero 전 노드)와 날카로운 사격 툴팁 어디에도 '광기' 없음 — 이번 시즌 날사는 광기를 부여/유지하지 않음",
                "frenzy_tooltip": "광기(272790) = '활성화된 야수의 공격 속도 20% 증가' (스택 문구 없음)",
                "log_attribution": fr,
            },
            "barbed_spacing": overall["barbed_spacing"],
            "bunching": overall["bunching"],
            "barbed_rate_in_bw8_vs_out": overall["barbed_rate_in_bw8_vs_out"],
        },
        "h2_cdr_waste": {
            "mechanics": "전쟁 명령 100%: 날사→살명 -3s. 코브라 내장 -1s. 단 우두머리 포식자(살명 2충전) 채택 100% — "
                         "쿨감 초과분은 '2충전 만충'일 때만 버려지는데, 살명을 평균 3.3초마다 치는 로그에서 만충은 드묾.",
            "kc_gap_gt_7p5s_pct": overall["kc_gap_gt_7p5s_pct"],
            "window_slots": overall["window_slots"],
            "tsk_gradient": overall["tsk_gradient"],
            "ttk_gradient": overall["ttk_gradient"],
        },
        "h3_master_handler": {
            "master": g_master, "no_master": g_nomaster,
            "per_boss_controlled": per_boss_h3,
        },
        "focus_economy": focus,
    }

    # ---- 판정 & 결론 ----
    ws = overall["window_slots"]
    bs = overall["barbed_spacing"]
    bn = overall["bunching"]
    bwr = overall["barbed_rate_in_bw8_vs_out"]
    tsk = overall["tsk_gradient"]
    frn = fr["nearest_cast_within_150ms"]
    fr_dire = frn.get("광포한 야수 소환(여러 id)", 0)
    fr_bw = frn.get("야수의 격노(19574)", 0)
    fr_barb = frn.get("날카로운 사격(217200)", 0)

    ka = per_boss_h3.get("카이메루스", {})
    sa = per_boss_h3.get("살라다르", {})

    out["verdicts"] = {
        "H1_광기_페이싱": {
            "verdict": "기각(전제 소멸)",
            "why": [
                f"이번 시즌 날사는 광기를 부여/유지하지 않음 — BM 트리 전 노드와 날사 툴팁에 '광기' 없음. "
                f"로그의 광기 발생 {fr['applybuff_total']}건 중 최근접 시전은 광포한 야수 소환 {fr_dire}건({round(100*fr_dire/fr['applybuff_total'])}%), "
                f"야수의 격노 {fr_bw}건({round(100*fr_bw/fr['applybuff_total'])}%), 날사는 {fr_barb}건({round(100*fr_barb/fr['applybuff_total'])}%)뿐.",
                f"날사 간격의 '균등함'은 시계식 유지가 아니라 재충전 리듬 — 간격 CV 중앙 {bs['cv_median']} "
                f"(완전 균등=0, 랜덤=1; 코브라 {bs['cobra_cv_median']}).",
                f"몰아쓰기(간격≤2.6s 쌍 {bn['pairs_le_2p6s']}건)는 격노에 정렬 — {bn['near_bw_pct']}%가 격노 ±8초 안에 발생"
                f"(격노 8초 창은 전체 시간의 {bn['bw8_share_of_time_pct']}%뿐, 농축 x{round(bn['near_bw_pct']/bn['bw8_share_of_time_pct'],1)}). "
                f"격노 후 8초 날사 {bwr['in_bw_8s_per_min']}/분 vs 평시 {bwr['outside_per_min']}/분 (x{bwr['ratio']}) "
                f"— 피의 향기(+1충전)와 격노 정렬로 설명되고 광기와는 무관.",
            ],
        },
        "H2_쿨감_낭비_방지": {
            "verdict": "기각(행동이 예측과 정반대, 그리고 전제가 이 빌드에 없음)",
            "why": [
                f"H2 예측(살상 직후=날사, 직전=코브라)과 반대 — 필러 2개 이상 창에서 첫 슬롯 날사 {ws['first_slot']['barbed_pct']}%, "
                f"마지막 슬롯 {ws['last_slot']['barbed_pct']}%. 직전 살명 후 경과별 날사 비중: "
                f"0-1.5s {tsk['0-1.5s']['barbed_pct']}% → 3.0-4.5s {tsk['3.0-4.5s']['barbed_pct']}% → 4.5-7.0s {tsk['4.5-7.0s']['barbed_pct']}%. 코브라가 앞, 날사가 뒤.",
                f"전제 자체가 무너짐: 우두머리 포식자(살명 2충전) 100% — 쿨감 초과분은 '2충전 만충'일 때만 버려지는데 "
                f"살명 간격>7.5s(만충이 가능해지는 조건)는 {overall['kc_gap_gt_7p5s_pct']}%뿐. 2번째 충전이 완충기 역할이라 "
                f"날사 -3s는 언제 눌러도 거의 안 넘침 → '살상 직후 날사' 규칙은 1충전 가정에서만 최적. "
                f"기존 분석의 '살상 직후 첫 버튼 코브라 51%' 모순은 이렇게 풀림.",
                f"날사가 창 끝에 몰리는 것(마지막 슬롯 {ws['last_slot']['barbed_pct']}%, 다음 살명까지 1.5s 미만 구간 날사 "
                f"{overall['ttk_gradient']['0-1.5s']['barbed_pct']}%)은 날사 -3s가 다음 살명을 그 자리로 당겨오는 인과의 결과이기도 함 "
                f"(날사 = 살명 재장전 방아쇠). 코브라는 항상 누를 수 있고 날사는 충전이 차야 하므로 창 후반일수록 가용성이 오르는 효과도 섞임.",
                f"필러 1개짜리 짧은 창(순서 선택이 없는 경우)에선 날사 {ws['single']['barbed_pct']}%로 반반 — "
                f"충전이 있을 때 순서는 사실상 무차별이라는 bm_filler_recheck(state≥1에서 코브라 48~54%)과 일치.",
            ],
        },
        "H3_조련술의_거장": {
            "verdict": "기각(겉보기 차이는 보스/빌드 교란)",
            "why": [
                f"채택 {g_master['n_fights']}킬 vs 미채택 {g_nomaster['n_fights']}킬의 슬롯 차이(첫 슬롯 날사 "
                f"{g_master['window_slots']['first_slot']['barbed_pct']}% vs {g_nomaster['window_slots']['first_slot']['barbed_pct']}%)는 커 보이지만, "
                f"채택이 보스와 거의 완전 상관(바엘고어·선봉대·아베르지안=전원 채택, 보라시우스·벨로렌·우주의왕관·르우라=전원 미채택) "
                f"— 광역 빌드(광포한 명령 등)와 세트로 감.",
                "채택/미채택이 섞인 두 보스로 통제하면 차이 소멸: "
                f"카이메루스 날사 {ka.get('master',{}).get('barbed_per_min')}/분 vs {ka.get('no_master',{}).get('barbed_per_min')}/분, "
                f"간격 중앙 {ka.get('master',{}).get('barbed_gap_median_s')}s vs {ka.get('no_master',{}).get('barbed_gap_median_s')}s, "
                f"단일 슬롯 날사 선택 {ka.get('master',{}).get('single_slot_barbed_pct')}% vs {ka.get('no_master',{}).get('single_slot_barbed_pct')}%; "
                f"살라다르 날사 {sa.get('master',{}).get('barbed_per_min')}/분 vs {sa.get('no_master',{}).get('barbed_per_min')}/분, "
                f"간격 {sa.get('master',{}).get('barbed_gap_median_s')}s vs {sa.get('no_master',{}).get('barbed_gap_median_s')}s, "
                f"단일 슬롯 {sa.get('master',{}).get('single_slot_barbed_pct')}% vs {sa.get('no_master',{}).get('single_slot_barbed_pct')}%. "
                "채택자가 날사를 더 자주/일찍 쓰지 않음(오히려 미세하게 덜 씀).",
                "같은 보스에서 채택자의 첫 슬롯 날사가 높아 보이는 것(35% vs 15%)은 채택자의 코브라 시전 자체가 적어서"
                f"(카이메루스 {ka.get('master',{}).get('cobra_per_min')} vs {ka.get('no_master',{}).get('cobra_per_min')}/분 — 마구잡이 난타로 대체) 생기는 구성 효과.",
            ],
        },
    }

    out["conclusion"] = {
        "mystery_answer": "기계적 최적과 행동이 다른 게 아니라, '날사 우선이 최적'이라는 전제가 이 빌드에서 무너져 있음. "
                          "①살명 2충전(우두머리 포식자 100%)이 쿨감 넘침을 흡수(만충 노출 2.2%) → 날사 -3s는 언제 써도 손실 없음. "
                          "②날사의 진짜 보너스 창은 격노(피의 향기 +1충전) — 몰아쓰기의 65%가 격노 근처, 밀도 x1.94. "
                          "③코브라는 살명 -1s에 더해 날사 재충전 -2s(날카로운 비늘 100%)와 집중 배출을 겸함 → 코브라를 먼저 눌러도 날사가 늦어지기는커녕 충전이 당겨짐. "
                          "그래서 순서는 '코브라 먼저, 날사는 창 끝에서 다음 살명을 당기는 방아쇠'가 되고, 이 순서와 반대 순서의 기대 손익 차가 거의 0이라 상위권도 절반쯤은 섞어 씀.",
        "guide_paragraph": "왜 상위권은 날카로운 사격 충전이 남아도 코브라부터 누를까 — 답은 '그래도 손해가 0'이기 때문이다. "
                           "이번 빌드(전쟁 명령·우두머리 포식자·날카로운 비늘 전원 채택)에서 살상 명령은 2충전이라 날사의 쿨 -3초가 넘쳐 버려지는 순간이 사실상 없고(살명 간격이 7.5초를 넘는 경우는 2.2%뿐), "
                           "코브라는 살명 쿨 -1초에 더해 날사 재충전까지 2초 당겨 주면서 집중도 비워 준다. 날사가 진짜 비싸지는 순간은 딱 둘 — 2충전으로 넘치기 직전과 야수의 격노 창(충전 +1) — 이고, "
                           "실제로 상위 100 로그의 날사 몰아치기 65%가 격노 ±8초에 몰려 있다(평시 대비 밀도 약 2배). 남는 글쿨이 두 개 이상이면 코브라 먼저(첫 슬롯 72%), 날사는 창 끝에서 다음 살명을 당기는 방아쇠로 쓰고"
                           "(날사 직후 1.5초 안에 살명이 뜨는 비율 54%), 글쿨이 하나뿐인 짧은 창에선 반반(날사 54%)으로 사실상 순서 무차별이다. "
                           "참고로 '펫 광기 유지를 위한 균등 배분'은 이번 시즌엔 성립하지 않고(날사는 광기를 주지 않음 — 광기의 66%는 광포한 야수 소환에서 발생), "
                           "조련술의 거장 채택 여부도 필러 리듬을 바꾸지 않는다(같은 보스에서 빈도·간격 동일). "
                           "요약: 날사는 '만충 직전 + 격노 창'에서만 서두르고, 그 외 남는 글쿨은 코브라 먼저 — 순서 자체의 딜 손해는 없으니 리듬이 편한 쪽으로 쳐도 된다.",
    }

    json.dump(out, open(DATA / "bm_cobra_why.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("저장: data/bm_cobra_why.json", flush=True)

    # 콘솔 요약
    print("\n[H1] 광기 귀속:", fr["nearest_cast_within_150ms"])
    bs = overall["barbed_spacing"]
    print(f"[H1] 날사 간격 p25/50/75/90 = {bs['gap_p25_s']}/{bs['gap_median_s']}/{bs['gap_p75_s']}/{bs['gap_p90_s']}s, CV중앙 {bs['cv_median']} (코브라 CV {bs['cobra_cv_median']})")
    bn = overall["bunching"]; bw = overall["barbed_rate_in_bw8_vs_out"]
    print(f"[H1] 몰아쓰기 쌍 {bn['pairs_le_2p6s']}({bn['pairs_per_min']}/분), 격노±8s 근접 {bn['near_bw_pct']}% (격노8s창=전체시간 {bn['bw8_share_of_time_pct']}%)")
    print(f"[H1] 격노 후 8s 날사 {bw['in_bw_8s_per_min']}/분 vs 밖 {bw['outside_per_min']}/분 (x{bw['ratio']})")
    ws = overall["window_slots"]
    print(f"\n[H2] single 창 날사 {ws['single']['barbed_pct']}% | 첫슬롯 {ws['first_slot']['barbed_pct']}% | 중간 {ws['mid_slots']['barbed_pct']}% | 마지막 {ws['last_slot']['barbed_pct']}%")
    print("[H2] ttk 그라디언트(다음 살명까지):")
    for bl, v in overall["ttk_gradient"].items():
        print(f"   {bl}: 날사 {v['barbed_pct']}% (n={v['barbed']+v['cobra']})")
    print("[H2] tsk 그라디언트(직전 살명 후):")
    for bl, v in overall["tsk_gradient"].items():
        print(f"   {bl}: 날사 {v['barbed_pct']}% (n={v['barbed']+v['cobra']})")
    print(f"[H2] 살명 간격>7.5s 비율 {overall['kc_gap_gt_7p5s_pct']}%")
    print(f"\n[H3] master n={g_master['n_fights']} vs no n={g_nomaster['n_fights']}")
    for lab, g in (("master", g_master), ("no_master", g_nomaster)):
        print(f"   {lab}: 날사 {g['rates_per_min']['barbed']}/분 코브라 {g['rates_per_min']['cobra']}/분 "
              f"간격중앙 {g['barbed_spacing']['gap_median_s']}s single날사 {g['window_slots']['single']['barbed_pct']}% "
              f"첫슬롯 {g['window_slots']['first_slot']['barbed_pct']}% 마지막 {g['window_slots']['last_slot']['barbed_pct']}%")
    print("\n[H3] 보스 통제:")
    for boss, row in per_boss_h3.items():
        m, n = row["master"], row["no_master"]
        if "barbed_per_min" in m and "barbed_per_min" in n:
            print(f"   {boss}: master(n={m['n_fights']}) 날사 {m['barbed_per_min']}/분 single {m['single_slot_barbed_pct']}% | "
                  f"no(n={n['n_fights']}) 날사 {n['barbed_per_min']}/분 single {n['single_slot_barbed_pct']}%")
        else:
            print(f"   {boss}: 표본 부족 master n={m.get('n_fights')} no n={n.get('n_fights')}")


if __name__ == "__main__":
    main()
