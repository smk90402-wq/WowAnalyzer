"""사격 사냥꾼(MM) 쿨기 홀드 실측 — 주요 쿨기 보스별 첫 사용·재사용 간격·홀드 판별.

파싱 패턴은 tmp_mine_bm_cd.py 를 따름
(v2_cache_events.json 1.4GB → raw_decode 증분 스캔, 스크래치패드에 추출 캐시).
★오늘자(2026-07-05) rankings CSV에 있는 킬만 대상 (CSV report_id/fight_id로 필터)★
★영웅특성(어둠 순찰자 vs 파수꾼)이 보스별로 갈리므로 모든 지표를 영웅트리별로 분리★

사용: python tmp_mine_mm_cd.py explore   → 스펠 ID 관측 (실제 ID 확정용)
      python tmp_mine_mm_cd.py           → 본 분석, data/mm_cd_usage.json 출력
"""
from __future__ import annotations
import json, sys, csv
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze\data")
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")
SCRATCH.mkdir(parents=True, exist_ok=True)

# ── 스펠 ID 후보 (explore 로 확정) ─────────────────────────────
TRUESHOT = 288613     # 정조준(Trueshot) — 사격 주기 쿨기
VOLLEY = 260243       # 탄막
BLACK_ARROW = 466930  # 검은 화살 (어둠 순찰자) — 후보
PUZZLE = 383781       # 알게타르 수수께끼 (상자 트링킷 시전)
LUST_IDS = {2825, 32182, 80353, 264667, 390386, 466904, 1260277}
POT_IDS = {1236616: "빛의잠재력", 1236998: "방종의비약", 1236994: "무모함의물약"}
POT_BUFF_S = 30.0
BOX_BUFF_S = 20.0

BOSS_KO = {3176: "아베르지안", 3177: "보라시우스", 3178: "바엘고어&에조라크",
           3179: "살라다르", 3180: "선봉대", 3181: "우주의 왕관",
           3182: "벨로렌", 3183: "한밤의 도래(르우라)", 3306: "카이메루스"}


def load_names():
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    return {int(k): (v.get("name_ko") or v.get("name_en") or "?") for k, v in db.items() if isinstance(v, dict)}


def load_hero_sets():
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))["Hunter/Marksmanship"]
    return {t: set(nd["id"] for nd in h["nodes"]) for t, h in tt["hero"].items()}


def load_wanted():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    mm = [r for r in rows if r["class"] == "Hunter" and r["spec"] == "Marksmanship"]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    hero_sets = load_hero_sets()
    wanted = {}
    for r in mm:
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
        hero = "불명"
        if p.get("nodes"):
            nodes = set(int(x) for x in p["nodes"])
            best = max(hero_sets, key=lambda t: len(nodes & hero_sets[t]))
            if len(nodes & hero_sets[best]) >= 8: hero = best
        wanted[key] = {
            "boss": r["encounter_name"], "eid": int(r["encounter_id"]),
            "rank": int(r["rank"]), "char": ch, "hero": hero,
            "t0": f["startTime"], "t1": f["endTime"],
        }
    return wanted


def stream_filter(wanted):
    cache = SCRATCH / "mm_cd_events.json"
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
    """영웅트리별 캐스트/버프 ID 관측."""
    for hero in ("어둠 순찰자", "파수꾼"):
        keys = [k for k, w in wanted.items() if w["hero"] == hero and k in ev]
        cast_ids = Counter(); cast_fights = Counter()
        buff_fights = Counter()
        for k in keys:
            e = ev[k]
            cseen, bseen = set(), set()
            for c in (e.get("casts") or []):
                if len(c) >= 3 and c[2] == "cast":
                    cast_ids[c[1]] += 1; cseen.add(c[1])
            for b in (e.get("buffs") or []):
                if len(b) >= 3 and b[2] == "applybuff": bseen.add(b[1])
            for x in cseen: cast_fights[x] += 1
            for x in bseen: buff_fights[x] += 1
        nf = len(keys)
        print(f"\n===== {hero} (n_fights={nf}) — 캐스트 ID top40 =====")
        for sid, c in cast_ids.most_common(40):
            print(f"  {sid:>8} {names.get(sid,'?'):<22} 총{c:>6}  판당 {c/max(1,nf):>5.1f}  출현 {cast_fights[sid]}/{nf}")
        print(f"  -- applybuff 판 출현율 상위 25 --")
        for sid, c in buff_fights.most_common(25):
            print(f"  {sid:>8} {names.get(sid,'?'):<22} 출현 {c}/{nf}")
    # 블러드/물약 확인
    lust = sum(1 for e in ev.values() for b in (e.get("buffs") or []) if len(b) >= 3 and b[1] in LUST_IDS)
    print(f"\n블러드 계열 버프 이벤트 총 {lust}건 / {len(ev)}킬")


