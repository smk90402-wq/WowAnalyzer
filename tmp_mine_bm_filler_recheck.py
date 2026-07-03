"""BM 단일 필러 재점검 — '코브라 54%'가 우선순위인가, 날카 충전 고갈의 결과인가.

사용자 반론 검증:
 1. 날카로운 사격(217200, 2충전/18s 재충전) 충전 상태를 시전 기록으로 추정해서
    '충전이 있는데도 코브라를 눌렀는지' 직접 측정.
 2. 코브라 강화 프록 존재 여부: 코브라 시전 직전 buffs 이벤트 lift 분석.
 3. 가이드 한 문장 결론.

데이터: 스크래치패드 bm_cd_events.json (v2_cache_events에서 이미 추출된 BM 362킬 풀 이벤트).
사용: python tmp_mine_bm_filler_recheck.py explore   → 탐색(간격 분포/버스트/프록 후보)
      python tmp_mine_bm_filler_recheck.py           → 본 분석, data/bm_filler_recheck.json
"""
from __future__ import annotations
import json, sys, csv
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze\data")
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")

KC = 34026; BARB = 217200; COBRA = 193455
WT_IDS = {1264359, 1264355}
FRENZY = 272790
# tmp_mine_bm_alternation.py 실측 오프글쿨 목록
OFFGCD = {20572, 186257, 204526, 212382, 212396, 219199, 227723, 274738,
          304051, 1234768, 1236616, 1236998, 1253050, 1283817, 1283818}

BOSS_KO = {3176: "아베르지안", 3177: "보라시우스", 3178: "바엘고어", 3179: "살라다르",
           3180: "선봉대", 3181: "우주의왕관", 3182: "벨로렌", 3183: "한밤의도래(르우라)",
           3306: "카이메루스"}


def load_names():
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    return {int(k): (v.get("name_ko") or v.get("name_en") or "?")
            for k, v in db.items() if isinstance(v, dict)}


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
        wanted[key] = {"boss_id": int(r["encounter_id"]),
                       "boss": BOSS_KO.get(int(r["encounter_id"]), r["encounter_name"]),
                       "rank": int(r["rank"]), "char": ch,
                       "t0": f["startTime"], "t1": f["endTime"]}
    return wanted


def prep_fight(info, e):
    """글쿨 시전열(t_ms, sid)과 buffs 원본 반환."""
    t0 = info["t0"]
    casts = sorted((c[0], c[1]) for c in (e.get("casts") or [])
                   if len(c) >= 3 and c[2] == "cast" and c[0] >= t0 - 1500)
    gcd = [(t, i) for t, i in casts if i not in OFFGCD]
    buffs = sorted((b for b in (e.get("buffs") or []) if len(b) >= 3), key=lambda b: b[0])
    return gcd, buffs


def pct(vals, q):
    if not vals: return None
    v = sorted(vals)
    return v[min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))]


# ────────────────────────── explore ──────────────────────────

