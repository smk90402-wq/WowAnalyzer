"""무기 전사(Arms) 쿨기 사용 패턴 채굴 — 보스별 첫 사용·재사용 간격·홀드·쿨기 정렬.

파싱 패턴은 tmp_mine_mm_cd.py / tmp_mine_fury_cd.py 를 따름
(v2_cache_events.json 1.4GB → raw_decode 증분 스캔, 스크래치패드에 추출 캐시).

사용: python tmp_mine_arms_cd.py explore   → 스펠 ID 관측 (실제 ID 확정용)
      python tmp_mine_arms_cd.py           → 본 분석, data/arms_cd_usage.json 출력
"""
from __future__ import annotations
import json, sys, csv
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(r"C:\Users\MKSEORTV\Desktop\WowAnalyzer\data")
SCRATCH = Path(r"C:\Users\MKSEORTV\AppData\Local\Temp\claude\C--Users-MKSEORTV-Desktop-WowAnalyzer\30b0abb8-5226-4b13-9c1c-14e4a1562211\scratchpad")
SCRATCH.mkdir(parents=True, exist_ok=True)

SPEC_KEY = "Warrior/Arms"
CSV_CLASS, CSV_SPEC = "Warrior", "Arms"
CACHE_NAME = "arms_cd_events.json"
OUT_NAME = "arms_cd_usage.json"

# ── 쿨기 후보 (트리 덤프 warr_talent_names.txt 기반, explore 로 확정) ──
# 107574 투신          (spec row 11)
# 167105 거인의 강타   (spec row 6)
# 227847 칼날폭풍      (spec row 9, 쇠날발톱과 선택 노드)
# 228920 쇠날발톱(파괴전차 현행 ID, 트리 덤프 기준)
# 152277 파괴전차 구 ID (검증용 — 트리 덤프에 없음)
# 64382  분쇄의 투척   (class row 7)
# 376079 용사의 창     (class row 11)
# 436358 쇄파 (거신 hero, Demolish 계열 후보)
CANDIDATES = {
    107574: "투신",
    167105: "거인의 강타",
    227847: "칼날폭풍",
    228920: "쇠날발톱",
    152277: "파괴전차(구)",
    64382: "분쇄의 투척",
    376079: "용사의 창",
    436358: "쇄파",
}
# 버프 창 폴백 길이(버프 이벤트 없을 때 캐스트+N초): 투신 20s, 거강 디버프 10s
WIN_FALLBACK = {107574: 20.0, 167105: 10.0}

BOSS_KO = {3176: "아베르지안", 3177: "보라시우스", 3178: "바엘고어&에조라크",
           3179: "살라다르", 3180: "선봉대", 3181: "우주의 왕관",
           3182: "벨로렌", 3183: "한밤의 도래(르우라)", 3306: "카이메루스"}


def load_names():
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    return {int(k): (v.get("name_ko") or v.get("name_en") or "?") for k, v in db.items() if isinstance(v, dict)}


def load_hero_sets():
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))[SPEC_KEY]
    return {t: set(nd["id"] for nd in h["nodes"]) for t, h in tt["hero"].items()}


def load_wanted():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    sel = [r for r in rows if r["class"] == CSV_CLASS and r["spec"] == CSV_SPEC]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    hero_sets = load_hero_sets()
    wanted = {}
    for r in sel:
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
    cache = SCRATCH / CACHE_NAME
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