# ── 확정 ID (explore 결과로 확정, 2026-07-05) ──────────────────
# 정조준(288613): 갭 p5=120.4s → 실효 2분 쿨. DR/SEN 공통 주기 쿨기.
# 울부짖는 화살(392060): 갭 p5=116.8s, 정조준과 1:1 페어(DR 전용) — 정조준 버프 중 대체되는 마무리기.
# 달빛 회전 표창(1264949): 갭 p5=114.1s (SEN 전용) — 정조준 주기에 연동되는 버스트 창.
# 연발 공격(260243): 갭 p5=45.3s → 별도의 짧은(~45~60s) 광역 쿨기, 정조준과 별개 주기.
# 검은 화살(466930): 갭 p5=2.1s → 스팸형 소모기(홀드 대상 아님, 채굴 제외).
# 돌격!(1259633): 19/172(SEN)만 시전 — 픽업률 낮아 대표성 없음(참고만).
# 블러드(2825 등): 335/341킬에서 관측 — BM 데이터셋과 달리 이 데이터셋엔 블러드 존재.
TRUESHOT = 288613
VOLLEY = 260243
WAILING_ARROW = 392060     # DR 전용 (정조준 연동 버스트)
CHAKRAM = 1264949           # SEN 전용 (정조준 연동 버스트)
CHARGE = 1259633            # SEN 저채택 (참고)
PUZZLE = 383781
POT_IDS = {1236616: "빛의잠재력", 1236998: "방종의비약", 1236994: "무모함의물약"}
POT_BUFF_S = 30.0
BOX_BUFF_S = 20.0
BLOODLUST_S = 40.0

BOSS_KO = {3176: "아베르지안", 3177: "보라시우스", 3178: "바엘고어&에조라크",
           3179: "살라다르", 3180: "선봉대", 3181: "우주의 왕관",
           3182: "벨로렌", 3183: "한밤의 도래(르우라)", 3306: "카이메루스"}

NOISE = {264735, 781, 186257, 186258, 186265, 147362, 109304, 6262, 1234768,
         19577, 34477, 136, 883, 20572, 109248, 187650, 103740, 26297, 1262857,
         227723, 1236616, 1236998, 1236994, 257284}


def overlap_s(win, lo, hi):
    tot = 0.0
    for a, b in win:
        tot += max(0.0, min(b, hi) - max(a, lo))
    return tot