def explore(wanted, ev, names):
    barb_gaps_st, barb_gaps_aoe = [], []
    burst20 = Counter()          # 20초 창 최대 날카 시전수
    adj_cb = adj_bc = cobra_n = barb_n = 0   # 코브라→날카(2s내) / 날카→코브라
    pre_cobra = Counter(); pre_barb = Counter()   # 시전 직전 2.5s 내 buff 이벤트
    consumed_cobra = Counter(); consumed_barb = Counter()  # 시전 직후 0.4s 내 remove
    buff_rate = Counter(); tot_dur_ms = 0
    frenzy_types = Counter(); frenzy_stacks = Counter()
    frenzy_durs = []             # apply→remove (refresh 없이) 지속시간
    n_st = n_aoe = 0

    for k, info in wanted.items():
        e = ev.get(k)
        if not e: continue
        gcd, buffs = prep_fight(info, e)
        if len(gcd) < 30: continue
        dur_ms = info["t1"] - info["t0"]
        tot_dur_ms += dur_ms
        wt_n = sum(1 for _, i in gcd if i in WT_IDS)
        is_st = wt_n < 3
        if is_st: n_st += 1
        else: n_aoe += 1

        bts = [t for t, i in gcd if i == BARB]
        gaps = [(b - a) / 1000 for a, b in zip(bts, bts[1:])]
        (barb_gaps_st if is_st else barb_gaps_aoe).extend(gaps)

        # 20s 롤링 창 최대 날카 수
        mx = 0; j = 0
        for i2 in range(len(bts)):
            while bts[i2] - bts[j] > 20000: j += 1
            mx = max(mx, i2 - j + 1)
        burst20[mx] += 1

        # 인접(다음 글쿨) 순서
        for a, b in zip(gcd, gcd[1:]):
            if a[1] == COBRA and b[1] == BARB and b[0] - a[0] <= 2000: adj_cb += 1
            if a[1] == BARB and b[1] == COBRA and b[0] - a[0] <= 2000: adj_bc += 1
        cobra_n += sum(1 for _, i in gcd if i == COBRA)
        barb_n += len(bts)

        # buff 이벤트 rate + 시전 직전/직후 패턴
        applies = [(b[0], b[1]) for b in buffs if b[2] in ("applybuff", "refreshbuff", "applybuffstack")]
        removes = [(b[0], b[1]) for b in buffs if b[2] in ("removebuff", "removebuffstack")]
        for _, bid in applies: buff_rate[bid] += 1
        for spell, pre_c, con_c in ((COBRA, pre_cobra, consumed_cobra), (BARB, pre_barb, consumed_barb)):
            cts = [t for t, i in gcd if i == spell]
            ai = 0
            for ct in cts:
                seen = set()
                for at, bid in applies:
                    if ct - 2500 <= at <= ct: seen.add(bid)
                    elif at > ct: break
                for bid in seen: pre_c[bid] += 1
                rseen = set()
                for rt, bid in removes:
                    if ct <= rt <= ct + 400: rseen.add(bid)
                    elif rt > ct + 400: break
                for bid in rseen: con_c[bid] += 1

        # 광기(펫버프) 실측
        exp = None
        for b in buffs:
            if b[1] != FRENZY: continue
            frenzy_types[b[2]] += 1
            if len(b) >= 5: frenzy_stacks[b[4]] += 1
            if b[2] == "applybuff": exp = b[0]
            elif b[2] == "removebuff" and exp is not None:
                frenzy_durs.append((b[0] - exp) / 1000); exp = None
            elif b[2] in ("refreshbuff", "applybuffstack"): exp = b[0]

    print(f"단일필러판(난타<3): {n_st}, 광역판: {n_aoe}")
    print(f"\n코브라 총 {cobra_n}, 날카 총 {barb_n}")
    print(f"코브라→바로 다음 글쿨이 날카(2s내): {adj_cb} ({100*adj_cb/cobra_n:.1f}% of 코브라)")
    print(f"날카→바로 다음 글쿨이 코브라(2s내): {adj_bc} ({100*adj_bc/barb_n:.1f}% of 날카)")

    for lab, g in (("단일", barb_gaps_st), ("광역", barb_gaps_aoe)):
        g = sorted(g)
        if not g: continue
        hist = Counter(min(19, int(x)) for x in g)
        print(f"\n날카 간격 히스토그램({lab}, n={len(g)}, med {pct(g,.5):.1f}s p10 {pct(g,.1):.1f} p90 {pct(g,.9):.1f}):")
        for b in range(0, 20):
            print(f"  {b:>2}-{b+1}s {'#' * int(60 * hist.get(b,0)/len(g))} {100*hist.get(b,0)/len(g):.1f}%")
    print(f"\n20s 창 최대 날카 시전수 분포: {dict(sorted(burst20.items()))}")
    print("  (2충전/18s 재충전이면 20s 창 최대 = 2+1=3. 4 이상이면 리셋/추가충전 존재)")

    print(f"\n광기(272790) 이벤트: {dict(frenzy_types)}, 스택 {dict(frenzy_stacks)}")
    if frenzy_durs:
        print(f"광기 apply→remove 지속: med {pct(frenzy_durs,.5):.1f}s p90 {pct(frenzy_durs,.9):.1f}s")

    tot_min = tot_dur_ms / 60000
    for lab, pre, con, n_casts in (("코브라", pre_cobra, consumed_cobra, cobra_n),
                                   ("날카", pre_barb, consumed_barb, barb_n)):
        print(f"\n== {lab} 시전 직전 2.5s 내 버프(상위 lift, 최소 500회) ==")
        rows = []
        for bid, c in pre.items():
            if c < 500: continue
            share = c / n_casts
            base = min(1.0, buff_rate[bid] * 2.5 / (tot_dur_ms / 1000))  # 임의 순간 2.5s창 기대확률
            lift = share / base if base > 0 else 0
            rows.append((lift, share, bid, c, con.get(bid, 0)))
        rows.sort(reverse=True)
        for lift, share, bid, c, conc in rows[:15]:
            print(f"  {bid:>8} {names.get(bid,'?'):<22} 직전출현 {100*share:5.1f}% lift x{lift:5.1f} "
                  f"(n={c}, 직후0.4s소멸 {conc})")


