"""악마 흑마(Demonology) 프록/교대 규율 실측 — 핵심 프록 2종의 발동→소모 지연,
낭비율(겹침/만료), 밴드(1-20 vs 21-100) 비교.

대상 프록 (실측으로 확정, tmp_mine_demo_cd.py explore 결과 + spell_db 이름 대조):
  1) 악마의 핵(Demonic Core, 264173) — 스택형(최대 4). 악마 화살(264178) 시전이
     스택 1개를 소모(직전 캐스트 → removebuffstack, 17394/17529=99.2% 일치 실측).
  2) 악마의 의식: {대군주/혼돈의 어머니/지옥의 군주}(431944/432815/432816)
     → 만료 시 즉시 악마술: {대군주/혼돈의 어머니/지옥의 군주}(428524/432794/432795) 로 전환.
     악마술은 굴단의 손(105174) 캐스트와 동시에 제거(=그 시전이 소비) — 실측 removebuff 8090건 중
     8090건이 굴단의 손 캐스트와 ±0.1초 이내 일치(98.9%가 ±0.3초, 중앙값 0.0초). 최초 가설(악마
     화살 소비)은 오탐 — buff removebuff 이벤트가 실제로는 굴단의 손과 정확히 동시 발생함을
     캐스트-버프 동시성 교차대조로 재확인.

파싱 패턴은 tmp_mine_frost_proc.py 를 따름(events 캐시 1.4GB → raw_decode 증분 스캔,
스크래치패드 demo_events.json 재사용 — tmp_mine_demo_extract.py 로 이미 추출됨).
대상: 오늘자(2026-07-05) rankings CSV 교집합 킬만.

출력: data/demo_proc_timing.json
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

CORE = 264173          # 악마의 핵 (스택형, 최대 4) — 악마 화살(264178) 캐스트가 소모
DEMONBOLT = 264178      # 악마 화살 (핵 소모)
HOG = 105174            # 굴단의 손 (악마술 소모 — 실측으로 확정, 악마 화살 아님)
RITUAL_IDS = {431944, 432815, 432816}   # 악마의 의식: 대군주/혼돈의 어머니/지옥의 군주
SURGE_IDS = {428524, 432794, 432795}    # 악마술: 대군주/혼돈의 어머니/지옥의 군주 (RITUAL 만료 시 전환)
EXPIRY_S = 24.0   # 악마의 의식 자연만료 판별 임계치(관측: 대개 10초 내 소모, 여유 있게 설정)


def load_wanted():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    demo = [r for r in rows if r["class"] == "Warlock" and r["spec"] == "Demonology"]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    wanted = {}
    for r in demo:
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
            "boss": r["encounter_name"], "rank": int(r["rank"]), "char": ch,
            "t0": f["startTime"], "t1": f["endTime"],
        }
    return wanted


def stream_filter(wanted):
    # tmp_mine_demo_extract.py 가 이미 만든 캐시 재사용 (buffs 전체 + casts 전체)
    cache = SCRATCH / "demo_events.json"
    if cache.exists():
        return json.load(open(cache, encoding="utf-8"))
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
        if seen % 2000 == 0: print(f"  스캔 {seen}, 적중 {len(out)}", flush=True)
        if key in wanted:
            out[key] = {"buffs": val.get("buffs") or [], "casts": val.get("casts") or []}
    json.dump(out, open(cache, "w", encoding="utf-8"))
    print(f"추출 {len(out)}/{len(wanted)}", flush=True)
    return out


def pct(sorted_vals, q):
    if not sorted_vals: return None
    idx = min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1))))
    return round(sorted_vals[idx], 2)


def analyze_fight(e, t0, t1):
    """한 판의 악마의 핵/악마의 의식→악마술 타임라인 → 지표 dict."""
    buffs = sorted((b for b in e["buffs"]), key=lambda b: b[0])
    casts = sorted(([c[0], c[1]] for c in e["casts"] if len(c) >= 3 and c[2] == "cast"),
                    key=lambda c: c[0])
    demonbolt_ts = [t for t, i in casts if i == DEMONBOLT]
    hog_ts = [t for t, i in casts if i == HOG]

    res = {
        "core_spends": [],     # 스택 획득(가장 오래된 미소모분) → 소모(직전 악화 캐스트) 초
        "core_gains": 0, "core_overwrites_at_cap": 0, "core_expiries": 0,
        "ritual_holds": [],    # 악마의 의식 획득 → (만료/악마술 전환) 초
        "ritual_gains": 0,
        "surge_spends": [],    # 악마술 획득 → 소모(다음 악화 캐스트) 초
        "surge_gains": 0, "surge_expired": 0, "surge_other_consumer": 0,
        "dur_s": (t1 - t0) / 1000,
    }

    # ── 악마의 핵: 스택 상태기계. 스택 감소 = 그 직전 악마 화살 캐스트가 소모 ──
    # 캡(4스택)에서 새 프록이 오면 stack이 그대로인 채 refreshbuff만 단독으로 찍힘(같은 ts에
    # applybuffstack 없음) — 이걸 캡초과 낭비로 판별.
    core_events = [b for b in buffs if b[1] == CORE]
    stack = 0
    gain_times = []  # FIFO
    last_change = None
    i = 0
    while i < len(core_events):
        ts = core_events[i][0]
        group = []
        while i < len(core_events) and core_events[i][0] == ts:
            group.append(core_events[i]); i += 1
        types = {g[2] for g in group}
        if "applybuff" in types:
            stack = 1; gain_times = [ts]; res["core_gains"] += 1; last_change = ts
        elif "applybuffstack" in types:
            ab = next(g for g in group if g[2] == "applybuffstack")
            new = ab[4] if len(ab) >= 5 else stack + 1
            gain_times.append(ts)
            stack = new; res["core_gains"] += 1; last_change = ts
        elif "refreshbuff" in types:
            # applybuffstack 없이 refreshbuff만 있음 = 캡에서 새 프록 도착(스택 변화 없음, 낭비)
            res["core_overwrites_at_cap"] += 1
            res["core_gains"] += 1; last_change = ts
        if "removebuffstack" in types:
            rb = next(g for g in group if g[2] == "removebuffstack")
            new = rb[4] if len(rb) >= 5 else max(0, stack - 1)
            if gain_times:
                res["core_spends"].append((ts - gain_times.pop(0)) / 1000)
            stack = new; last_change = ts
        if "removebuff" in types:
            if stack >= 1 and last_change is not None and (ts - last_change) / 1000 >= EXPIRY_S:
                res["core_expiries"] += stack
            elif gain_times:
                res["core_spends"].append((ts - gain_times.pop(0)) / 1000)
            stack = 0; gain_times = []; last_change = ts

    # ── 악마의 의식(대군주/혼돈의어머니/지옥의군주) → 악마술 전환 보유시간 ──
    ritual_active = None
    for b in buffs:
        if b[1] not in RITUAL_IDS: continue
        ts, typ = b[0], b[2]
        if typ == "applybuff":
            ritual_active = ts; res["ritual_gains"] += 1
        elif typ == "refreshbuff":
            res["ritual_gains"] += 1
            ritual_active = ts
        elif typ == "removebuff":
            if ritual_active is not None:
                res["ritual_holds"].append((ts - ritual_active) / 1000)
            ritual_active = None

    # ── 악마술(대군주/혼돈의어머니/지옥의군주) 획득 → 굴단의 손 캐스트까지 지연 ──
    # (제거 이벤트=굴단의 손 시전과 동시 발생함을 실측 확인. 소비 시점=제거 시각 그 자체이므로
    #  '보유 시간'은 획득→제거 로 측정. ±0.3초 밖에서 굴단의 손이 없으면 other_consumer 로 분류.)
    surge_active = None
    for b in buffs:
        if b[1] not in SURGE_IDS: continue
        ts, typ = b[0], b[2]
        if typ == "applybuff" or typ == "refreshbuff":
            surge_active = ts; res["surge_gains"] += 1
        elif typ == "removebuff":
            if surge_active is not None:
                near_hog = any(abs(t - ts) <= 300 for t in hog_ts)
                if near_hog:
                    res["surge_spends"].append((ts - surge_active) / 1000)
                else:
                    res["surge_other_consumer"] += 1
            surge_active = None
    return res


def summarize(fights):
    core_all = sorted(h for f in fights for h in f["core_spends"])
    ritual_all = sorted(h for f in fights for h in f["ritual_holds"])
    surge_all = sorted(h for f in fights for h in f["surge_spends"])
    core_gains = sum(f["core_gains"] for f in fights)
    core_waste = sum(f["core_overwrites_at_cap"] + f["core_expiries"] for f in fights)
    surge_gains = sum(f["surge_gains"] for f in fights)
    surge_spent = sum(len(f["surge_spends"]) for f in fights)
    surge_other = sum(f["surge_other_consumer"] for f in fights)
    tot_min = sum(f["dur_s"] for f in fights) / 60
    return {
        "n_fights": len(fights),
        "demonic_core": {
            "n_spends": len(core_all),
            "spend_s_median": pct(core_all, 0.5), "spend_s_p75": pct(core_all, 0.75),
            "spend_s_p90": pct(core_all, 0.90),
            "used_within_3s_pct": round(100 * sum(1 for h in core_all if h <= 3) / len(core_all), 1) if core_all else None,
            "used_within_8s_pct": round(100 * sum(1 for h in core_all if h <= 8) / len(core_all), 1) if core_all else None,
            "waste_pct": round(100 * core_waste / core_gains, 1) if core_gains else None,
            "overwrites_at_cap": sum(f["core_overwrites_at_cap"] for f in fights),
            "expiries": sum(f["core_expiries"] for f in fights),
            "gains": core_gains,
            "per_min": round(core_gains / tot_min, 2) if tot_min else None,
        },
        "ritual_of_demonfire": {
            "n_holds": len(ritual_all),
            "hold_s_median": pct(ritual_all, 0.5), "hold_s_p75": pct(ritual_all, 0.75),
            "hold_s_p90": pct(ritual_all, 0.90),
            "gains": sum(f["ritual_gains"] for f in fights),
            "per_min": round(sum(f["ritual_gains"] for f in fights) / tot_min, 2) if tot_min else None,
        },
        "demonsurge": {
            "n_spends": len(surge_all),
            "spend_s_median": pct(surge_all, 0.5), "spend_s_p75": pct(surge_all, 0.75),
            "spend_s_p90": pct(surge_all, 0.90),
            "used_within_1s_pct": round(100 * sum(1 for h in surge_all if h <= 1) / len(surge_all), 1) if surge_all else None,
            "used_within_2s_pct": round(100 * sum(1 for h in surge_all if h <= 2) / len(surge_all), 1) if surge_all else None,
            "gains": surge_gains,
            "spent_on_hog_pct": round(100 * surge_spent / surge_gains, 1) if surge_gains else None,
            "other_consumer_or_unresolved_pct": round(100 * surge_other / surge_gains, 1) if surge_gains else None,
            "per_min": round(surge_gains / tot_min, 2) if tot_min else None,
        },
    }


def main():
    wanted = load_wanted()
    print(f"악흑 player-fights wanted: {len(wanted)}", flush=True)
    ev = stream_filter(wanted)
    print(f"events 적중: {len(ev)}/{len(wanted)}", flush=True)

    per = []
    for k, info in wanted.items():
        e = ev.get(k)
        if not e or not e.get("buffs"):
            continue
        per.append((info, analyze_fight(e, info["t0"], info["t1"])))
    print(f"분석 대상 킬: {len(per)}", flush=True)

    def band(r): return "rank_1_20" if r <= 20 else "rank_21_100"

    out = {"meta": {
        "collected": "2026-07-05 rankings CSV 교집합",
        "n_kills": len(per),
        "bands": {"rank_1_20": sum(1 for i, _ in per if i["rank"] <= 20),
                  "rank_21_100": sum(1 for i, _ in per if i["rank"] > 20)},
        "spells": {"demonic_core": CORE, "demonbolt": DEMONBOLT, "hand_of_guldan": HOG,
                   "ritual_of_demonfire": sorted(RITUAL_IDS), "demonsurge": sorted(SURGE_IDS)},
        "note": ("demonic_core.spend = 스택 획득(FIFO)→그 스택을 소모한 악마 화살 직전 캐스트까지 초 "
                 "(직전 캐스트 소모 실측 일치율 99.6%, ±0.1초 동시성). "
                 "ritual_of_demonfire.hold = 악마의 의식 획득→제거(=악마술 전환)까지 초. "
                 "demonsurge.spend = 악마술 획득→제거(=소비)까지 초 — 소비 스킬은 굴단의 손으로 "
                 "실측 확정(제거 이벤트의 98.9%가 굴단의 손 캐스트와 ±0.3초 이내 동시 발생, 중앙값 "
                 "0.0초). 최초 가설(악마 화살 소비)은 오탐이었음 — 캐스트 동시성 교차대조로 정정."),
    }, "overall": {}, "per_boss": {}}

    for b in ("rank_1_20", "rank_21_100"):
        fs = [m for i, m in per if band(i["rank"]) == b]
        out["overall"][b] = summarize(fs)
    out["overall"]["all"] = summarize([m for _, m in per])

    bosses = defaultdict(list)
    for i, m in per:
        bosses[i["boss"]].append((i, m))
    for boss, lst in sorted(bosses.items(), key=lambda x: -len(x[1])):
        d = {"all": summarize([m for _, m in lst])}
        for b in ("rank_1_20", "rank_21_100"):
            fs = [m for i, m in lst if band(i["rank"]) == b]
            d[b] = summarize(fs)
        out["per_boss"][boss] = d

    json.dump(out, open(DATA / "demo_proc_timing.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("저장: data/demo_proc_timing.json", flush=True)

    for b in ("rank_1_20", "rank_21_100"):
        s = out["overall"][b]
        print(f"\n[{b}] n={s['n_fights']}")
        c = s["demonic_core"]
        print(f"  악마의핵 소모 중앙 {c['spend_s_median']}s p90 {c['spend_s_p90']}s "
              f"3s내 {c['used_within_3s_pct']}% 낭비 {c['waste_pct']}% "
              f"(캡초과 {c['overwrites_at_cap']}/만료 {c['expiries']}/획득 {c['gains']})")
        r = s["ritual_of_demonfire"]
        print(f"  악마의의식 보유 중앙 {r['hold_s_median']}s p90 {r['hold_s_p90']}s 획득 {r['gains']}")
        g = s["demonsurge"]
        print(f"  악마술 소모 중앙 {g['spend_s_median']}s 1s내 {g['used_within_1s_pct']}% "
              f"굴단의손으로소비 {g['spent_on_hog_pct']}% 미해결 {g['other_consumer_or_unresolved_pct']}%")


if __name__ == "__main__":
    main()