def parse_fight(info, e, names):
    t0, t1 = info["t0"], info["t1"]
    dur = (t1 - t0) / 1000
    casts = sorted((c for c in (e.get("casts") or []) if len(c) >= 3 and c[2] == "cast"),
                   key=lambda c: c[0])
    buffs = sorted((b for b in (e.get("buffs") or []) if len(b) >= 3), key=lambda b: b[0])

    def rel(ts): return (ts - t0) / 1000

    ts_cast = [(rel(c[0]), c[1]) for c in casts]
    trueshot = [t for t, sid in ts_cast if sid == TRUESHOT]
    volley = [t for t, sid in ts_cast if sid == VOLLEY]
    wailing = [t for t, sid in ts_cast if sid == WAILING_ARROW]
    chakram = [t for t, sid in ts_cast if sid == CHAKRAM]
    pots = [(rel(c[0]), POT_IDS[c[1]]) for c in casts if c[1] in POT_IDS]
    box = [rel(c[0]) for c in casts if c[1] == PUZZLE]

    # 정조준 버프 실측 창 (apply→remove)
    ts_win, act = [], None
    for b in buffs:
        if b[1] != TRUESHOT: continue
        if b[2] == "applybuff": act = rel(b[0])
        elif b[2] == "removebuff" and act is not None:
            ts_win.append((act, rel(b[0]))); act = None
    if act is not None: ts_win.append((act, dur))
    if not ts_win:
        ts_win = [(t, t + 15) for t in trueshot]

    # 블러드/영웅심 계열 시작 시각(대상 무관, applybuff 전체에서 탐지)
    lust_starts = []
    for b in buffs:
        if b[1] in LUST_IDS and b[2] == "applybuff":
            lust_starts.append(rel(b[0]))
    lust_starts = sorted(set(round(x, 1) for x in lust_starts))

    def carried_in(sid):
        for b in buffs:
            if b[1] != sid: continue
            return b[2] in ("removebuff", "refreshbuff") and rel(b[0]) > 0.5
        return False

    seq = []
    for t, sid in ts_cast:
        if t > 12: break
        if sid in NOISE: continue
        if seq and t - seq[-1][0] < 0.75 and sid == seq[-1][1]: continue
        seq.append((t, sid))
    seq_names = tuple(names.get(a, f"#{a}") for _, a in seq[:5])

    return {
        "rank": info["rank"], "dur": dur, "hero": info["hero"],
        "ts": trueshot, "ts_win": ts_win, "volley": volley,
        "wailing": wailing, "chakram": chakram,
        "pots": pots, "box": box,
        "box_carried": carried_in(PUZZLE),
        "pot_carried": any(carried_in(s) for s in POT_IDS),
        "lust_starts": lust_starts,
        "seq": seq_names,
    }


def gap_stats(g, eff_cd):
    if not g: return None
    n = len(g)
    return {
        "n": n, "p25": round(pct(g, .25), 1), "med": round(pct(g, .5), 1),
        "p75": round(pct(g, .75), 1),
        "즉시_pct": round(100 * sum(1 for x in g if x <= eff_cd + 3) / n),
        "소홀드_pct": round(100 * sum(1 for x in g if eff_cd + 3 < x <= eff_cd + 20) / n),
        "대홀드_pct": round(100 * sum(1 for x in g if x > eff_cd + 20) / n),
    }