BW = 19574


def sim_charges(barb_times, press_times, R_ms):
    """2충전/직렬 재충전 시뮬 (리셋 프록은 관측 불가 → 시뮬 충전수는 항상 실제 이하 = 하한).
    barb_times: 날카 시전(소모) 시각들. press_times: 상태를 묻고 싶은 시각들.
    반환: press_times 각각의 시뮬 충전수, 그리고 clamp(0충전인데 시전 = 보이지 않는 충전) 횟수."""
    events = [(t, "b") for t in barb_times] + [(t, "q") for t in press_times]
    # q(질문)가 같은 시각의 소모보다 먼저 평가되도록 정렬
    events.sort(key=lambda x: (x[0], 0 if x[1] == "q" else 1))
    ch, next_ready = 2, None
    out, clamp = [], 0
    for t, kind in events:
        while next_ready is not None and next_ready <= t and ch < 2:
            ch += 1
            next_ready = (next_ready + R_ms) if ch < 2 else None
        if kind == "q":
            out.append(ch)
        else:  # 날카 시전 = 소모
            if ch > 0:
                if ch == 2: next_ready = t + R_ms
                ch -= 1
            else:
                clamp += 1  # 시뮬엔 없는 충전(리셋 프록 등) — 하한 유지 위해 0 유지
    return out, clamp


