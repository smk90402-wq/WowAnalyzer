"""냉기 법사 프록 규율 실측 — 두뇌 빙결(190446)·서리의 손가락(44544)
apply→remove 보유시간 분포, 보스별 + 등수밴드(1-20 vs 21-100) 비교.

파싱 패턴은 analyze_bm_addwave.py / analyze_caster_cycle.py 를 따름
(events 캐시 1.4GB → raw_decode 증분 스캔, 스크래치패드에 추출 캐시).

출력: data/frost_proc_timing.json
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

BF = 190446    # 두뇌 빙결 (버프)
FOF = 44544    # 서리의 손가락 (버프, 최대 2중첩)
FLURRY = 44614 # 얼음보라 (BF 소모)
ICELANCE = 30455  # 얼음 창 (FoF 소모)
EXPIRY_S = 14.7   # 두 버프 모두 15초 지속 → 이 이상 들고 있다 사라지면 '자연만료'로 분류


def load_wanted():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    frost = [r for r in rows if r["class"] == "Mage" and r["spec"] == "Frost"]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    wanted = {}
    for r in frost:
        rid, fid, ch = r["report_id"], int(r["fight_id"]), r["character"]
        p = pf.get(f"{rid}:{fid}:{ch}")
        if not isinstance(p, dict): continue
        sid = p.get("sourceID")
        m = meta.get(rid)
        if sid is None or not m: continue
        f = next((x for x in (m.get("fights") or []) if x.get("id") == fid), None)
        if not f: continue
        wanted[f"{rid}:{fid}:{sid}"] = {
            "boss": r["encounter_name"], "rank": int(r["rank"]), "char": ch,
            "t0": f["startTime"], "t1": f["endTime"],
        }
    return wanted


def stream_filter(wanted):
    cache = SCRATCH / "frost_proc_events.json"
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
        if seen % 1000 == 0: print(f"  스캔 {seen}, 적중 {len(out)}", flush=True)
        if key in wanted:
            # 필요한 이벤트만 남겨 캐시 슬림화 (BF/FoF 버프 + 얼음보라/얼음창 캐스트)
            buffs = [b for b in (val.get("buffs") or []) if len(b) >= 3 and b[1] in (BF, FOF)]
            casts = [c for c in (val.get("casts") or []) if len(c) >= 3 and c[2] == "cast" and c[1] in (FLURRY, ICELANCE)]
            out[key] = {"buffs": buffs, "casts": casts}
    json.dump(out, open(cache, "w", encoding="utf-8"))
    print(f"추출 {len(out)}/{len(wanted)}", flush=True)
    return out


def analyze_fight(e, t0, t1):
    """한 판의 BF/FoF 프록 타임라인 → 지표 dict."""
    buffs = sorted((b for b in e["buffs"]), key=lambda b: b[0])
    res = {
        "bf_holds": [],      # 프록 획득→소모까지 초
        "bf_gains": 0, "bf_overwrites": 0, "bf_expiries": 0,
        "fof_spends": [],    # 충전 획득→소모까지 초
        "fof_gains": 0, "fof_munched": 0, "fof_expired": 0,
        "fof_2stack_s": 0.0,
        "dur_s": (t1 - t0) / 1000,
    }
    # ── 두뇌 빙결 ──
    active = None   # 마지막 획득 ts
    for b in buffs:
        if b[1] != BF: continue
        ts, typ = b[0], b[2]
        if typ == "applybuff":
            active = ts; res["bf_gains"] += 1
        elif typ == "refreshbuff":
            if active is not None:
                res["bf_overwrites"] += 1   # 들고 있는데 새 프록 → 기존 프록 낭비
            res["bf_gains"] += 1
            active = ts
        elif typ == "removebuff":
            if active is not None:
                hold = (ts - active) / 1000
                if hold >= EXPIRY_S:
                    res["bf_expiries"] += 1
                else:
                    res["bf_holds"].append(hold)
                active = None
    # ── 서리의 손가락 (스택 상태기계) ──
    stack = 0
    gain_times = []       # 충전별 획득 ts (FIFO)
    enter2 = None
    last_gain = None
    for b in buffs:
        if b[1] != FOF: continue
        ts, typ = b[0], b[2]
        if typ == "applybuff":
            stack = 1; gain_times = [ts]; last_gain = ts; res["fof_gains"] += 1
        elif typ == "applybuffstack":
            new = b[4] if len(b) >= 5 else stack + 1
            if new >= 2 and stack < 2:
                enter2 = ts
            stack = new; gain_times.append(ts); last_gain = ts; res["fof_gains"] += 1
        elif typ == "refreshbuff":
            res["fof_gains"] += 1
            if stack >= 2:
                res["fof_munched"] += 1   # 2중첩에서 새 프록 → 통째로 낭비
            last_gain = ts
        elif typ == "removebuffstack":
            new = b[4] if len(b) >= 5 else max(0, stack - 1)
            if stack >= 2 and new < 2 and enter2 is not None:
                res["fof_2stack_s"] += (ts - enter2) / 1000; enter2 = None
            if gain_times:
                res["fof_spends"].append((ts - gain_times.pop(0)) / 1000)
            stack = new
        elif typ == "removebuff":
            if stack >= 2 and enter2 is not None:
                res["fof_2stack_s"] += (ts - enter2) / 1000; enter2 = None
            if stack >= 1:
                if last_gain is not None and (ts - last_gain) / 1000 >= EXPIRY_S:
                    res["fof_expired"] += stack   # 남은 충전 전부 자연만료
                elif gain_times:
                    res["fof_spends"].append((ts - gain_times.pop(0)) / 1000)
            stack = 0; gain_times = []
    if enter2 is not None:  # 전투 종료까지 2중첩 유지
        res["fof_2stack_s"] += (t1 - enter2) / 1000
    return res


def pct(sorted_vals, q):
    if not sorted_vals: return None
    idx = min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1))))
    return round(sorted_vals[idx], 2)


def summarize(fights):
    """fights: analyze_fight 결과 리스트 → 집계 dict."""
    bf_all = sorted(h for f in fights for h in f["bf_holds"])
    fof_all = sorted(h for f in fights for h in f["fof_spends"])
    bf_gains = sum(f["bf_gains"] for f in fights)
    bf_waste = sum(f["bf_overwrites"] + f["bf_expiries"] for f in fights)
    fof_gains = sum(f["fof_gains"] for f in fights)
    fof_waste = sum(f["fof_munched"] + f["fof_expired"] for f in fights)
    tot_min = sum(f["dur_s"] for f in fights) / 60
    return {
        "n_fights": len(fights),
        "bf": {
            "n_procs_used": len(bf_all),
            "hold_s_median": pct(bf_all, 0.5), "hold_s_p75": pct(bf_all, 0.75),
            "hold_s_p90": pct(bf_all, 0.90),
            "used_within_3s_pct": round(100 * sum(1 for h in bf_all if h <= 3) / len(bf_all), 1) if bf_all else None,
            "used_within_5s_pct": round(100 * sum(1 for h in bf_all if h <= 5) / len(bf_all), 1) if bf_all else None,
            "waste_pct": round(100 * bf_waste / bf_gains, 1) if bf_gains else None,
            "overwrites": sum(f["bf_overwrites"] for f in fights),
            "expiries": sum(f["bf_expiries"] for f in fights),
            "gains": bf_gains,
        },
        "fof": {
            "n_charges_used": len(fof_all),
            "spend_s_median": pct(fof_all, 0.5), "spend_s_p75": pct(fof_all, 0.75),
            "spend_s_p90": pct(fof_all, 0.90),
            "used_within_3s_pct": round(100 * sum(1 for h in fof_all if h <= 3) / len(fof_all), 1) if fof_all else None,
            "used_within_5s_pct": round(100 * sum(1 for h in fof_all if h <= 5) / len(fof_all), 1) if fof_all else None,
            "waste_pct": round(100 * fof_waste / fof_gains, 1) if fof_gains else None,
            "munched_at_cap": sum(f["fof_munched"] for f in fights),
            "expired": sum(f["fof_expired"] for f in fights),
            "gains": fof_gains,
            "twostack_s_per_min": round(sum(f["fof_2stack_s"] for f in fights) / tot_min, 2) if tot_min else None,
        },
        "procs_per_min": {
            "bf": round(bf_gains / tot_min, 2) if tot_min else None,
            "fof": round(fof_gains / tot_min, 2) if tot_min else None,
        },
    }


def main():
    wanted = load_wanted()
    print(f"냉법 player-fights wanted: {len(wanted)}", flush=True)
    ev = stream_filter(wanted)
    print(f"events 적중: {len(ev)}/{len(wanted)}", flush=True)

    per = []   # (info, metrics)
    for k, info in wanted.items():
        e = ev.get(k)
        if not e or not e.get("buffs"):
            continue
        per.append((info, analyze_fight(e, info["t0"], info["t1"])))
    print(f"분석 대상 킬: {len(per)}", flush=True)

    def band(r): return "rank_1_20" if r <= 20 else "rank_21_100"

    out = {"meta": {"n_kills": len(per),
                    "bands": {"rank_1_20": sum(1 for i, _ in per if i["rank"] <= 20),
                              "rank_21_100": sum(1 for i, _ in per if i["rank"] > 20)},
                    "spells": {"brain_freeze": BF, "fingers_of_frost": FOF},
                    "note": "hold/spend = 프록 획득→소모(초). waste = 덮어쓰기+자연만료 / 총 획득."},
           "overall": {}, "per_boss": {}}

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

    json.dump(out, open(DATA / "frost_proc_timing.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("저장: data/frost_proc_timing.json", flush=True)

    # 콘솔 요약
    for b in ("rank_1_20", "rank_21_100"):
        s = out["overall"][b]
        print(f"\n[{b}] n={s['n_fights']}")
        print(f"  BF  중앙 {s['bf']['hold_s_median']}s p90 {s['bf']['hold_s_p90']}s "
              f"3s내 {s['bf']['used_within_3s_pct']}% 낭비 {s['bf']['waste_pct']}% "
              f"(덮어씀 {s['bf']['overwrites']}/만료 {s['bf']['expiries']}/획득 {s['bf']['gains']})")
        print(f"  FoF 중앙 {s['fof']['spend_s_median']}s p90 {s['fof']['spend_s_p90']}s "
              f"3s내 {s['fof']['used_within_3s_pct']}% 낭비 {s['fof']['waste_pct']}% "
              f"2중첩 {s['fof']['twostack_s_per_min']}s/분")


if __name__ == "__main__":
    main()