def summarize(fs, eff_cd_ts, eff_cd_volley):
    if not fs: return None
    ts_gaps = [g for f in fs for g in
               (f["ts"][i+1] - f["ts"][i] for i in range(len(f["ts"]) - 1))]
    vol_gaps = [g for f in fs for g in
                (f["volley"][i+1] - f["volley"][i] for i in range(len(f["volley"]) - 1))]
    first_ts = sorted(f["ts"][0] for f in fs if f["ts"])
    first_vol = sorted(f["volley"][0] for f in fs if f["volley"])
    tspm = sorted(len(f["ts"]) / (f["dur"] / 60) for f in fs if f["dur"] > 0)
    volpm = sorted(len(f["volley"]) / (f["dur"] / 60) for f in fs if f["dur"] > 0)

    # 정조준 창 내 hero 버스트기 사용률 (DR=울부짖는 화살, SEN=달빛 회전 표창)
    wailing_in_ts = wailing_n = 0
    chakram_in_ts = chakram_n = 0
    for f in fs:
        for t in f["wailing"]:
            wailing_n += 1
            if any(a <= t <= b for a, b in f["ts_win"]): wailing_in_ts += 1
        for t in f["chakram"]:
            chakram_n += 1
            if any(a <= t <= b for a, b in f["ts_win"]): chakram_in_ts += 1

    # 물약↔정조준 정렬
    pot_ol, pot_n, pot_in_ts, pot_next3, pot_next = [], 0, 0, 0, []
    for f in fs:
        for p, _ in f["pots"]:
            pot_n += 1
            pot_ol.append(overlap_s(f["ts_win"], p, p + POT_BUFF_S))
            if any(a <= p <= b for a, b in f["ts_win"]): pot_in_ts += 1
            nxt = [t for t in f["ts"] if t >= p - 1]
            if nxt:
                d = nxt[0] - p
                pot_next.append(d)
                if d <= 3: pot_next3 += 1
    box_ol, box_n, box_in_ts, box_next3 = [], 0, 0, 0
    for f in fs:
        for p in f["box"]:
            box_n += 1
            box_ol.append(overlap_s(f["ts_win"], p, p + BOX_BUFF_S))
            if any(a <= p <= b for a, b in f["ts_win"]): box_in_ts += 1
            nxt = [t for t in f["ts"] if t >= p - 1]
            if nxt and nxt[0] - p <= 3: box_next3 += 1

    # 블러드↔정조준 정렬: 블러드 시작 후 3s내 정조준 캐스트 / 정조준 창과 겹침
    lust_n, lust_in_ts, lust_next3, lust_next = 0, 0, 0, []
    for f in fs:
        for l in f["lust_starts"]:
            lust_n += 1
            if any(a <= l <= b for a, b in f["ts_win"]): lust_in_ts += 1
            nxt = [t for t in f["ts"] if t >= l - 1]
            if nxt:
                d = nxt[0] - l
                lust_next.append(d)
                if d <= 3: lust_next3 += 1

    return {
        "n": len(fs),
        "first_ts_med_s": round(pct(first_ts, .5), 1) if first_ts else None,
        "first_ts_p25_p75": [round(pct(first_ts, .25), 1), round(pct(first_ts, .75), 1)] if first_ts else None,
        "ts_per_min_med": round(pct(tspm, .5), 2) if tspm else None,
        "ts_gap": gap_stats(ts_gaps, eff_cd_ts),
        "first_volley_med_s": round(pct(first_vol, .5), 1) if first_vol else None,
        "volley_per_min_med": round(pct(volpm, .5), 2) if volpm else None,
        "volley_gap": gap_stats(vol_gaps, eff_cd_volley),
        "wailing_uses": wailing_n,
        "wailing_in_ts_window_pct": round(100 * wailing_in_ts / wailing_n) if wailing_n else None,
        "chakram_uses": chakram_n,
        "chakram_in_ts_window_pct": round(100 * chakram_in_ts / chakram_n) if chakram_n else None,
        "pot_uses": pot_n,
        "pot_ts_overlap_med_s": round(pct(pot_ol, .5), 1) if pot_ol else None,
        "pot_cast_in_ts_pct": round(100 * pot_in_ts / pot_n) if pot_n else None,
        "pot_then_ts_within3s_pct": round(100 * pot_next3 / pot_n) if pot_n else None,
        "pot_to_next_ts_med_s": round(pct(pot_next, .5), 1) if pot_next else None,
        "box_uses": box_n,
        "box_ts_overlap_med_s": round(pct(box_ol, .5), 1) if box_ol else None,
        "box_cast_in_ts_pct": round(100 * box_in_ts / box_n) if box_n else None,
        "box_then_ts_within3s_pct": round(100 * box_next3 / box_n) if box_n else None,
        "lust_events": lust_n,
        "lust_cast_in_ts_pct": round(100 * lust_in_ts / lust_n) if lust_n else None,
        "lust_then_ts_within3s_pct": round(100 * lust_next3 / lust_n) if lust_n else None,
        "lust_to_next_ts_med_s": round(pct(lust_next, .5), 1) if lust_next else None,
    }