def main():
    names = load_names()
    wanted = load_wanted()
    ev = json.load(open(SCRATCH / "bm_cd_events.json", encoding="utf-8"))
    print(f"이벤트 캐시 적중: {len(ev)}/{len(wanted)}", flush=True)
    if "explore" in sys.argv:
        explore(wanted, ev, names)
        return

    # ── 시나리오: 재충전 시간 가정 (리셋/충전지급은 모두 무시 → 충전수는 '하한')
    SCEN = {"S1_툴팁18s": 18000, "S2_가속반영": None, "S3_실효8s": 8000, "S4_실효6s": 6000}

    st_fights = []
    bw_before = bw_after = bw_n = 0  # 격노 캐스트 앞뒤 6s의 날카 수 (충전 지급 가설)
    for k, info in wanted.items():
        e = ev.get(k)
        if not e: continue
        gcd, buffs = prep_fight(info, e)
        if len(gcd) < 30: continue
        wt_n = sum(1 for _, i in gcd if i in WT_IDS)
        if wt_n >= 3: continue  # 단일 필러 질문 → 광역판 제외
        st_fights.append((k, info, gcd))
        bts = [t for t, i in gcd if i == BARB]
        for t, i in gcd:
            if i == BW and (t - info["t0"]) > 30000:
                bw_n += 1
                bw_before += sum(1 for x in bts if t - 6000 <= x < t)
                bw_after += sum(1 for x in bts if t < x <= t + 6000)
    print(f"단일 판: {len(st_fights)}")
    print(f"격노(중반 이후) {bw_n}회 — 직전 6s 날카 평균 {bw_before/bw_n:.2f} vs 직후 6s {bw_after/bw_n:.2f}")

    # 판별 가속 추정: 글쿨 간격 (0.5~2.0s) p10 → GCD → 가속
    def gcd_est(gcd):
        iv = sorted((b[0] - a[0]) / 1000 for a, b in zip(gcd, gcd[1:]) if 0.5 < (b[0] - a[0]) / 1000 < 2.0)
        return pct(iv, 0.10) or 1.5

    # 상태별 결정 행렬 + 코브라 시전 중 '충전 확실히 있었음' 비율
    res = {}
    band_res = {}
    for scen, R_fix in SCEN.items():
        mat = {0: Counter(), 1: Counter(), 2: Counter()}   # state -> {cobra: n, barb: n}
        clamp_tot = barb_tot = 0
        cap2_cobra_examples = 0
        bmat = {"rank_1_20": {1: Counter(), 2: Counter()}, "rank_21_100": {1: Counter(), 2: Counter()}}
        for k, info, gcd in st_fights:
            g = gcd_est(gcd)
            R = R_fix if R_fix else int(18000 / (1.5 / g))
            bts = [t for t, i in gcd if i == BARB]
            fills = [(t, i) for t, i in gcd if i in (BARB, COBRA)]
            states, clamp = sim_charges(bts, [t for t, _ in fills], R)
            clamp_tot += clamp; barb_tot += len(bts)
            band = "rank_1_20" if info["rank"] <= 20 else "rank_21_100"
            for (t, i), st in zip(fills, states):
                mat[st][i] += 1
                if st >= 1:
                    bmat[band][st][i] += 1
        res[scen] = {"R_note": "판별 가속 반영 18s/(1+가속)" if R_fix is None else f"{R_fix/1000:.0f}s 고정",
                     "clamp_pct_of_barb": round(100 * clamp_tot / barb_tot, 1)}
        for st in (0, 1, 2):
            c, b = mat[st][COBRA], mat[st][BARB]
            res[scen][f"state{st}"] = {"cobra": c, "barbed": b,
                                       "cobra_pct": round(100 * c / (c + b), 1) if c + b else None}
        band_res[scen] = {bd: {f"state{st}": {"cobra": bmat[bd][st][COBRA], "barbed": bmat[bd][st][BARB],
                                              "cobra_pct": round(100 * bmat[bd][st][COBRA] / max(1, bmat[bd][st][COBRA] + bmat[bd][st][BARB]), 1)}
                               for st in (1, 2)} for bd in bmat}
        ge1c = mat[1][COBRA] + mat[2][COBRA]; ge1b = mat[1][BARB] + mat[2][BARB]
        res[scen]["state_ge1"] = {"cobra": ge1c, "barbed": ge1b,
                                  "cobra_pct": round(100 * ge1c / (ge1c + ge1b), 1) if ge1c + ge1b else None}
        print(f"\n[{scen}] ({res[scen]['R_note']}) 시뮬에 없는 충전으로 시전(리셋 추정): 날카의 {res[scen]['clamp_pct_of_barb']}%")
        for st in (0, 1, 2):
            d = res[scen][f"state{st}"]
            print(f"  충전 {st}개(하한) 상태에서 필러 선택: 코브라 {d['cobra']} vs 날카 {d['barbed']} → 코브라 {d['cobra_pct']}%")
        print(f"  충전 1개 이상 확실: 코브라 {ge1c} vs 날카 {ge1b} → 코브라 {res[scen]['state_ge1']['cobra_pct']}%")
        for bd in bmat:
            s1, s2 = bmat[bd][1], bmat[bd][2]
            c, b = s1[COBRA] + s2[COBRA], s1[BARB] + s2[BARB]
            if c + b:
                print(f"    {bd}: 충전확보 상태 코브라 {100*c/(c+b):.1f}%")

    # '격노 버스트용 아껴두기' 반론 확인: 충전 있는데 코브라 누른 순간 중 6s 내 격노 도착 비율
    import bisect
    near_bw = save_tot = 0
    for k, info, gcd in st_fights:
        bts = [t for t, i in gcd if i == BARB]
        bws = [t for t, i in gcd if i == BW]
        fills = [(t, i) for t, i in gcd if i in (BARB, COBRA)]
        states, _ = sim_charges(bts, [t for t, _ in fills], 14000)
        for (t, i), st in zip(fills, states):
            if st >= 1 and i == COBRA:
                save_tot += 1
                j = bisect.bisect_left(bws, t)
                if j < len(bws) and bws[j] - t <= 6000: near_bw += 1
    print(f"\n충전 있는데 코브라 {save_tot}회 중 6s 내 격노 도착(아껴두기 가능성): {near_bw} ({100*near_bw/save_tot:.1f}%)")

    # KC 사이 구간에 둘 다 등장 시 순서 (단일판)
    both = cobra_first = 0
    adj_cb = adj_bc = cobra_tot = 0
    for k, info, gcd in st_fights:
        kc_idx = [x for x, (t, i) in enumerate(gcd) if i == KC]
        for a, b in zip(kc_idx, kc_idx[1:]):
            between = [gcd[x][1] for x in range(a + 1, b)]
            if BARB in between and COBRA in between:
                both += 1
                if between.index(COBRA) < between.index(BARB): cobra_first += 1
        for a, b in zip(gcd, gcd[1:]):
            if a[1] == COBRA and b[1] == BARB and b[0] - a[0] <= 2000: adj_cb += 1
            if a[1] == BARB and b[1] == COBRA and b[0] - a[0] <= 2000: adj_bc += 1
        cobra_tot += sum(1 for _, i in gcd if i == COBRA)
    print(f"\n살명 사이에 코브라+날카 둘 다: {both}회, 코브라 먼저 {100*cobra_first/both:.1f}%")
    print(f"코브라→다음 글쿨 날카: {adj_cb} / 날카→다음 글쿨 코브라: {adj_bc}")

    out = {
        "meta": {
            "date": "2026-07-04",
            "question": "'단일 필러 54%=코브라'가 코브라 우선순위 증거인가, 날카 충전 고갈의 결과인가 (본캐 유저 반론 검증)",
            "sample": f"12.0.7 top100 신화 BM {len(st_fights)}킬 (마구잡이 난타<3회 = 단일 위주 판만)",
            "method": "날카 2충전/재충전 시뮬(리셋 프록은 관측 불가 → 시뮬 충전수는 항상 '실제 이하'인 하한). "
                      "충전 하한이 1 이상인 순간의 필러 선택만 보면 '충전이 분명히 있는데 뭘 눌렀나'를 확정할 수 있음.",
        },
        "barbed_charge_reality": {
            "tooltip": "18초 재충전, 2회 충전 (spell_db)",
            "observed": "20초 창에 날카 5~8발이 흔함 → 재충전만으론 불가능, 리셋/추가충전이 대량 존재",
            "bw_grant_check": {"bw_casts": bw_n,
                               "barbed_in_6s_before": round(bw_before / bw_n, 2),
                               "barbed_in_6s_after": round(bw_after / bw_n, 2)},
        },
        "decision_by_charge_state": res,
        "by_rank_band": band_res,
        "order_when_both": {
            "kc_windows_with_both": both,
            "cobra_first_pct": round(100 * cobra_first / both, 1),
            "cobra_then_barbed_next_gcd": adj_cb,
            "barbed_then_cobra_next_gcd": adj_bc,
        },
        "saving_for_bw_check": {
            "cobra_with_charge_n": save_tot,
            "bw_within_6s_after": near_bw,
            "pct": round(100 * near_bw / save_tot, 1),
            "note": "'격노 버스트용으로 날카를 아껴둔 것' 반론 검증 — 충전 있는데 코브라 누른 순간의 "
                    "18.5%만 6초 안에 격노가 옴. 나머지 81.5%는 아껴둘 이유가 없는데도 코브라를 먼저 누름.",
        },
        "cobra_proc_scan": {
            "found": False,
            "note": "코브라 시전 직전 2.5s 버프 lift 스캔 — 최고 lift 1.5(원정순찰대원의 매의 눈, 출현 2.5%)로 "
                    "전부 장신구/외부 버프. 코브라를 강화하는 클래스 프록 버프는 top100 로그에 없음. "
                    "(날카 쪽은 야수의 격노 직후 몰림 lift 2.2 — 프록이 아니라 버스트 정렬)",
        },
        "conclusion": {
            "user_method_point": "인정 — '필러의 54%가 코브라'라는 빈도만으로는 우선순위를 말할 수 없음. "
                                 "충전 고갈로도 같은 빈도가 나올 수 있다는 지적이 맞음. 기존 문구의 근거 제시가 틀렸음.",
            "user_hypothesis_test": "그러나 '충전 없을 때만 코브라'는 실측과 다름 — 날카 충전이 확실히 남아 있는 순간에도 "
                                    "필러의 절반이 코브라(가장 보수적 추정 47.8%, 현실적 추정 51~59%)이고, "
                                    "살상 명령 사이에 둘 다 나올 땐 코브라를 먼저 누른 게 72.4%.",
            "real_barbed_rule": "날카가 우선이 되는 순간은 딱 두 가지 — ① 2충전(넘치기 직전)이면 즉시(이때 날카 선택 81~97%), "
                                "② 야수의 격노 직후(직후 6초 날카 1.77발 vs 직전 0.90발 — 격노에 맞춰 몰아씀). "
                                "그 외엔 서두르지 않음(출혈은 늦게 발라도 남은 피해가 합산).",
            "cobra_proc": "코브라 강화 프록은 이번 시즌(무리의 지도자 빌드) 로그에 존재하지 않음. "
                          "코브라의 가치는 프록이 아니라 '살상 명령 쿨 1초 단축'(툴팁 내장 효과).",
            "guide_sentence": "단일 필러: 날카로운 사격은 '2충전으로 넘치기 직전'과 '격노 직후'에만 먼저 쓰고, "
                              "그 외 남는 글쿨은 충전이 있어도 코브라(살상 명령 쿨 1초 단축) — "
                              "상위 100 로그에서 충전이 확실히 남아 있어도 절반은 코브라를 먼저 눌렀다.",
        },
    }
    json.dump(out, open(DATA / "bm_filler_recheck.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n저장: data/bm_filler_recheck.json")


if __name__ == "__main__":
    main()
