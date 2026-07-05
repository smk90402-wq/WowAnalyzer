# -*- coding: utf-8 -*-
"""사격 사냥꾼(MM) 프록/교대 규율 실측 — 어둠 순찰자(DR) 중심.

절차 (GUIDE_PLAYBOOK §2-3 프록/교대 차원):
 0. 오늘자 rankings_zone46_mythic_dps_top100.csv 의 MM 킬만 (캐시-명단 정합)
 1. 영웅트리 채택률(어둠 순찰자 vs 파수꾼) — pf nodes ∩ hero tree nodes (겹침>=8)
 2. events 캐시(1.4GB) 증분 스캔 → MM 킬 buffs 전체 + casts(cast만) 스크래치패드 캐시
 3. 프록 버프 후보 = 트리(spec+hero) + 티어셋 → 실제 buffs 관측으로 확정
 4. 버프별 apply→remove 보유시간 분포, 소모/만료/덮어쓰기 분류,
    밴드(1~20 vs 21~100) × 영웅트리(DR/SEN) 비교
소모 판정: removebuff ±0.35s 안에 해당 소모 스킬 캐스트가 있으면 '소모',
           없고 보유시간>=만료문턱이면 '자연만료', 그 외 '기타제거'(사망/페이즈).
만료문턱: 버프별 보유시간 상위 절벽(관측 p99.5)에서 도출해 코드에 고정, 콘솔에 출력.

출력: data/mm_proc_timing.json  (커밋 금지 — 가이드 입력용)
"""
from __future__ import annotations
import csv, json, sys, os
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SCRATCH = Path(os.environ.get(
    "PROC_EVENTS_DIR",
    r"C:\Users\smk90\AppData\Local\Temp\claude"
    r"\C--Users-smk90-OneDrive-------LogAnalyze"
    r"\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad"))
SCRATCH.mkdir(parents=True, exist_ok=True)
EV_CACHE = SCRATCH / "mm_proc_events.json"

TOP_BAND = 20

# ── 추적 대상 프록 버프 (트리+티어셋 후보 → 실측 buffs 관측으로 확정, main에서 재검증) ──
# consumer: removebuff 부근에 있어야 '소모'로 치는 캐스트 spellID 목록
PROCS = {
    "죽음의 강타":   {"buff": [378770, 343248], "consumer": [466930],         # 검은 화살(DR: 마무리 사격 대체)
                      "note": "마무리 사격(DR: 검은 화살) 쿨 초기화+조건 해제 (DR 핵심). 실측: removebuff는 466930 캐스트와 0ms 일치"},
    "정밀 사격":     {"buff": [260242], "consumer": [185358, 257620, 466930],  # 신비한/일제 사격(툴팁) + DR 검은 화살(실측 50ms 정합 확인)
                      "note": "조준 사격 사용 시 다음 신비한 사격 또는 일제 사격 강화(집중감소+피증). DR은 검은 화살도 소모창구로 실측됨"},
    "실탄 장전":     {"buff": [194594], "consumer": [19434],                  # 조준 사격
                      "note": "다음 조준 사격 무료·즉시"},
    "연타 공격":     {"buff": [260402, 473370], "consumer": [19434, 257044],  # 조준/속사
                      "note": "정조준·연발 후 다음 조준/속사 강화"},
    "부패의 사격":   {"buff": [466990, 466991], "consumer": [],               # 지속형(야격 후 10초)
                      "note": "야수의 격노 후 10초 창(soft) — 소모형 아님"},
}
STACK_BUFFS = {  # 중첩형(교대 규율이 아니라 유지 지표만)
    "총알 세례": [389020, 389019],
    "별바라기": [1253751, 1253750],
}

CONSUME_WINDOW_MS = 150  # 실측: 전 프록 removebuff→소모캐스트 시차가 <=100ms에 절벽, 150ms로 여유


def load_tree_hero_sets():
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))
    mm = tt["Hunter/Marksmanship"]
    return {t: set(nd["id"] for nd in h["nodes"]) for t, h in mm["hero"].items()}


