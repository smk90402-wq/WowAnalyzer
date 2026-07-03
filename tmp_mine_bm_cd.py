"""BM 쿨기 운용 실측 — 야수의 격노·야생의 부름·물약·블러드 정렬 보스별 정답지.

파싱 패턴은 analyze_bm_addwave.py / tmp_mine_frost_cd.py 를 따름
(v2_cache_events.json 1.4GB → raw_decode 증분 스캔, 스크래치패드에 추출 캐시).
★오늘자(2026-07-03) rankings CSV에 있는 킬만 대상 (CSV report_id/fight_id로 필터)★

사용: python tmp_mine_bm_cd.py explore   → 스펠 ID 관측 (실제 ID 확정용)
      python tmp_mine_bm_cd.py           → 본 분석, data/bm_cd_usage.json 출력
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

# ── 스펠 ID 후보 (explore 로 확정) ─────────────────────────────
BW = 19574            # 야수의 격노 (캐스트)
BW_BUFF_IDS = {19574, 186254, 344572, 1235388, 1285912}
COTW = 359844         # 야생의 부름 (캐스트, DB에 없음 → 관측으로 확인)
KC = 34026            # 살상 명령
BARBED = 217200       # 날카로운 사격
WT = 1264359          # 마구잡이 난타 (쫄웨이브 지표)
PUZZLE = 383781       # 알게타르 수수께끼 (상자 트링킷 시전)
LUST_IDS = {2825, 32182, 80353, 264667, 390386, 466904, 1260277}
POTION_IDS = {1236994, 1238443, 431932, 453035}  # 무모함의 물약 등 (버프)


def load_names():
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    return {int(k): (v.get("name_ko") or v.get("name_en") or "?") for k, v in db.items() if isinstance(v, dict)}


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
        gear_names = [g.get("name") or "" for g in (p.get("gear") or [])]
        wanted[key] = {
            "boss": r["encounter_name"], "eid": int(r["encounter_id"]),
            "rank": int(r["rank"]), "char": ch,
            "t0": f["startTime"], "t1": f["endTime"],
            "puzzle_box": any("Puzzle Box" in g for g in gear_names),
        }
    return wanted


def stream_filter(wanted):
    cache = SCRATCH / "bm_cd_events.json"
    if cache.exists():
        return json.load(open(cache, encoding="utf-8"))
    s = open(DATA / "v2_cache_events.json", encoding="utf-8").read()
    print(f"events 캐시 {len(s)/1e6:.0f}MB 스캔...", flush=True)
    dec = json.JSONDecoder()
    out, i, n, seen = {}, 1, len(s), 0
    while i < n:
        while i < n and s[i] in ' \t\r\n,': i += 1
        if i >= n or s[i] == '}': break
        key, j = dec.raw_decode(s, i); i = j
        while s[i] in ' \t\r\n:': i += 1
        val, j = dec.raw_decode(s, i); i = j
        seen += 1
        if seen % 2000 == 0: print(f"  스캔 {seen}, 적중 {len(out)}", flush=True)
        if key in wanted:
            out[key] = val
    del s
    json.dump(out, open(cache, "w", encoding="utf-8"))
    print(f"추출 {len(out)}/{len(wanted)}", flush=True)
    return out


def mmss(t):
    sign = "-" if t < 0 else ""
    t = abs(t)
    return f"{sign}{int(t)//60}:{int(t)%60:02d}"


def pct(vals, q):
    if not vals: return None
    v = sorted(vals)
    idx = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return v[idx]


def explore(wanted, ev, names):
    cast_ids = Counter(); buff_ids = Counter()
    cast_fights = Counter(); buff_fights = Counter()
    for k, e in ev.items():
        cseen, bseen = set(), set()
        for c in (e.get("casts") or []):
            if len(c) >= 3 and c[2] == "cast":
                cast_ids[c[1]] += 1; cseen.add(c[1])
        for b in (e.get("buffs") or []):
            if len(b) >= 3 and b[2] == "applybuff":
                buff_ids[b[1]] += 1; bseen.add(b[1])
        for x in cseen: cast_fights[x] += 1
        for x in bseen: buff_fights[x] += 1
    nf = len(ev)
    print(f"\n== 캐스트 ID top50 (n_fights={nf}) ==")
    for sid, c in cast_ids.most_common(50):
        print(f"  {sid:>8} {names.get(sid,'?'):<20} 총{c:>6}  판당출현 {cast_fights[sid]}/{nf}")
    print("\n== applybuff ID top60 ==")
    for sid, c in buff_ids.most_common(60):
        print(f"  {sid:>8} {names.get(sid,'?'):<20} 총{c:>6}  판당출현 {buff_fights[sid]}/{nf}")
    print("\n== 후보 확인 ==")
    for sid in sorted(BW_BUFF_IDS | {COTW, KC, BARBED, WT, PUZZLE} | LUST_IDS | POTION_IDS):
        print(f"  {sid:>8} {names.get(sid,'?'):<20} cast총 {cast_ids.get(sid,0):>6} (판 {cast_fights.get(sid,0)}) / buff총 {buff_ids.get(sid,0):>6} (판 {buff_fights.get(sid,0)})")


# ── 확정 ID (explore 결과) ─────────────────────────────────────
# 야생의 부름(359844): 12.0 미드나잇에서 사라짐 — 0/362 킬. 격노가 유일한 주기 쿨기.
# 블러드(2825/32182/80353/264667/390386): 0/362 킬 — 미드나잇에 블러드 없음.
# 물약 슬롯: 빛의 잠재력(1236616, 주스탯+346 30s) / 날뛰는 방종의 비약(1236998, +385 30s)
#            / 무모함의 물약(1236994) — 셋 다 5분쿨 '마시는' 아이템.
POT_MAIN = 1236616
POT_IDS = {1236616: "빛의잠재력", 1236998: "방종의비약", 1236994: "무모함의물약"}
BOX_BUFF_S = 20.0
POT_BUFF_S = 30.0

NOISE = {264735, 781, 186257, 186258, 186265, 147362, 109304, 6262, 1234768,
         19577, 34477, 136, 883, 20572, 109248, 187650, 103740, 26297, 1262857,
         227723, 1236616, 1236998, 1236994}  # 오프너 시퀀스용 노이즈(유틸/소모품)

BOSS_KO = {3176: "아베르지안", 3177: "보라시우스", 3178: "바엘고어&에조라크",
           3179: "살라다르", 3180: "선봉대", 3181: "우주의 왕관",
           3182: "벨로렌", 3183: "한밤의 도래(르우라)", 3306: "카이메루스"}


def parse_fight(info, e, names):
    t0, t1 = info["t0"], info["t1"]
    dur = (t1 - t0) / 1000
    casts = sorted((c for c in (e.get("casts") or []) if len(c) >= 3 and c[2] == "cast"),
                   key=lambda c: c[0])
    buffs = sorted((b for b in (e.get("buffs") or []) if len(b) >= 3), key=lambda b: b[0])

    def rel(ts): return (ts - t0) / 1000

    bw = [rel(c[0]) for c in casts if c[1] == BW]
    wt = [rel(c[0]) for c in casts if c[1] == WT]
    pots = [(rel(c[0]), POT_IDS[c[1]]) for c in casts if c[1] in POT_IDS]
    box = [rel(c[0]) for c in casts if c[1] == PUZZLE]

    # 격노 버프 실측 창 (apply→remove; 연장 특성 반영)
    bw_win, act = [], None
    for b in buffs:
        if b[1] != BW: continue
        if b[2] == "applybuff": act = rel(b[0])
        elif b[2] == "removebuff" and act is not None:
            bw_win.append((act, rel(b[0]))); act = None
    if act is not None: bw_win.append((act, dur))
    if not bw_win:  # 폴백: 캐스트+15s
        bw_win = [(t, t + 15) for t in bw]

    # 풀링 전 시전 감지: 캐스트 없이 removebuff 먼저 나오면 '미리 켜고 입장'
    def carried_in(sid):
        for b in buffs:
            if b[1] != sid: continue
            return b[2] in ("removebuff", "refreshbuff") and rel(b[0]) > 0.5
        return False

    # 오프너 시퀀스: 첫 12초, 750ms 중복 접기, 노이즈 제외
    seq = []
    for c in casts:
        t = rel(c[0])
        if t > 12: break
        if c[1] in NOISE: continue
        if seq and t - seq[-1][0] < 0.75 and c[1] == seq[-1][1]: continue
        seq.append((t, c[1]))
    seq_names = tuple(names.get(a, f"#{a}") for _, a in seq[:5])

    return {
        "rank": info["rank"], "dur": dur,
        "bw": bw, "bw_win": bw_win, "wt": wt, "pots": pots, "box": box,
        "box_carried": carried_in(PUZZLE),
        "pot_carried": any(carried_in(s) for s in POT_IDS),
        "seq": seq_names,
    }


def overlap_s(win, lo, hi):
    """[lo,hi]와 win(구간 리스트)의 겹침 초."""
    tot = 0.0
    for a, b in win:
        tot += max(0.0, min(b, hi) - max(a, lo))
    return tot


def gap_stats(g, eff_cd):
    if not g: return None
    n = len(g)
    return {
        "n": n, "p25": round(pct(g, .25), 1), "med": round(pct(g, .5), 1),
        "p75": round(pct(g, .75), 1),
        "즉시_pct": round(100 * sum(1 for x in g if x <= eff_cd + 3) / n),
        "소홀드_pct": round(100 * sum(1 for x in g if eff_cd + 3 < x <= eff_cd + 15) / n),
        "대홀드_pct": round(100 * sum(1 for x in g if x > eff_cd + 15) / n),
    }


def summarize(fs, eff_cd):
    if not fs: return None
    gaps = [g for f in fs for g in
            (f["bw"][i+1] - f["bw"][i] for i in range(len(f["bw"]) - 1))]
    first = sorted(f["bw"][0] for f in fs if f["bw"])
    bwpm = sorted(len(f["bw"]) / (f["dur"] / 60) for f in fs if f["dur"] > 0)
    # 물약↔격노 정렬: 격노 업타임이 ~50%라 '겹침 초'는 기본값이 15s.
    # → 진짜 정렬 지표는 (1) 물약 직후 3s 내 격노 캐스트 (2) 겹침 20s 이상(격노 2방 걸침)
    pot_ol, pot_n, pot_in_bw, pot_next3, pot_next = [], 0, 0, 0, []
    for f in fs:
        for p, _ in f["pots"]:
            pot_n += 1
            pot_ol.append(overlap_s(f["bw_win"], p, p + POT_BUFF_S))
            if any(a <= p <= b for a, b in f["bw_win"]): pot_in_bw += 1
            nxt = [t for t in f["bw"] if t >= p - 1]
            if nxt:
                d = nxt[0] - p
                pot_next.append(d)
                if d <= 3: pot_next3 += 1
    box_ol, box_n, box_in_bw, box_next3 = [], 0, 0, 0
    for f in fs:
        for p in f["box"]:
            box_n += 1
            box_ol.append(overlap_s(f["bw_win"], p, p + BOX_BUFF_S))
            if any(a <= p <= b for a, b in f["bw_win"]): box_in_bw += 1
            nxt = [t for t in f["bw"] if t >= p - 1]
            if nxt and nxt[0] - p <= 3: box_next3 += 1
    return {
        "n": len(fs),
        "first_bw_med_s": round(pct(first, .5), 1) if first else None,
        "first_bw_p25_p75": [round(pct(first, .25), 1), round(pct(first, .75), 1)] if first else None,
        "bw_per_min_med": round(pct(bwpm, .5), 2) if bwpm else None,
        "bw_gap": gap_stats(gaps, eff_cd),
        "pot_uses": pot_n,
        "pot_bw_overlap_med_s": round(pct(pot_ol, .5), 1) if pot_ol else None,
        "pot_overlap_ge20s_pct": round(100 * sum(1 for x in pot_ol if x >= 20) / pot_n) if pot_n else None,
        "pot_cast_in_bw_pct": round(100 * pot_in_bw / pot_n) if pot_n else None,
        "pot_then_bw_within3s_pct": round(100 * pot_next3 / pot_n) if pot_n else None,
        "pot_to_next_bw_med_s": round(pct(pot_next, .5), 1) if pot_next else None,
        "box_uses": box_n,
        "box_bw_overlap_med_s": round(pct(box_ol, .5), 1) if box_ol else None,
        "box_cast_in_bw_pct": round(100 * box_in_bw / box_n) if box_n else None,
        "box_then_bw_within3s_pct": round(100 * box_next3 / box_n) if box_n else None,
    }


def main():
    names = load_names()
    wanted = load_wanted()
    print(f"BM player-fights wanted: {len(wanted)}", flush=True)
    ev = stream_filter(wanted)
    print(f"events hit: {len(ev)}/{len(wanted)}", flush=True)
    if "explore" in sys.argv:
        explore(wanted, ev, names)
        return

    per = []
    for k, info in wanted.items():
        e = ev.get(k)
        if not e: continue
        f = parse_fight(info, e, names)
        if len(f["bw"]) < 2: continue
        per.append((info, f))
    print(f"분석 대상 킬: {len(per)}", flush=True)

    # 실효 쿨: 전체 격노 간격의 5퍼센타일
    all_gaps = sorted(g for _, f in per for g in
                      (f["bw"][i+1] - f["bw"][i] for i in range(len(f["bw"]) - 1)))
    eff_cd = pct(all_gaps, .05)
    print(f"격노 간격 p5(실효 쿨 추정) = {eff_cd:.1f}s, p1 = {pct(all_gaps, .01):.1f}s", flush=True)

    def band(r): return "rank_1_20" if r <= 20 else "rank_21_100"

    out = {"meta": {
        "date": "2026-07-03", "n_kills": len(per),
        "eff_cd_s": round(eff_cd, 1),
        "spells": {"bestial_wrath": BW, "wild_trample": WT, "puzzle_box": PUZZLE,
                   "potions": {str(k): v for k, v in POT_IDS.items()}},
        "notes": [
            "야생의 부름(359844)은 12.0 미드나잇 로그에 0회 — 스킬 자체가 사라져 격노(19574)가 유일한 주기 쿨기.",
            "블러드/영웅심/시간왜곡 계열 버프 0/362킬 — 미드나잇에는 블러드가 없어 '블러드 정렬' 항목은 성립 안 함.",
            "물약 슬롯은 '빛의 잠재력'(주스탯+346 30s 5분쿨)이 표준. 무모함의 물약은 3/362킬만 사용.",
            "격노 캐스트 1회당 쇄도!(1258338)·무리의 지도자의 포효가 1:1로 따라붙음 — 격노=쇄도 타이밍.",
        ]},
        "overall": {}, "per_boss": {}}

    for b in ("rank_1_20", "rank_21_100"):
        out["overall"][b] = summarize([f for i, f in per if band(i["rank"]) == b], eff_cd)
    out["overall"]["all"] = summarize([f for _, f in per], eff_cd)

    bosses = defaultdict(list)
    for i, f in per:
        bosses[(i["eid"], i["boss"])].append((i, f))

    for (eid, bname), lst in sorted(bosses.items()):
        ko = BOSS_KO.get(eid, bname)
        fs = [f for _, f in lst]
        d = {"encounter_id": eid, "name_en": bname,
             "kill_med_s": round(pct(sorted(f["dur"] for f in fs), .5)),
             "all": summarize(fs, eff_cd)}
        for b in ("rank_1_20", "rank_21_100"):
            d[b] = summarize([f for i, f in lst if band(i["rank"]) == b], eff_cd)

        # 오프너
        firsts = sorted(f["bw"][0] for f in fs if f["bw"])
        d["opener"] = {
            "first_bw_med_s": round(pct(firsts, .5), 1),
            "first_bw_le5s_pct": round(100 * sum(1 for x in firsts if x <= 5) / len(firsts)),
            "box_precast_pct": round(100 * sum(1 for f in fs if f["box_carried"]) /
                                     max(1, sum(1 for f in fs if f["box"] or f["box_carried"]))),
            "pot_prepull_or_10s_pct": round(100 * sum(
                1 for f in fs if f["pot_carried"] or any(p <= 10 for p, _ in f["pots"])) / len(fs)),
            "seq_top3": [{"seq": list(s), "n": c} for s, c in
                         Counter(f["seq"] for f in fs if f["seq"]).most_common(3)],
        }

        # 물약 시점 분포 (전투 진행률 10% 구간) + 첫/둘째 물약 절대시각
        pot_bins = Counter()
        for f in fs:
            for p, _ in f["pots"]:
                pot_bins[min(9, int(10 * p / f["dur"]))] += 1
        d["pot_time_decile_hist"] = {f"{k*10}-{k*10+10}%": v for k, v in sorted(pot_bins.items())}
        pot_kind = Counter(kind for f in fs for _, kind in f["pots"])
        d["pot_kind"] = dict(pot_kind)
        p1 = sorted(f["pots"][0][0] for f in fs if f["pots"])
        p2 = sorted(f["pots"][1][0] for f in fs if len(f["pots"]) >= 2)
        d["pot_first_med_s"] = round(pct(p1, .5), 1) if p1 else None
        d["pot_second_med_s"] = round(pct(p2, .5), 1) if p2 else None
        d["fights_with_2pots_pct"] = round(100 * sum(1 for f in fs if len(f["pots"]) >= 2) / len(fs))

        # 쫄웨이브(난타) 분석 — 6월 addwave '모은 뒤 격노' 재검증
        wt_fights = sum(1 for f in fs if len(f["wt"]) >= 3)
        if wt_fights >= len(fs) * 0.4:
            hist = Counter()
            for f in fs:
                for t in f["wt"]:
                    hist[int(t // 10) * 10] += 1
            med_dur = pct(sorted(f["dur"] for f in fs), .5)
            hot = sorted(b for b, c in hist.items() if c >= len(fs) * 0.8 and b < med_dur)
            waves = []
            for b in hot:
                if waves and b - waves[-1][1] <= 10: waves[-1][1] = b + 10
                else: waves.append([b, b + 10])
            n_wave_bw = 0; n_bw = 0; wave_gap = []; nonwave_gap = []
            leads = []   # 격노 시각 - 웨이브(난타 클러스터) 시작: +면 '모은 뒤 격노'
            for f in fs:
                for i, t in enumerate(f["bw"]):
                    n_bw += 1
                    near_wt = [x for x in f["wt"] if abs(x - t) <= 8]
                    is_wave = len(near_wt) >= 2
                    if is_wave:
                        n_wave_bw += 1
                        leads.append(t - min(near_wt))
                    if i > 0:
                        (wave_gap if is_wave else nonwave_gap).append(t - f["bw"][i-1])
            d["addwave"] = {
                "wt_fights": wt_fights, "wave_windows_s": [list(w) for w in waves],
                "wave_windows_mmss": [f"{mmss(w0)}~{mmss(w1)}" for w0, w1 in waves],
                "bw_on_wave_pct": round(100 * n_wave_bw / n_bw) if n_bw else None,
                "wave_bw_gap_med_s": round(pct(wave_gap, .5), 1) if wave_gap else None,
                "nonwave_bw_gap_med_s": round(pct(nonwave_gap, .5), 1) if nonwave_gap else None,
                "bw_after_wave_start_pct": round(100 * sum(1 for x in leads if x > 0) / len(leads)) if leads else None,
                "bw_lead_med_s": round(pct(leads, .5), 1) if leads else None,
            }

        # 대홀드(간격 > 실효쿨+15s)가 '언제' 발생하나 — 홀드 후 격노가 떨어진 시각 30s 빈
        hold_hist = Counter()
        n_holds = 0
        for f in fs:
            for i in range(1, len(f["bw"])):
                if f["bw"][i] - f["bw"][i-1] > eff_cd + 15:
                    hold_hist[int(f["bw"][i] // 30) * 30] += 1
                    n_holds += 1
        d["hold_bw_arrival_top"] = [
            {"t": mmss(t), "n": c} for t, c in hold_hist.most_common(5)]
        d["n_holds"] = n_holds
        out["per_boss"][ko] = d

        # 콘솔
        a = d["all"]
        print(f"\n===== {ko} (n={a['n']}, 킬 {mmss(d['kill_med_s'])})", flush=True)
        t20, rest = d["rank_1_20"], d["rank_21_100"]
        fb20 = t20["first_bw_med_s"] if t20 else None
        fbre = rest["first_bw_med_s"] if rest else None
        print(f"  첫 격노 med {d['opener']['first_bw_med_s']}s p25-75 {a['first_bw_p25_p75']} (5s내 {d['opener']['first_bw_le5s_pct']}%) [1-20위 {fb20} vs 21-100위 {fbre}] · 격노/분 {a['bw_per_min_med']}")
        print(f"  격노 간격: {a['bw_gap']}")
        if t20 and rest and t20["bw_gap"] and rest["bw_gap"]:
            print(f"    1-20위 med {t20['bw_gap']['med']}s 즉시 {t20['bw_gap']['즉시_pct']}% 대홀드 {t20['bw_gap']['대홀드_pct']}% | 21-100위 med {rest['bw_gap']['med']}s 즉시 {rest['bw_gap']['즉시_pct']}% 대홀드 {rest['bw_gap']['대홀드_pct']}%")
        print(f"  홀드 도착 핫스팟: {d['hold_bw_arrival_top']} (총 {d['n_holds']}회)")
        print(f"  물약 {a['pot_uses']}회: 첫 물약 {d['pot_first_med_s']}s, 둘째 {d['pot_second_med_s']}s (2개 사용 {d['fights_with_2pots_pct']}%) | 종류 {d['pot_kind']}")
        print(f"    정렬: 물약→3s내 격노 {a['pot_then_bw_within3s_pct']}%, 물약→다음 격노 med {a['pot_to_next_bw_med_s']}s, 겹침 20s+ {a['pot_overlap_ge20s_pct']}%, 격노중 사용 {a['pot_cast_in_bw_pct']}%")
        print(f"  상자 {a['box_uses']}회: 상자→3s내 격노 {a['box_then_bw_within3s_pct']}%, 격노중 사용 {a['box_cast_in_bw_pct']}% · 프리캐스트 {d['opener']['box_precast_pct']}%")
        if "addwave" in d:
            aw = d["addwave"]
            print(f"  웨이브: {aw['wave_windows_mmss']} · 격노의 웨이브 적중 {aw['bw_on_wave_pct']}% · 웨이브 격노 직전간격 {aw['wave_bw_gap_med_s']}s vs 평시 {aw['nonwave_bw_gap_med_s']}s")
            print(f"    웨이브 시작 후 격노 {aw['bw_after_wave_start_pct']}% (격노-웨이브시작 med {aw['bw_lead_med_s']}s)")
        for s in d["opener"]["seq_top3"]:
            print(f"  오프너: {' > '.join(s['seq'])}  ({s['n']}명)")

    json.dump(out, open(DATA / "bm_cd_usage.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n저장: data/bm_cd_usage.json", flush=True)

    # 밴드 요약
    for b in ("rank_1_20", "rank_21_100"):
        s = out["overall"][b]
        print(f"\n[{b}] n={s['n']} 첫격노 {s['first_bw_med_s']}s 격노/분 {s['bw_per_min_med']} "
              f"간격med {s['bw_gap']['med']}s 즉시 {s['bw_gap']['즉시_pct']}% 대홀드 {s['bw_gap']['대홀드_pct']}% "
              f"물약겹침 {s['pot_bw_overlap_med_s']}s", flush=True)


if __name__ == "__main__":
    main()