def explore(wanted, ev, names, heroes):
    """영웅트리별 캐스트 ID 관측 + 후보 갭 통계."""
    for hero in heroes:
        keys = [k for k, w in wanted.items() if w["hero"] == hero and k in ev]
        cast_ids = Counter(); cast_fights = Counter()
        for k in keys:
            e = ev[k]
            cseen = set()
            for c in (e.get("casts") or []):
                if len(c) >= 3 and c[2] == "cast":
                    cast_ids[c[1]] += 1; cseen.add(c[1])
            for x in cseen: cast_fights[x] += 1
        nf = len(keys)
        print(f"\n===== {hero} (n_fights={nf}) — 캐스트 ID top40 =====")
        for sid, c in cast_ids.most_common(40):
            mark = " ★후보" if sid in CANDIDATES else ""
            print(f"  {sid:>8} {names.get(sid,'?'):<22} 총{c:>6}  판당 {c/max(1,nf):>5.1f}  출현 {cast_fights[sid]}/{nf}{mark}")
    print(f"\n===== 후보 스펠 갭 통계 (전체) =====")
    for sid, name in CANDIDATES.items():
        gaps, total, nfight = [], 0, 0
        for k, e in ev.items():
            ts = sorted(c[0] for c in (e.get("casts") or [])
                        if len(c) >= 3 and c[2] == "cast" and c[1] == sid)
            if ts: nfight += 1
            total += len(ts)
            gaps += [(ts[i+1] - ts[i]) / 1000 for i in range(len(ts) - 1)]
        if gaps:
            print(f"  {sid:>8} {name:<12} 총{total} 출현판 {nfight}/{len(ev)} 갭 p5={pct(gaps,.05):.1f}s med={pct(gaps,.5):.1f}s")
        else:
            print(f"  {sid:>8} {name:<12} 총{total} 출현판 {nfight}/{len(ev)} (갭 없음)")


def parse_fight(info, e):
    t0, t1 = info["t0"], info["t1"]
    dur = (t1 - t0) / 1000
    def rel(ts): return (ts - t0) / 1000
    casts = sorted((c for c in (e.get("casts") or []) if len(c) >= 3 and c[2] == "cast"),
                   key=lambda c: c[0])
    buffs = sorted((b for b in (e.get("buffs") or []) if len(b) >= 3), key=lambda b: b[0])

    sp = {sid: [rel(c[0]) for c in casts if c[1] == sid] for sid in TRACKED}

    wins = {}
    for sid, fb in WIN_FALLBACK.items():
        w, act = [], None
        for b in buffs:
            if b[1] != sid: continue
            if b[2] == "applybuff": act = rel(b[0])
            elif b[2] == "removebuff" and act is not None:
                w.append((act, rel(b[0]))); act = None
        if act is not None: w.append((act, dur))
        if not w:
            w = [(t, t + fb) for t in sp.get(sid, [])]
        wins[sid] = w

    return {"rank": info["rank"], "dur": dur, "hero": info["hero"], "sp": sp, "wins": wins}


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


def spell_summary(fs, sid, eff_cd):
    firsts = sorted(f["sp"][sid][0] for f in fs if f["sp"][sid])
    gaps = [g for f in fs for g in
            (f["sp"][sid][i+1] - f["sp"][sid][i] for i in range(len(f["sp"][sid]) - 1))]
    uses = sorted(len(f["sp"][sid]) for f in fs)
    used = sum(1 for f in fs if f["sp"][sid])
    if not used: return None
    return {
        "출현판_pct": round(100 * used / len(fs)),
        "uses_med": pct(uses, .5),
        "first_med_s": round(pct(firsts, .5), 1) if firsts else None,
        "first_p25_p75": [round(pct(firsts, .25), 1), round(pct(firsts, .75), 1)] if firsts else None,
        "opener10s_pct": round(100 * sum(1 for x in firsts if x <= 10) / len(firsts)) if firsts else None,
        "gap": gap_stats(gaps, eff_cd),
    }


def align_summary(fs):
    """쿨기 정렬: 거인의 강타↔투신 동시(±3s), 칼날폭풍/쇠날발톱/쇄파가 거강·투신 창 안 비율."""
    out = {}
    cs_n = cs_with_ava = 0
    for f in fs:
        for t in f["sp"].get(167105, []):
            cs_n += 1
            if any(a - 3 <= t <= b for a, b in f["wins"].get(107574, [])): cs_with_ava += 1
    out["cs_uses"] = cs_n
    out["cs_in_avatar_win_pct"] = round(100 * cs_with_ava / cs_n) if cs_n else None

    for sid, label in ((BLADESTORM, "bladestorm"), (228920, "ravager"), (436358, "demolish")):
        if sid not in TRACKED: continue
        n = in_cs = in_ava = 0
        for f in fs:
            for t in f["sp"].get(sid, []):
                n += 1
                if any(a <= t <= b for a, b in f["wins"].get(167105, [])): in_cs += 1
                if any(a <= t <= b for a, b in f["wins"].get(107574, [])): in_ava += 1
        out[f"{label}_uses"] = n
        out[f"{label}_in_cs_win_pct"] = round(100 * in_cs / n) if n else None
        out[f"{label}_in_avatar_win_pct"] = round(100 * in_ava / n) if n else None
    return out