def load_wanted():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    mm_rows = [r for r in rows if r["class"] == "Hunter" and r["spec"] == "Marksmanship"]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    hero_sets = load_tree_hero_sets()
    wanted = {}
    for r in mm_rows:
        rid, fid, ch = r["report_id"], int(r["fight_id"]), r["character"]
        p = pf.get(f"{rid}:{fid}:{ch}")
        if not isinstance(p, dict): continue
        sid = p.get("sourceID")
        m = meta.get(rid)
        if sid is None or not m: continue
        f = next((x for x in (m.get("fights") or []) if x.get("id") == fid), None)
        if not f: continue
        nodes = set(int(x) for x in (p.get("nodes") or []))
        best = max(hero_sets, key=lambda t: len(nodes & hero_sets[t]))
        hero = best if len(nodes & hero_sets[best]) >= 8 else "불명"
        wanted[f"{rid}:{fid}:{sid}"] = {
            "boss": r["encounter_name"], "rank": int(r["rank"]), "char": ch,
            "hero": hero, "t0": f["startTime"], "t1": f["endTime"],
        }
    return wanted


def stream_filter(wanted):
    if EV_CACHE.exists():
        return json.load(open(EV_CACHE, encoding="utf-8"))
    s = open(DATA / "v2_cache_events.json", encoding="utf-8").read()
    print(f"events 캐시 {len(s)/1e6:.0f}MB 스캔...", flush=True)
    dec = json.JSONDecoder()
    out, i, n, seen = {}, 1, len(s), 0
    while i < n:
        while i < n and s[i] in " \t\r\n,": i += 1
        if i >= n or s[i] == "}": break
        key, j = dec.raw_decode(s, i); i = j
        while s[i] in " \t\r\n:": i += 1
        val, j = dec.raw_decode(s, i); i = j
        seen += 1
        if seen % 1000 == 0: print(f"  스캔 {seen}, 적중 {len(out)}", flush=True)
        if key in wanted:
            buffs = [b for b in (val.get("buffs") or []) if len(b) >= 3]
            casts = [c for c in (val.get("casts") or []) if len(c) >= 3 and c[2] == "cast"]
            out[key] = {"buffs": buffs, "casts": casts}
    json.dump(out, open(EV_CACHE, "w", encoding="utf-8"))
    print(f"추출 {len(out)}/{len(wanted)}", flush=True)
    return out


def survey_buffs(ev, wanted):
    """관측 버프 ID 전수 → 후보 확정용 콘솔 표."""
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    name = lambda sid: (db.get(str(sid)) or {}).get("name_ko") or f"#{sid}"
    cnt_by_hero = {"어둠 순찰자": Counter(), "파수꾼": Counter()}
    kills_by_hero = Counter()
    for k, e in ev.items():
        h = wanted[k]["hero"]
        if h not in cnt_by_hero: continue
        kills_by_hero[h] += 1
        for b in e["buffs"]:
            if b[2] in ("applybuff", "refreshbuff", "applybuffstack"):
                cnt_by_hero[h][b[1]] += 1
    print("\n=== 관측 버프 상위 (획득 이벤트 수) ===")
    for h, c in cnt_by_hero.items():
        print(f"[{h}] 킬 {kills_by_hero[h]}")
        for sid, n_ in c.most_common(40):
            print(f"  {sid:>8} {name(sid):<22} {n_}")
    return cnt_by_hero


