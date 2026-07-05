"""고통 흑마 쿨기 홀드 실측 — 주요 쿨기 보스별 첫 사용·재사용 간격·홀드 판별.

파싱 패턴은 tmp_mine_bm_cd.py / tmp_mine_frost_cd.py 를 따름
(v2_cache_events.json 1.4GB → raw_decode 증분 스캔, 스크래치패드에 추출 캐시).
★오늘자(2026-07-05) rankings CSV에 있는 킬만 대상★

사용: python tmp_mine_aff_cd.py explore   → 스펠 ID 관측 (실제 ID 확정용)
      python tmp_mine_aff_cd.py           → 본 분석, data/aff_cd_usage.json 출력

explore 결과로 확정된 것 (2026-07-05, 301킬):
  암흑시선 소환(205180)이 유일한 주기 쿨기(2분, 20초 지속, 고통/부패/불안정한고통 공증20%) — 301/301판 출현, 판당 3.0회.
  일리단/드레노어 시절 '영혼 부패'(386997) 류 스킬은 이 확장에 없음(0/301) — SOULROT/VILE/PHANTOM/MALEV/RAPTURE 전부 0.
  블러드/영웅심/시간왜곡 계열 0/301 — 미드나잇에 블러드 없음(BM/Frost와 동일 확인).
  물약: 빛의 잠재력(1236616) 277/301판 표준, 무모함의 물약(1236994) 22/301판 소수.
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
DARKGLARE = 205180   # 암흑시선 소환 (2분급) — 유일한 메이저 주기 쿨기(20초 지속)
DARKHARVEST = 1257052  # 암흑의 수확 (1분쿨, 정신집중 3초) — 1분급 쿨기. 301/301판, 판당 7.4회
HAUNT = 48181        # 유령 출몰 (15초쿨, 처치시 초기화) — 단축쿨/필러. 301/301판, 판당 17.4회
SOULROT = 386997     # 영혼 부패 (1분급 후보) — 0/301, 미채택
VILE = 278350        # 사악한 오염 (충전/짧은 쿨 후보) — 0/301
PHANTOM = 205179     # 유령 특이점 — 0/301
MALEV = 442726       # 적개심 (영웅특성 액티브 쿨기 후보) — 0/301, 미채택
RAPTURE = 324536     # 부정한 격변 (조각 소비) — 0/301
LUST_IDS = {2825, 32182, 80353, 264667, 390386, 466904, 1260277}  # 전부 0/301
POT_IDS = {1236616: "빛의잠재력", 1236998: "방종의비약", 1236994: "무모함의물약"}
PUZZLE = 383781      # 알게타르 수수께끼 상자 — 0/301(장신구 미보유)
POT_BUFF_S = 30.0
DARKGLARE_BUFF_S = 20.0

# 도트/조각 소비(★쿨기 홀드와 별개 차원: 도트 갱신 창 + 영혼 조각 소비 타이밍★)
AGONY = 980          # 고통 — 18초 도트, 조각 생성, 갱신해도 현재 피해량 유지(클리핑 페널티 없음)
UA = 1259790         # 불안정한 고통 — 8초, 조각 1개 소비(중첩형), 해제시 폭발+침묵
SEED = 27243         # 부패의 씨앗 — 조각 1개 소비, 12초 지연 폭발

BOSS_KO = {3176: "아베르지안", 3177: "보라시우스", 3178: "바엘고어&에조라크",
           3179: "살라다르", 3180: "선봉대", 3181: "우주의 왕관",
           3182: "벨로렌", 3183: "한밤의 도래(르우라)", 3306: "카이메루스"}


def load_names():
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    return {int(k): (v.get("name_ko") or v.get("name_en") or "?") for k, v in db.items() if isinstance(v, dict)}


def load_wanted():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    aff = [r for r in rows if r["class"] == "Warlock" and r["spec"] == "Affliction"]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    wanted = {}
    for r in aff:
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
        wanted[key] = {
            "boss": r["encounter_name"], "eid": int(r["encounter_id"]),
            "rank": int(r["rank"]), "char": ch,
            "t0": f["startTime"], "t1": f["endTime"],
        }
    return wanted


def stream_filter(wanted):
    cache = SCRATCH / "aff_cd_events.json"
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
    print(f"\n== 캐스트 ID top60 (n_fights={nf}) ==")
    for sid, c in cast_ids.most_common(60):
        print(f"  {sid:>8} {names.get(sid,'?'):<22} 총{c:>7}  판당출현 {cast_fights[sid]}/{nf}  판당횟수 {c/max(1,cast_fights[sid]):.1f}")
    print("\n== applybuff ID top60 ==")
    for sid, c in buff_ids.most_common(60):
        print(f"  {sid:>8} {names.get(sid,'?'):<22} 총{c:>7}  판당출현 {buff_fights[sid]}/{nf}")
    print("\n== 후보 확인 ==")
    for sid in sorted({DARKGLARE, SOULROT, VILE, PHANTOM, MALEV, RAPTURE, PUZZLE} | LUST_IDS | set(POT_IDS)):
        print(f"  {sid:>8} {names.get(sid,'?'):<22} cast총 {cast_ids.get(sid,0):>7} (판 {cast_fights.get(sid,0)}) / buff총 {buff_ids.get(sid,0):>7} (판 {buff_fights.get(sid,0)})")


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

    dg = [rel(c[0]) for c in casts if c[1] == DARKGLARE]
    dh = [rel(c[0]) for c in casts if c[1] == DARKHARVEST]
    haunt = [rel(c[0]) for c in casts if c[1] == HAUNT]
    agony = [rel(c[0]) for c in casts if c[1] == AGONY]
    ua = [rel(c[0]) for c in casts if c[1] == UA]
    seed = [rel(c[0]) for c in casts if c[1] == SEED]
    pots = [(rel(c[0]), POT_IDS[c[1]]) for c in casts if c[1] in POT_IDS]

    # 암흑시선 버프 실측 창 (apply→remove)
    dg_win, act = [], None
    for b in buffs:
        if b[1] != DARKGLARE: continue
        if b[2] == "applybuff": act = rel(b[0])
        elif b[2] == "removebuff" and act is not None:
            dg_win.append((act, rel(b[0]))); act = None
    if act is not None: dg_win.append((act, dur))
    if not dg_win:
        dg_win = [(t, t + DARKGLARE_BUFF_S) for t in dg]

    def carried_in(sid):
        for b in buffs:
            if b[1] != sid: continue
            return b[2] in ("removebuff", "refreshbuff") and rel(b[0]) > 0.5
        return False

    # 오프너 쿨기 순서: 첫 15초, 추적 대상(암흑시선/암흑의 수확/유령 출몰/물약/도트 빌더)만, 750ms 중복 접기
    TRACKED = {DARKGLARE, DARKHARVEST, HAUNT, AGONY, UA, SEED} | set(POT_IDS)
    seq = []
    for c in casts:
        t = rel(c[0])
        if t > 15: break
        if c[1] not in TRACKED: continue
        if seq and t - seq[-1][0] < 0.75 and c[1] == seq[-1][1]: continue
        seq.append((t, c[1]))
    seq_names = tuple(names.get(a, f"#{a}") for _, a in seq[:6])

    return {
        "rank": info["rank"], "dur": dur,
        "dg": dg, "dg_win": dg_win, "pots": pots,
        "dh": dh, "haunt": haunt, "agony": agony, "ua": ua, "seed": seed,
        "seq": seq_names,
        "pot_carried": any(carried_in(s) for s in POT_IDS),
    }


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


def dot_refresh_stats(casts_list, dot_dur):
    """도트 재시전 간격을 지속시간 대비 분류: 조기 클리핑(간격<dur-2) vs 정시갱신(dur-2~dur+2) vs 만료후리필(>dur+2).
    (buffs 캐시에 대상 디버프 적용/해제 이벤트가 없어 캐스트 간격만으로 근사)"""
    gaps = []
    for ts in casts_list:
        gaps += [ts[i+1] - ts[i] for i in range(len(ts) - 1)]
    if not gaps: return None
    n = len(gaps)
    early = sum(1 for g in gaps if g < dot_dur - 2)
    ontime = sum(1 for g in gaps if dot_dur - 2 <= g <= dot_dur + 2)
    late = sum(1 for g in gaps if g > dot_dur + 2)
    late_over = [g - dot_dur for g in gaps if g > dot_dur + 2]
    return {
        "n": n, "med_gap_s": round(pct(gaps, .5), 1),
        "조기클리핑_pct": round(100 * early / n), "정시갱신_pct": round(100 * ontime / n),
        "만료후리필_pct": round(100 * late / n),
        "만료후리필_med_초과분_s": round(pct(late_over, .5), 1) if late_over else None,
    }


def summarize_cd(fs, key, eff_cd):
    """DARKGLARE 외 다른 쿨기(암흑의 수확 등)용 — 물약 정렬 없이 간격/분당횟수만."""
    if not fs: return None
    arr = [f[key] for f in fs]
    gaps = [g for ts in arr for g in (ts[i+1] - ts[i] for i in range(len(ts) - 1))]
    first = sorted(ts[0] for ts in arr if ts)
    per_min = sorted(len(ts) / (f["dur"] / 60) for f, ts in zip(fs, arr) if f["dur"] > 0)
    return {
        "n": sum(1 for ts in arr if ts),
        "first_med_s": round(pct(first, .5), 1) if first else None,
        "per_min_med": round(pct(per_min, .5), 2) if per_min else None,
        "gap": gap_stats(gaps, eff_cd),
    }


def summarize(fs, eff_cd):
    if not fs: return None
    gaps = [g for f in fs for g in
            (f["dg"][i+1] - f["dg"][i] for i in range(len(f["dg"]) - 1))]
    first = sorted(f["dg"][0] for f in fs if f["dg"])
    dgpm = sorted(len(f["dg"]) / (f["dur"] / 60) for f in fs if f["dur"] > 0)
    pot_ol, pot_n, pot_in_dg, pot_next3, pot_next = [], 0, 0, 0, []
    for f in fs:
        for p, _ in f["pots"]:
            pot_n += 1
            pot_ol.append(overlap_s(f["dg_win"], p, p + POT_BUFF_S))
            if any(a <= p <= b for a, b in f["dg_win"]): pot_in_dg += 1
            nxt = [t for t in f["dg"] if t >= p - 1]
            if nxt:
                d = nxt[0] - p
                pot_next.append(d)
                if d <= 3: pot_next3 += 1
    return {
        "n": len(fs),
        "first_dg_med_s": round(pct(first, .5), 1) if first else None,
        "first_dg_p25_p75": [round(pct(first, .25), 1), round(pct(first, .75), 1)] if first else None,
        "dg_per_min_med": round(pct(dgpm, .5), 2) if dgpm else None,
        "dg_gap": gap_stats(gaps, eff_cd),
        "pot_uses": pot_n,
        "pot_dg_overlap_med_s": round(pct(pot_ol, .5), 1) if pot_ol else None,
        "pot_overlap_ge15s_pct": round(100 * sum(1 for x in pot_ol if x >= 15) / pot_n) if pot_n else None,
        "pot_cast_in_dg_pct": round(100 * pot_in_dg / pot_n) if pot_n else None,
        "pot_then_dg_within3s_pct": round(100 * pot_next3 / pot_n) if pot_n else None,
        "pot_to_next_dg_med_s": round(pct(pot_next, .5), 1) if pot_next else None,
    }


def main():
    names = load_names()
    wanted = load_wanted()
    print(f"고통 흑마 player-fights wanted: {len(wanted)}", flush=True)
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
        if len(f["dg"]) < 1: continue
        per.append((info, f))
    print(f"분석 대상 킬: {len(per)}", flush=True)

    all_gaps = sorted(g for _, f in per for g in
                      (f["dg"][i+1] - f["dg"][i] for i in range(len(f["dg"]) - 1)))
    eff_cd = pct(all_gaps, .05) if all_gaps else 120.0
    print(f"암흑시선 간격 p5(실효 쿨 추정) = {eff_cd:.1f}s, p1 = {pct(all_gaps, .01):.1f}s", flush=True)

    dh_gaps = sorted(g for _, f in per for g in
                     (f["dh"][i+1] - f["dh"][i] for i in range(len(f["dh"]) - 1)) if len(f["dh"]) >= 2)
    eff_cd_dh = pct(dh_gaps, .05) if dh_gaps else 60.0
    print(f"암흑의 수확 간격 p5(실효 쿨 추정) = {eff_cd_dh:.1f}s", flush=True)

    def band(r): return "rank_1_20" if r <= 20 else "rank_21_100"

    out = {"meta": {
        "date": "2026-07-05", "n_kills": len(per),
        "eff_cd_s": round(eff_cd, 1), "eff_cd_dark_harvest_s": round(eff_cd_dh, 1),
        "spells": {"summon_darkglare": DARKGLARE, "dark_harvest": DARKHARVEST, "haunt": HAUNT,
                   "agony": AGONY, "unstable_affliction": UA, "seed_of_corruption": SEED,
                   "potions": {str(k): v for k, v in POT_IDS.items()}},
        "notes": [
            "메이저 주기 쿨기는 2종: 암흑시선 소환(205180, 2분쿨/20초지속)과 암흑의 수확(1257052, 1분쿨/정신집중3초). "
            "영혼 부패·사악한 오염 등 드래곤플라이트기 쿨기는 트리에서 사라짐(explore 0/301) — 적개심(442726, 헤로 액티브)도 0/301로 미채택.",
            "블러드/영웅심/시간왜곡 계열 0/301킬 — 미드나잇에는 블러드가 없어 '블러드 정렬' 항목은 성립 안 함(BM/Frost와 동일 확인).",
            "물약 슬롯은 '빛의 잠재력'(1236616)이 표준(277/301판). 무모함의 물약은 22/301판만 사용.",
            "암흑시선 소환은 고통/부패/불안정한고통 공증 20%(대상 디버프 없이 시전자 버프로 적용) — "
            "3가지 DoT를 최대한 걸어둔 상태에서 켜는 게 이득이라 오프너보다 '도트 정착 후 1차'가 이론상 유리.",
            "유령 출몰(48181)은 15초쿨(처치시 초기화)이라 '홀드'보다 '즉시 재시전' 위주 — 참고 지표로만 수록.",
            "도트(고통 18초/불안정한 고통 8초) 재시전 간격은 buffs 캐시에 대상 디버프 apply/remove 이벤트가 없어(자기 버프만 기록) 캐스트 간격으로 근사 분류.",
            "불안정한 고통은 캐스트당 조각 1개 소비 — 암흑시선 창(전체 시간의 일부) 안에서 쓴 비율이 창 시간비율보다 높으면 조각을 몰아서 쓰는 규율이 있다는 뜻.",
        ]},
        "overall": {}, "per_boss": {}}

    for b in ("rank_1_20", "rank_21_100"):
        out["overall"][b] = summarize([f for i, f in per if band(i["rank"]) == b], eff_cd)
    out["overall"]["all"] = summarize([f for _, f in per], eff_cd)
    out["overall"]["rank_1_10"] = summarize([f for i, f in per if i["rank"] <= 10], eff_cd)

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

        firsts = sorted(f["dg"][0] for f in fs if f["dg"])
        d["opener"] = {
            "first_dg_med_s": round(pct(firsts, .5), 1) if firsts else None,
            "first_dg_le10s_pct": round(100 * sum(1 for x in firsts if x <= 10) / len(firsts)) if firsts else None,
            "first_dg_10_25s_pct": round(100 * sum(1 for x in firsts if 10 < x <= 25) / len(firsts)) if firsts else None,
            "pot_prepull_or_10s_pct": round(100 * sum(
                1 for f in fs if f["pot_carried"] or any(p <= 10 for p, _ in f["pots"])) / len(fs)),
            "seq_top3": [{"seq": list(s), "n": c} for s, c in
                         Counter(f["seq"] for f in fs if f["seq"]).most_common(3)],
        }

        pot_kind = Counter(kind for f in fs for _, kind in f["pots"])
        d["pot_kind"] = dict(pot_kind)
        p1 = sorted(f["pots"][0][0] for f in fs if f["pots"])
        d["pot_first_med_s"] = round(pct(p1, .5), 1) if p1 else None
        d["fights_with_2pots_pct"] = round(100 * sum(1 for f in fs if len(f["pots"]) >= 2) / len(fs))

        hold_hist = Counter()
        n_holds = 0
        for f in fs:
            for i in range(1, len(f["dg"])):
                if f["dg"][i] - f["dg"][i-1] > eff_cd + 15:
                    hold_hist[int(f["dg"][i] // 30) * 30] += 1
                    n_holds += 1
        d["hold_dg_arrival_top"] = [{"t": mmss(t), "n": c} for t, c in hold_hist.most_common(5)]
        d["n_holds"] = n_holds

        # ── 암흑의 수확(1분급) 간격/분당 — 메이저 쿨기 2 ──
        d["dark_harvest"] = summarize_cd(fs, "dh", eff_cd_dh)

        # ── 유령 출몰(단축쿨 15초, 처치시 초기화) 참고 지표 ──
        haunt_pm = sorted(len(f["haunt"]) / (f["dur"] / 60) for f in fs if f["dur"] > 0 and f["haunt"])
        d["haunt_per_min_med"] = round(pct(haunt_pm, .5), 2) if haunt_pm else None

        # ── 도트 갱신 창: 조기클리핑 vs 정시갱신 vs 만료후리필 ──
        d["dot_refresh"] = {
            "agony_18s": dot_refresh_stats([f["agony"] for f in fs], 18.0),
            "unstable_affliction_8s": dot_refresh_stats([f["ua"] for f in fs], 8.0),
        }

        # ── 영혼 조각 소비(불안정한 고통) 타이밍: 암흑시선 창 안 vs 밖 비율 ──
        ua_in_dg = 0; ua_total = 0; ua_pm = []
        for f in fs:
            uac = f["ua"]
            ua_total += len(uac)
            ua_in_dg += sum(1 for t in uac if any(a <= t <= b for a, b in f["dg_win"]))
            if f["dur"] > 0 and uac:
                ua_pm.append(len(uac) / (f["dur"] / 60))
        dg_win_total = sum(b - a for f in fs for a, b in f["dg_win"])
        dur_total = sum(f["dur"] for f in fs)
        dg_win_share = dg_win_total / dur_total if dur_total else 0
        d["ua_shard_timing"] = {
            "ua_total": ua_total,
            "ua_per_min_med": round(pct(ua_pm, .5), 2) if ua_pm else None,
            "ua_in_darkglare_window_pct": round(100 * ua_in_dg / ua_total) if ua_total else None,
            "darkglare_window_time_share_pct": round(100 * dg_win_share),
            "note": "창내비율 > 창시간비율이면 암흑시선 창에 맞춰 조각 소비를 몰아준다는 뜻(홀드 규율 있음)",
        }

        out["per_boss"][ko] = d

        a = d["all"]
        print(f"\n===== {ko} (n={a['n']}, 킬 {mmss(d['kill_med_s'])})", flush=True)
        t20, rest = d["rank_1_20"], d["rank_21_100"]
        fb20 = t20["first_dg_med_s"] if t20 else None
        fbre = rest["first_dg_med_s"] if rest else None
        print(f"  첫 암흑시선 med {d['opener']['first_dg_med_s']}s (10s내 {d['opener']['first_dg_le10s_pct']}%) [1-20위 {fb20} vs 21-100위 {fbre}] · 암흑시선/분 {a['dg_per_min_med']}")
        print(f"  간격: {a['dg_gap']}")
        if t20 and rest and t20["dg_gap"] and rest["dg_gap"]:
            print(f"    1-20위 med {t20['dg_gap']['med']}s 즉시 {t20['dg_gap']['즉시_pct']}% 대홀드 {t20['dg_gap']['대홀드_pct']}% | 21-100위 med {rest['dg_gap']['med']}s 즉시 {rest['dg_gap']['즉시_pct']}% 대홀드 {rest['dg_gap']['대홀드_pct']}%")
        print(f"  홀드 도착 핫스팟: {d['hold_dg_arrival_top']} (총 {d['n_holds']}회)")
        print(f"  물약 {a['pot_uses']}회: 첫 물약 {d['pot_first_med_s']}s (2개 사용 {d['fights_with_2pots_pct']}%) | 종류 {d['pot_kind']}")
        print(f"    정렬: 물약→3s내 암흑시선 {a['pot_then_dg_within3s_pct']}%, 물약→다음 암흑시선 med {a['pot_to_next_dg_med_s']}s, 겹침15s+ {a['pot_overlap_ge15s_pct']}%, 암흑시선중 사용 {a['pot_cast_in_dg_pct']}%")
        dh = d["dark_harvest"]
        if dh:
            print(f"  암흑의 수확(1분급): 판당 {dh['per_min_med']}/분, 간격 {dh['gap']}")
        print(f"  유령 출몰(15초쿨) 판당 {d['haunt_per_min_med']}/분")
        print(f"  도트갱신 — 고통(18s): {d['dot_refresh']['agony_18s']}")
        print(f"  도트갱신 — 불안정한고통(8s): {d['dot_refresh']['unstable_affliction_8s']}")
        u = d["ua_shard_timing"]
        print(f"  조각소비(UA) 창내비율 {u['ua_in_darkglare_window_pct']}% vs 창시간비율 {u['darkglare_window_time_share_pct']}% (판당 {u['ua_per_min_med']}/분, 총 {u['ua_total']}회)")
        for s in d["opener"]["seq_top3"]:
            print(f"  오프너: {' > '.join(s['seq'])}  ({s['n']}명)")

    json.dump(out, open(DATA / "aff_cd_usage.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n저장: data/aff_cd_usage.json", flush=True)

    for b in ("rank_1_20", "rank_21_100"):
        s = out["overall"][b]
        if not s: continue
        print(f"\n[{b}] n={s['n']} 첫암흑시선 {s['first_dg_med_s']}s 암흑시선/분 {s['dg_per_min_med']} "
              f"간격med {s['dg_gap']['med']}s 즉시 {s['dg_gap']['즉시_pct']}% 대홀드 {s['dg_gap']['대홀드_pct']}% "
              f"물약겹침 {s['pot_dg_overlap_med_s']}s", flush=True)


if __name__ == "__main__":
    main()
