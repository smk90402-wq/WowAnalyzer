"""악마 흑마 쿨기 홀드 실측 — 악마 폭군 소환/흑마법서: 임프 군주/잿불날개 열파 보스별 운용 정답지.

파싱 패턴은 tmp_mine_bm_cd.py / tmp_mine_frost_cd.py 를 따름
(v2_cache_events.json 1.4GB → raw_decode 증분 스캔, 스크래치패드에 추출 캐시).
★오늘자(2026-07-05) rankings CSV에 있는 킬만 대상 (CSV report_id/fight_id로 필터)★

explore 결과로 확정한 ID:
  265187 악마 폭군 소환(Summon Demonic Tyrant) — 실효쿨 60.7s(p5), 302/302판 전원 사용. 유일한 주기 대쿨기.
  1276452 흑마법서: 임프 군주(Grimoire: Imp Lord) — 트리(10,19) 분기 노드, 실효쿨 120.9s(p5), 255/302판(84%) 채택.
          대체옵션 1276467(흑마법서: 지옥 유린자)는 explore 0회 — 죽은 선택지.
          폭군 소환보다 중앙값 3.9s "먼저" 캐스트(폭군 발동 셋업).
  1250508 잿불날개 열파(Emberwing Heatwave, 영웅특성 계열) — 실효쿨 121.5s(p5), 262/302판(87%).
          폭군 소환과 거의 동시(중앙값 +0.1s, 96%가 3s 이내) — 폭군 연동형.
  108416 어둠의 서약(Dark Pact) — 60s쿨이지만 생존기(자기 보호막). DPS 쿨기 아님 — 이 분석에서 제외.
  30146 지옥수호병 소환 — 8/302판만 사용, 채택률 3%. 임프 군주/폭군 트리 선택에 밀린 죽은 노드.
  블러드(2825/32182/80353/264667/390386/1260277) — 0/302판. 미드나잇 시즌 블러드 없음.

사용: python tmp_mine_demo_cd.py explore   → 스펠 ID 관측 (실제 ID 확정용)
      python tmp_mine_demo_cd.py           → 본 분석, data/demo_cd_usage.json 출력
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

TYRANT = 265187        # 악마 폭군 소환 (주 쿨기, 60s)
IMP_LORD = 1276452     # 흑마법서: 임프 군주 (분기 정점특성, 120s)
IMP_LORD_ALT = 1276467 # 흑마법서: 지옥 유린자 (대체 옵션, 실사용 0)
EMBERWING = 1250508    # 잿불날개 열파 (영웅특성, 120s, 폭군 연동)
DARK_PACT = 108416     # 어둠의 서약 (생존기, DPS쿨 아님 — 참고용만)
FEL_LORD = 30146       # 지옥수호병 소환 (채택률 낮음 — 참고용만)
GRIMOIRE_CANDS = {IMP_LORD, IMP_LORD_ALT, 30146, 1251778, 1276672}  # 트리 분기 후보 전부
LUST_IDS = {2825, 32182, 80353, 264667, 390386, 466904, 1260277}
POT_IDS = {1236616: "빛의잠재력", 1236998: "방종의비약", 1236994: "무모함의물약"}
TYRANT_BUFF_S = 20.0   # 폭군 활성 버프 실측(applybuff~removebuff)


def load_names():
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    return {int(k): (v.get("name_ko") or v.get("name_en") or "?") for k, v in db.items() if isinstance(v, dict)}


def load_cds():
    try:
        cd = json.load(open(DATA / "spell_cooldowns.json", encoding="utf-8"))
        return {int(k): v for k, v in cd.items()}
    except Exception:
        return {}


def load_wanted():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    dl = [r for r in rows if r["class"] == "Warlock" and r["spec"] == "Demonology"]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    wanted = {}
    for r in dl:
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
    cache = SCRATCH / "demo_cd_events.json"
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


def explore(wanted, ev, names, cds):
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
        print(f"  {sid:>8} {names.get(sid,'?'):<24} cd={cds.get(sid,'-'):>4} 총{c:>6}  판출현 {cast_fights[sid]}/{nf}")
    print("\n== 캐스트 중 쿨기(cd>=40s) 전부 ==")
    for sid, c in cast_ids.most_common():
        if cds.get(sid, 0) >= 40:
            print(f"  {sid:>8} {names.get(sid,'?'):<24} cd={cds.get(sid)} 총{c:>6}  판출현 {cast_fights[sid]}/{nf}")
    print("\n== applybuff ID top50 ==")
    for sid, c in buff_ids.most_common(50):
        print(f"  {sid:>8} {names.get(sid,'?'):<24} 총{c:>6}  판출현 {buff_fights[sid]}/{nf}")
    print("\n== 후보/블러드/물약 확인 ==")
    for sid in sorted(GRIMOIRE_CANDS | {TYRANT, EMBERWING, DARK_PACT} | LUST_IDS | set(POT_IDS)):
        print(f"  {sid:>8} {names.get(sid,'?'):<24} cast총 {cast_ids.get(sid,0):>6} (판 {cast_fights.get(sid,0)}) / buff총 {buff_ids.get(sid,0):>6} (판 {buff_fights.get(sid,0)})")


NOISE = {105174, 264178, 686, 196277, 104316, 434506, 434635, 111400, 48020, 132411,
         385899, 111771, 48018, 1234768, 1236994, 1236616, 1236998, 6789}  # 오프너 시퀀스용 노이즈(필러/유틸/소모품)

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

    tyrant = [rel(c[0]) for c in casts if c[1] == TYRANT]
    imp_lord = [rel(c[0]) for c in casts if c[1] == IMP_LORD]
    ember = [rel(c[0]) for c in casts if c[1] == EMBERWING]
    pots = [(rel(c[0]), POT_IDS[c[1]]) for c in casts if c[1] in POT_IDS]

    # 폭군 활성 실측 창 (apply→remove)
    tyrant_win, act = [], None
    for b in buffs:
        if b[1] != TYRANT: continue
        if b[2] == "applybuff": act = rel(b[0])
        elif b[2] == "removebuff" and act is not None:
            tyrant_win.append((act, rel(b[0]))); act = None
    if act is not None: tyrant_win.append((act, dur))
    if not tyrant_win:
        tyrant_win = [(t, t + TYRANT_BUFF_S) for t in tyrant]

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
        "tyrant": tyrant, "tyrant_win": tyrant_win,
        "imp_lord": imp_lord, "ember": ember, "pots": pots,
        "pot_carried": any(carried_in(s) for s in POT_IDS),
        "seq": seq_names,
    }


def overlap_s(win, lo, hi):
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


def rel_offset_stats(offsets):
    """보조 쿨기 캐스트 시각 - 가장 가까운 폭군 시각(초). 음수=폭군보다 먼저."""
    if not offsets: return None
    n = len(offsets)
    return {
        "n": n, "med": round(pct(offsets, .5), 1),
        "p25": round(pct(offsets, .25), 1), "p75": round(pct(offsets, .75), 1),
        "within3s_pct": round(100 * sum(1 for x in offsets if abs(x) <= 3) / n),
        "before_pct": round(100 * sum(1 for x in offsets if x < -3) / n),
        "after_pct": round(100 * sum(1 for x in offsets if x > 3) / n),
    }


def summarize(fs, eff_cd):
    if not fs: return None
    gaps = [g for f in fs for g in
            (f["tyrant"][i+1] - f["tyrant"][i] for i in range(len(f["tyrant"]) - 1))]
    first = sorted(f["tyrant"][0] for f in fs if f["tyrant"])
    tpm = sorted(len(f["tyrant"]) / (f["dur"] / 60) for f in fs if f["dur"] > 0)

    # 임프 군주/열파 ↔ 폭군 정렬 (가장 가까운 폭군 시각과의 차)
    imp_off, ember_off = [], []
    for f in fs:
        for t in f["imp_lord"]:
            if not f["tyrant"]: continue
            near = min(f["tyrant"], key=lambda x: abs(x - t))
            imp_off.append(t - near)
        for t in f["ember"]:
            if not f["tyrant"]: continue
            near = min(f["tyrant"], key=lambda x: abs(x - t))
            ember_off.append(t - near)

    # 물약↔폭군 정렬: 겹침 초 + 폭군 직전/직후 3s
    pot_ol, pot_n, pot_in_tyrant, pot_next3, pot_next = [], 0, 0, 0, []
    for f in fs:
        for p, _ in f["pots"]:
            pot_n += 1
            pot_ol.append(overlap_s(f["tyrant_win"], p, p + 30.0))
            if any(a <= p <= b for a, b in f["tyrant_win"]): pot_in_tyrant += 1
            nxt = [t for t in f["tyrant"] if t >= p - 1]
            if nxt:
                d = nxt[0] - p
                pot_next.append(d)
                if d <= 3: pot_next3 += 1

    return {
        "n": len(fs),
        "first_tyrant_med_s": round(pct(first, .5), 1) if first else None,
        "first_tyrant_p25_p75": [round(pct(first, .25), 1), round(pct(first, .75), 1)] if first else None,
        "tyrant_per_min_med": round(pct(tpm, .5), 2) if tpm else None,
        "tyrant_gap": gap_stats(gaps, eff_cd),
        "imp_lord_vs_tyrant": rel_offset_stats(imp_off),
        "ember_vs_tyrant": rel_offset_stats(ember_off),
        "pot_uses": pot_n,
        "pot_tyrant_overlap_med_s": round(pct(pot_ol, .5), 1) if pot_ol else None,
        "pot_cast_in_tyrant_pct": round(100 * pot_in_tyrant / pot_n) if pot_n else None,
        "pot_then_tyrant_within3s_pct": round(100 * pot_next3 / pot_n) if pot_n else None,
        "pot_to_next_tyrant_med_s": round(pct(pot_next, .5), 1) if pot_next else None,
    }


def main():
    names = load_names()
    cds = load_cds()
    wanted = load_wanted()
    print(f"악흑 player-fights wanted: {len(wanted)}", flush=True)
    ev = stream_filter(wanted)
    print(f"events hit: {len(ev)}/{len(wanted)}", flush=True)
    if "explore" in sys.argv:
        explore(wanted, ev, names, cds)
        return

    per = []
    for k, info in wanted.items():
        e = ev.get(k)
        if not e: continue
        f = parse_fight(info, e, names)
        if len(f["tyrant"]) < 2: continue
        per.append((info, f))
    print(f"분석 대상 킬: {len(per)}", flush=True)

    all_gaps = sorted(g for _, f in per for g in
                      (f["tyrant"][i+1] - f["tyrant"][i] for i in range(len(f["tyrant"]) - 1)))
    eff_cd = pct(all_gaps, .05)
    print(f"폭군 간격 p5(실효 쿨 추정) = {eff_cd:.1f}s, p1 = {pct(all_gaps, .01):.1f}s", flush=True)

    def band(r): return "rank_1_20" if r <= 20 else "rank_21_100"

    out = {"meta": {
        "date": "2026-07-05", "n_kills": len(per),
        "eff_cd_s": round(eff_cd, 1),
        "spells": {"tyrant": TYRANT, "imp_lord": IMP_LORD, "emberwing": EMBERWING,
                   "potions": {str(k): v for k, v in POT_IDS.items()}},
        "notes": [
            "악마 폭군 소환(265187, 60s쿨)이 유일한 주기 대쿨기 — 302/302판 전원 사용, 실효쿨 60.7s(p5)로 거의 즉시재사용.",
            "흑마법서: 임프 군주(1276452, 120s쿨) 채택률 84%(255/302) — 대체옵션 지옥 유린자(1276467)는 실사용 0. "
            "폭군보다 중앙값 3.9초 먼저 캐스트(폭군 발동 전 셋업 타이밍).",
            "잿불날개 열파(1250508, 영웅특성 120s쿨) 채택률 87%(262/302) — 폭군과 거의 동시(중앙값 +0.1s, 96%가 3s 이내). "
            "별도 홀드 판단 불필요, 폭군에 자동 종속.",
            "지옥수호병 소환(30146)은 8/302판(3%)만 사용 — 임프 군주/폭군 트리 선택에 밀린 죽은 노드, 가이드 제외.",
            "어둠의 서약(108416, 60s쿨)은 생존기(자기 보호막)라 DPS 쿨기 홀드 분석에서 제외.",
            "블러드/영웅심/시간왜곡 계열 버프 0/302킬 — 미드나잇 시즌에는 블러드가 없어 '블러드 정렬' 항목 성립 안 함.",
            "펫(악마) 버프는 플레이어 buffs에 없어 측정 불가 — 폭군의 '소환수 강화' 효과 자체는 캐스트/버프 타이밍으로만 간접 추적.",
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
        firsts = sorted(f["tyrant"][0] for f in fs if f["tyrant"])
        d["opener"] = {
            "first_tyrant_med_s": round(pct(firsts, .5), 1),
            "first_tyrant_le5s_pct": round(100 * sum(1 for x in firsts if x <= 5) / len(firsts)),
            "pot_prepull_or_10s_pct": round(100 * sum(
                1 for f in fs if f["pot_carried"] or any(p <= 10 for p, _ in f["pots"])) / len(fs)),
            "seq_top3": [{"seq": list(s), "n": c} for s, c in
                         Counter(f["seq"] for f in fs if f["seq"]).most_common(3)],
        }

        # 물약 시점 분포
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

        # 대홀드(간격 > 실효쿨+15s) 도착 시각 핫스팟
        hold_hist = Counter()
        n_holds = 0
        for f in fs:
            for i in range(1, len(f["tyrant"])):
                if f["tyrant"][i] - f["tyrant"][i-1] > eff_cd + 15:
                    hold_hist[int(f["tyrant"][i] // 30) * 30] += 1
                    n_holds += 1
        d["hold_tyrant_arrival_top"] = [
            {"t": mmss(t), "n": c} for t, c in hold_hist.most_common(5)]
        d["n_holds"] = n_holds
        out["per_boss"][ko] = d

        # 콘솔
        a = d["all"]
        print(f"\n===== {ko} (n={a['n']}, 킬 {mmss(d['kill_med_s'])})", flush=True)
        t20, rest = d["rank_1_20"], d["rank_21_100"]
        fb20 = t20["first_tyrant_med_s"] if t20 else None
        fbre = rest["first_tyrant_med_s"] if rest else None
        print(f"  첫 폭군 med {d['opener']['first_tyrant_med_s']}s p25-75 {a['first_tyrant_p25_p75']} (5s내 {d['opener']['first_tyrant_le5s_pct']}%) [1-20위 {fb20} vs 21-100위 {fbre}] · 폭군/분 {a['tyrant_per_min_med']}")
        print(f"  폭군 간격: {a['tyrant_gap']}")
        if t20 and rest and t20["tyrant_gap"] and rest["tyrant_gap"]:
            print(f"    1-20위 med {t20['tyrant_gap']['med']}s 즉시 {t20['tyrant_gap']['즉시_pct']}% 대홀드 {t20['tyrant_gap']['대홀드_pct']}% | 21-100위 med {rest['tyrant_gap']['med']}s 즉시 {rest['tyrant_gap']['즉시_pct']}% 대홀드 {rest['tyrant_gap']['대홀드_pct']}%")
        print(f"  홀드 도착 핫스팟: {d['hold_tyrant_arrival_top']} (총 {d['n_holds']}회)")
        if a["imp_lord_vs_tyrant"]:
            iv = a["imp_lord_vs_tyrant"]
            print(f"  임프군주↔폭군 오프셋 med {iv['med']}s (3s내 {iv['within3s_pct']}%, 먼저 {iv['before_pct']}%, 나중 {iv['after_pct']}%)")
        if a["ember_vs_tyrant"]:
            ev_ = a["ember_vs_tyrant"]
            print(f"  열파↔폭군 오프셋 med {ev_['med']}s (3s내 {ev_['within3s_pct']}%)")
        print(f"  물약 {a['pot_uses']}회: 첫 물약 {d['pot_first_med_s']}s, 둘째 {d['pot_second_med_s']}s (2개 사용 {d['fights_with_2pots_pct']}%) | 종류 {d['pot_kind']}")
        print(f"    정렬: 물약→3s내 폭군 {a['pot_then_tyrant_within3s_pct']}%, 물약→다음 폭군 med {a['pot_to_next_tyrant_med_s']}s, 폭군중 사용 {a['pot_cast_in_tyrant_pct']}%")
        for s in d["opener"]["seq_top3"]:
            print(f"  오프너: {' > '.join(s['seq'])}  ({s['n']}명)")

    json.dump(out, open(DATA / "demo_cd_usage.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n저장: data/demo_cd_usage.json", flush=True)

    for b in ("rank_1_20", "rank_21_100"):
        s = out["overall"][b]
        print(f"\n[{b}] n={s['n']} 첫폭군 {s['first_tyrant_med_s']}s 폭군/분 {s['tyrant_per_min_med']} "
              f"간격med {s['tyrant_gap']['med']}s 즉시 {s['tyrant_gap']['즉시_pct']}% 대홀드 {s['tyrant_gap']['대홀드_pct']}% "
              f"물약겹침 {s['pot_tyrant_overlap_med_s']}s", flush=True)


if __name__ == "__main__":
    main()