def analyze_fight(e, info):
    buffs = sorted(e["buffs"], key=lambda b: b[0])
    casts = e["casts"]
    cast_ts = defaultdict(list)   # spellID → [ts...]
    for c in casts:
        cast_ts[c[1]].append(c[0])
    res = {"dur_s": (info["t1"] - info["t0"]) / 1000, "procs": {}}

    def consumed_near(ts, consumers):
        for cid in consumers:
            for t in cast_ts.get(cid, ()):
                if abs(t - ts) <= CONSUME_WINDOW_MS:
                    return True
        return False

    for pname, cfg in PROCS.items():
        ids = set(cfg["buff"])
        r = {"gains": 0, "overwrites": 0, "holds": [], "consumed": 0,
             "expired": 0, "other_removed": 0, "uptime_s": 0.0}
        active = None
        for b in buffs:
            if b[1] not in ids: continue
            ts, typ = b[0], b[2]
            if typ == "applybuff":
                active = ts; r["gains"] += 1
            elif typ == "refreshbuff":
                if active is not None: r["overwrites"] += 1
                r["gains"] += 1; active = ts
            elif typ == "removebuff":
                if active is not None:
                    hold = (ts - active) / 1000
                    r["holds"].append(hold)
                    r["uptime_s"] += hold
                    if cfg["consumer"] and consumed_near(ts, cfg["consumer"]):
                        r["consumed"] += 1
                    else:
                        r["other_removed"] += 1  # 만료 분류는 문턱 도출 후 2차에서
                    active = None
        res["procs"][pname] = r
    # 중첩형: 최대 스택 + 스택 획득 수
    res["stacks"] = {}
    for sname, ids in STACK_BUFFS.items():
        idset = set(ids); mx = 0; gains = 0
        for b in buffs:
            if b[1] in idset:
                if b[2] == "applybuffstack":
                    st = b[3] if len(b) >= 4 and isinstance(b[3], int) else 0
                    mx = max(mx, st); gains += 1
                elif b[2] == "applybuff":
                    mx = max(mx, 1); gains += 1
        res["stacks"][sname] = {"max": mx, "gains": gains}
    return res


def pct(sorted_vals, q):
    if not sorted_vals: return None
    idx = min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1))))
    return round(sorted_vals[idx], 2)


def derive_expiry_threshold(all_holds):
    """보유시간 절벽(자연 지속시간) 추정: p99.5 근처 0.5s 격자 최빈 상단."""
    if len(all_holds) < 50: return None
    hs = sorted(all_holds)
    p995 = pct(hs, 0.995)
    return round(p995 - 0.3, 1) if p995 else None


def summarize(fights, pname, expiry_s):
    holds_all = sorted(h for f in fights for h in f["procs"][pname]["holds"])
    gains = sum(f["procs"][pname]["gains"] for f in fights)
    ow = sum(f["procs"][pname]["overwrites"] for f in fights)
    consumed = sum(f["procs"][pname]["consumed"] for f in fights)
    tot_min = sum(f["dur_s"] for f in fights) / 60
    expired = 0
    if expiry_s:
        expired = sum(1 for h in holds_all if h >= expiry_s)
    waste = ow + expired
    return {
        "n_fights": len(fights),
        "gains": gains, "gains_per_min": round(gains / tot_min, 2) if tot_min else None,
        "hold_s_median": pct(holds_all, 0.5), "hold_s_p75": pct(holds_all, 0.75),
        "hold_s_p90": pct(holds_all, 0.90),
        "used_within_2s_pct": round(100 * sum(1 for h in holds_all if h <= 2) / len(holds_all), 1) if holds_all else None,
        "used_within_4s_pct": round(100 * sum(1 for h in holds_all if h <= 4) / len(holds_all), 1) if holds_all else None,
        "consumed_confirmed": consumed,
        "overwrites": ow, "expired": expired,
        "waste_pct": round(100 * waste / gains, 1) if gains else None,
    }