def summarize(fs, eff_cds):
    if not fs: return None
    d = {"n": len(fs)}
    for sid in TRACKED:
        d[TRACKED[sid]] = spell_summary(fs, sid, eff_cds[sid])
    d["align"] = align_summary(fs)
    return d


def analyze(wanted, ev, names, heroes):
    per = []
    for k, info in wanted.items():
        e = ev.get(k)
        if not e: continue
        f = parse_fight(info, e)
        if not any(f["sp"][sid] for sid in TRACKED): continue
        per.append((info, f))
    print(f"분석 대상 킬(추적 쿨기 1회 이상): {len(per)}", flush=True)
    hc = Counter(i["hero"] for i, _ in per)
    print(f"영웅트리: {dict(hc)}", flush=True)

    eff_cds = {}
    for sid in TRACKED:
        gaps = sorted(g for _, f in per for g in
                      (f["sp"][sid][i+1] - f["sp"][sid][i] for i in range(len(f["sp"][sid]) - 1)))
        eff_cds[sid] = round(pct(gaps, .05), 1) if gaps else None
        print(f"  {TRACKED[sid]}({sid}) 실효쿨 p5={eff_cds[sid]}s (갭 n={len(gaps)})", flush=True)
        if eff_cds[sid] is None: eff_cds[sid] = 9999.0

    def band(r): return "rank_1_20" if r <= 20 else "rank_21_100"

    out = {"meta": {
        "date": "2026-07-11", "spec": SPEC_KEY, "n_kills": len(per),
        "hero_adoption": dict(hc),
        "spells": {str(sid): TRACKED[sid] for sid in TRACKED},
        "eff_cd_s": {TRACKED[sid]: eff_cds[sid] for sid in TRACKED},
        "excluded_zero_cast": EXCLUDED,
    }, "overall": {}, "per_boss": {}}

    out["overall"]["all"] = summarize([f for _, f in per], eff_cds)
    for b in ("rank_1_20", "rank_21_100"):
        out["overall"][b] = summarize([f for i, f in per if band(i["rank"]) == b], eff_cds)
    for hero in heroes:
        sub = [f for i, f in per if i["hero"] == hero]
        if sub: out["overall"][f"hero_{hero}"] = summarize(sub, eff_cds)

    bosses = defaultdict(list)
    for i, f in per:
        bosses[(i["eid"], i["boss"])].append((i, f))

    for (eid, bname), lst in sorted(bosses.items()):
        ko = BOSS_KO.get(eid, bname)
        fs = [f for _, f in lst]
        d = {"encounter_id": eid, "name_en": bname,
             "kill_med_s": round(pct(sorted(f["dur"] for f in fs), .5)),
             "all": summarize(fs, eff_cds)}
        for hero in heroes:
            sub = [f for i, f in lst if i["hero"] == hero]
            if len(sub) >= 5:
                d[f"hero_{hero}"] = summarize(sub, eff_cds)
        out["per_boss"][ko] = d

        a = d["all"]
        print(f"\n===== {ko} (n={a['n']}, 킬 {mmss(d['kill_med_s'])})", flush=True)
        for sid in TRACKED:
            s = a[TRACKED[sid]]
            if not s:
                print(f"  {TRACKED[sid]}: 사용 없음", flush=True)
                continue
            g = s["gap"]
            gtxt = (f"갭med {g['med']}s 즉시 {g['즉시_pct']}% 소홀드 {g['소홀드_pct']}% 대홀드 {g['대홀드_pct']}%"
                    if g else "갭 없음")
            print(f"  {TRACKED[sid]}: 첫 {s['first_med_s']}s(10s내 {s['opener10s_pct']}%) "
                  f"판당 {s['uses_med']}회 {gtxt}", flush=True)
        al = a["align"]
        parts = [f"거강 in 투신창 {al['cs_in_avatar_win_pct']}%({al['cs_uses']}회)"]
        for label in ("bladestorm", "ravager", "demolish"):
            if f"{label}_uses" in al and al[f"{label}_uses"]:
                parts.append(f"{label} in 거강창 {al[f'{label}_in_cs_win_pct']}% in 투신창 {al[f'{label}_in_avatar_win_pct']}%({al[f'{label}_uses']}회)")
        print("  정렬: " + " · ".join(parts), flush=True)

    json.dump(out, open(DATA / OUT_NAME, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n저장: data/{OUT_NAME}", flush=True)

    print("\n===== 전체/영웅트리/랭크밴드 요약 =====", flush=True)
    for label in ["all"] + [f"hero_{h}" for h in heroes] + ["rank_1_20", "rank_21_100"]:
        s = out["overall"].get(label)
        if not s: continue
        parts = []
        for sid in TRACKED:
            ss = s[TRACKED[sid]]
            if ss and ss["gap"]:
                parts.append(f"{TRACKED[sid]} 첫{ss['first_med_s']}s 갭{ss['gap']['med']}s 대홀드{ss['gap']['대홀드_pct']}%")
        print(f"[{label}] n={s['n']} " + " · ".join(parts), flush=True)


# ── 확정 ID (explore 결과로 확정, 2026-07-11) ──────────────────
# 투신(107574): 296/296판, 갭 p5=50.4s → 실효 ~50s.
# 거인의 강타(167105): 296/296판, 판당 ~10.7, 갭 p5=24.4s → 실효 ~25s.
#   (플레이어 버프 이벤트 없음 — 디버프라 창은 캐스트+10s 폴백 사용)
# 칼날폭풍: 특성 ID 227847 은 캐스트 0회. 실제 캐스트/버프 ID 446035 (학살자 204판 전원).
# 쇠날발톱(228920): 거신 92판 전원, 갭 p5=90.4s → 실효 ~90s (선택 노드: 학살자=칼폭).
# 쇄파(436358, 거신 hero 액티브): 거신 92판 전원, 판당 13.5, 갭 p5=14.9s.
# 파괴전차 구 ID(152277)·용사의 창(376079): 0캐스트 → 제외. 분쇄의 투척(64382): 1캐스트 → 제외.
BLADESTORM = 446035
TRACKED = {
    107574: "투신",
    167105: "거인의 강타",
    BLADESTORM: "칼날폭풍",
    228920: "쇠날발톱",
    436358: "쇄파",
}
EXCLUDED = [
    {"id": 227847, "name": "칼날폭풍(특성ID)", "reason": "캐스트 0회 — 실제 캐스트 ID는 446035"},
    {"id": 152277, "name": "파괴전차(구 ID)", "reason": "캐스트 0회 — 현행 ID는 228920 쇠날발톱"},
    {"id": 64382, "name": "분쇄의 투척", "reason": "296킬 중 1캐스트 (사실상 미사용)"},
    {"id": 376079, "name": "용사의 창", "reason": "캐스트 0회"},
]


def main():
    names = load_names()
    hero_sets = load_hero_sets()
    heroes = list(hero_sets.keys())
    wanted = load_wanted()
    print(f"{CSV_SPEC} player-fights wanted: {len(wanted)}", flush=True)
    hc = Counter(w["hero"] for w in wanted.values())
    print(f"영웅트리(wanted): {dict(hc)}", flush=True)
    ev = stream_filter(wanted)
    print(f"events hit: {len(ev)}/{len(wanted)}", flush=True)
    if "explore" in sys.argv:
        explore(wanted, ev, names, heroes)
        return
    analyze(wanted, ev, names, heroes)


if __name__ == "__main__":
    main()