def analyze(wanted, ev, names):
    per = []
    for k, info in wanted.items():
        e = ev.get(k)
        if not e: continue
        f = parse_fight(info, e, names)
        if len(f["ts"]) < 2: continue
        per.append((info, f))
    print(f"분석 대상 킬(정조준 2회 이상): {len(per)}", flush=True)
    hc = Counter(i["hero"] for i, _ in per)
    print(f"영웅트리: {dict(hc)}", flush=True)

    all_ts_gaps = sorted(g for _, f in per for g in
                          (f["ts"][i+1] - f["ts"][i] for i in range(len(f["ts"]) - 1)))
    eff_ts = pct(all_ts_gaps, .05)
    all_vol_gaps = sorted(g for _, f in per for g in
                           (f["volley"][i+1] - f["volley"][i] for i in range(len(f["volley"]) - 1)))
    eff_vol = pct(all_vol_gaps, .05) if all_vol_gaps else 45.0
    print(f"정조준 간격 p5(실효쿨)={eff_ts:.1f}s, p1={pct(all_ts_gaps,.01):.1f}s", flush=True)
    print(f"연발공격 간격 p5(실효쿨)={eff_vol:.1f}s, p1={pct(all_vol_gaps,.01):.1f}s", flush=True)

    def band(r): return "rank_1_20" if r <= 20 else "rank_21_100"

    out = {"meta": {
        "date": "2026-07-05", "n_kills": len(per),
        "hero_adoption": dict(hc),
        "eff_cd_s": {"trueshot": round(eff_ts, 1), "volley": round(eff_vol, 1)},
        "spells": {"trueshot": TRUESHOT, "volley": VOLLEY, "wailing_arrow_dr": WAILING_ARROW,
                   "chakram_sen": CHAKRAM, "puzzle_box": PUZZLE,
                   "potions": {str(k): v for k, v in POT_IDS.items()}},
        "notes": [
            "정조준(288613) 간격 p5=120s → 실효 2분 쿨. DR/SEN 공통.",
            "울부짖는 화살(392060, DR 전용)·달빛 회전 표창(1264949, SEN 전용) 모두 간격 p5≈114~117s로 정조준 주기와 동기 — 각 영웅특성의 '정조준 연동 버스트'로 확정.",
            "연발 공격(260243) 간격 p5=45s → 정조준과 별개의 짧은 광역 쿨기(1분 미만 티어).",
            "검은 화살(466930)은 간격 p5=2.1s(스팸형 소모기)라 홀드 채굴 대상에서 제외.",
            "블러드/영웅심 계열 335/341킬에서 관측 — BM 데이터셋(0/362)과 달리 이 데이터셋엔 블러드 존재.",
        ]},
        "overall": {}, "per_boss": {}}

    for b in ("rank_1_20", "rank_21_100"):
        out["overall"][b] = summarize([f for i, f in per if band(i["rank"]) == b], eff_ts, eff_vol)
    out["overall"]["all"] = summarize([f for _, f in per], eff_ts, eff_vol)
    for hero in ("어둠 순찰자", "파수꾼"):
        out["overall"][f"hero_{hero}"] = summarize([f for i, f in per if i["hero"] == hero], eff_ts, eff_vol)

    bosses = defaultdict(list)
    for i, f in per:
        bosses[(i["eid"], i["boss"])].append((i, f))

    for (eid, bname), lst in sorted(bosses.items()):
        ko = BOSS_KO.get(eid, bname)
        fs = [f for _, f in lst]
        d = {"encounter_id": eid, "name_en": bname,
             "kill_med_s": round(pct(sorted(f["dur"] for f in fs), .5)),
             "all": summarize(fs, eff_ts, eff_vol)}
        for hero in ("어둠 순찰자", "파수꾼"):
            sub = [f for i, f in lst if i["hero"] == hero]
            if len(sub) >= 5:
                d[f"hero_{hero}"] = summarize(sub, eff_ts, eff_vol)
        for b in ("rank_1_20", "rank_21_100"):
            d[b] = summarize([f for i, f in lst if band(i["rank"]) == b], eff_ts, eff_vol)

        firsts = sorted(f["ts"][0] for f in fs if f["ts"])
        d["opener"] = {
            "first_ts_med_s": round(pct(firsts, .5), 1),
            "first_ts_le5s_pct": round(100 * sum(1 for x in firsts if x <= 5) / len(firsts)),
            "box_precast_pct": round(100 * sum(1 for f in fs if f["box_carried"]) /
                                     max(1, sum(1 for f in fs if f["box"] or f["box_carried"]))),
            "pot_prepull_or_10s_pct": round(100 * sum(
                1 for f in fs if f["pot_carried"] or any(p <= 10 for p, _ in f["pots"])) / len(fs)),
            "seq_top3": [{"seq": list(s), "n": c} for s, c in
                         Counter(f["seq"] for f in fs if f["seq"]).most_common(3)],
        }

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

        # 대홀드(정조준 간격 > 실효쿨+20s) 발생 시점
        hold_hist = Counter()
        n_holds = 0
        for f in fs:
            for i2 in range(1, len(f["ts"])):
                if f["ts"][i2] - f["ts"][i2-1] > eff_ts + 20:
                    hold_hist[int(f["ts"][i2] // 30) * 30] += 1
                    n_holds += 1
        d["hold_ts_arrival_top"] = [{"t": mmss(t), "n": c} for t, c in hold_hist.most_common(5)]
        d["n_holds"] = n_holds
        out["per_boss"][ko] = d

        a = d["all"]
        print(f"\n===== {ko} (n={a['n']}, 킬 {mmss(d['kill_med_s'])})", flush=True)
        print(f"  첫 정조준 med {d['opener']['first_ts_med_s']}s p25-75 {a['first_ts_p25_p75']} (5s내 {d['opener']['first_ts_le5s_pct']}%) · 정조준/분 {a['ts_per_min_med']}", flush=True)
        print(f"  정조준 간격: {a['ts_gap']}", flush=True)
        print(f"  연발공격 간격: {a['volley_gap']} (분당 {a['volley_per_min_med']})", flush=True)
        print(f"  홀드 도착 핫스팟: {d['hold_ts_arrival_top']} (총 {d['n_holds']}회)", flush=True)
        print(f"  hero버스트 정조준창내: 울부짖는화살 {a['wailing_in_ts_window_pct']}%({a['wailing_uses']}회) · 표창 {a['chakram_in_ts_window_pct']}%({a['chakram_uses']}회)", flush=True)
        print(f"  물약 {a['pot_uses']}회: 첫 {d['pot_first_med_s']}s 둘째 {d['pot_second_med_s']}s(2개 {d['fights_with_2pots_pct']}%) 정렬: 3s내정조준 {a['pot_then_ts_within3s_pct']}% 겹침med {a['pot_ts_overlap_med_s']}s", flush=True)
        print(f"  상자 {a['box_uses']}회: 3s내정조준 {a['box_then_ts_within3s_pct']}% 프리캐스트 {d['opener']['box_precast_pct']}%", flush=True)
        print(f"  블러드 {a['lust_events']}회: 3s내정조준 {a['lust_then_ts_within3s_pct']}% 정조준창내 {a['lust_cast_in_ts_pct']}% 다음정조준까지med {a['lust_to_next_ts_med_s']}s", flush=True)
        for s in d["opener"]["seq_top3"]:
            print(f"  오프너: {' > '.join(s['seq'])}  ({s['n']}명)", flush=True)

    json.dump(out, open(DATA / "mm_cd_usage.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n저장: data/mm_cd_usage.json", flush=True)

    print("\n===== 영웅트리별 전체 요약 =====", flush=True)
    for hero in ("어둠 순찰자", "파수꾼"):
        s = out["overall"][f"hero_{hero}"]
        if not s: continue
        print(f"[{hero}] n={s['n']} 첫정조준 {s['first_ts_med_s']}s 정조준/분 {s['ts_per_min_med']} "
              f"간격med {s['ts_gap']['med']}s 즉시 {s['ts_gap']['즉시_pct']}% 대홀드 {s['ts_gap']['대홀드_pct']}% "
              f"물약겹침 {s['pot_ts_overlap_med_s']}s 블러드정렬3s {s['lust_then_ts_within3s_pct']}%", flush=True)

    print("\n===== 랭크 밴드 요약 =====", flush=True)
    for b in ("rank_1_20", "rank_21_100"):
        s = out["overall"][b]
        print(f"[{b}] n={s['n']} 첫정조준 {s['first_ts_med_s']}s 정조준/분 {s['ts_per_min_med']} "
              f"간격med {s['ts_gap']['med']}s 즉시 {s['ts_gap']['즉시_pct']}% 대홀드 {s['ts_gap']['대홀드_pct']}% "
              f"물약겹침 {s['pot_ts_overlap_med_s']}s", flush=True)


def main():
    names = load_names()
    wanted = load_wanted()
    print(f"MM player-fights wanted: {len(wanted)}", flush=True)
    hc = Counter(w["hero"] for w in wanted.values())
    print(f"영웅트리(wanted): {dict(hc)}", flush=True)
    ev = stream_filter(wanted)
    print(f"events hit: {len(ev)}/{len(wanted)}", flush=True)
    hc2 = Counter(w["hero"] for k, w in wanted.items() if k in ev)
    print(f"영웅트리(events): {dict(hc2)}", flush=True)
    if "explore" in sys.argv:
        explore(wanted, ev, names)
        return
    analyze(wanted, ev, names)


if __name__ == "__main__":
    main()