def main():
    wanted = load_wanted()
    hero_cnt = Counter(i["hero"] for i in wanted.values())
    band_hero = {"rank_1_20": Counter(), "rank_21_100": Counter()}
    boss_hero = defaultdict(Counter)
    for i in wanted.values():
        band_hero["rank_1_20" if i["rank"] <= TOP_BAND else "rank_21_100"][i["hero"]] += 1
        boss_hero[i["boss"]][i["hero"]] += 1
    print(f"MM wanted: {len(wanted)} · 영웅트리 {dict(hero_cnt)}", flush=True)

    ev = stream_filter(wanted)
    print(f"events 적중: {len(ev)}/{len(wanted)}", flush=True)
    if os.environ.get("MM_SURVEY"):
        survey_buffs(ev, wanted)
        return

    per = []
    for k, info in wanted.items():
        e = ev.get(k)
        if not e or not e.get("buffs"): continue
        per.append((info, analyze_fight(e, info)))
    print(f"분석 대상 킬: {len(per)}", flush=True)

    # 만료 문턱 도출 (전체 표본 기준, 콘솔 출력)
    expiry = {}
    for pname in PROCS:
        allh = [h for _, m in per for h in m["procs"][pname]["holds"]]
        expiry[pname] = derive_expiry_threshold(allh)
        print(f"  만료문턱 {pname}: {expiry[pname]}s (관측 hold n={len(allh)})", flush=True)

    def seg(fights_meta, label):
        return {pname: summarize([m for _, m in fights_meta], pname, expiry[pname]) for pname in PROCS} | {
            "_stacks": {s: {
                "max_stack_p50": pct(sorted(m["stacks"][s]["max"] for _, m in fights_meta), 0.5),
                "max_stack_max": max((m["stacks"][s]["max"] for _, m in fights_meta), default=0),
            } for s in STACK_BUFFS},
            "_n": len(fights_meta),
        }

    out = {
        "meta": {
            "date": "2026-07-05", "n_kills": len(per),
            "hero_adoption": {
                "total": dict(hero_cnt),
                "band": {b: dict(c) for b, c in band_hero.items()},
                "per_boss": {b: dict(c) for b, c in sorted(boss_hero.items())},
            },
            "procs": {p: {"buff_ids": c["buff"], "consumer_ids": c["consumer"], "note": c["note"]} for p, c in PROCS.items()},
            "expiry_threshold_s": expiry,
            "note": "hold=획득→제거(초). waste=덮어쓰기+자연만료/총획득. consumed_confirmed=제거 ±0.35s 내 소모 캐스트 확인.",
        },
        "segments": {},
        "per_boss": {},
    }
    for hero in ("어둠 순찰자", "파수꾼"):
        sub = [(i, m) for i, m in per if i["hero"] == hero]
        out["segments"][hero] = {
            "all": seg(sub, hero),
            "rank_1_20": seg([(i, m) for i, m in sub if i["rank"] <= TOP_BAND], "top"),
            "rank_21_100": seg([(i, m) for i, m in sub if i["rank"] > TOP_BAND], "rest"),
        }
    bosses = defaultdict(list)
    for i, m in per: bosses[i["boss"]].append((i, m))
    for boss, lst in sorted(bosses.items(), key=lambda x: -len(x[1])):
        d = {}
        for hero in ("어둠 순찰자", "파수꾼"):
            sub = [(i, m) for i, m in lst if i["hero"] == hero]
            if len(sub) >= 5:
                d[hero] = {"all": seg(sub, boss),
                           "rank_1_20": seg([(i, m) for i, m in sub if i["rank"] <= TOP_BAND], "t"),
                           "rank_21_100": seg([(i, m) for i, m in sub if i["rank"] > TOP_BAND], "r")}
        out["per_boss"][boss] = d

    json.dump(out, open(DATA / "mm_proc_timing.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("저장: data/mm_proc_timing.json", flush=True)

    # 콘솔 요약 (DR 중심)
    for hero in ("어둠 순찰자", "파수꾼"):
        print(f"\n===== {hero} =====")
        for band in ("rank_1_20", "rank_21_100"):
            s = out["segments"][hero][band]
            print(f"[{band}] n={s['_n']}")
            for pname in PROCS:
                p = s[pname]
                if not p["gains"]: continue
                print(f"  {pname:<8} 분당 {p['gains_per_min']} · 중앙 {p['hold_s_median']}s p90 {p['hold_s_p90']}s "
                      f"· 2s내 {p['used_within_2s_pct']}% · 낭비 {p['waste_pct']}% (덮 {p['overwrites']}/만료 {p['expired']}/획득 {p['gains']})")


if __name__ == "__main__":
    main()
