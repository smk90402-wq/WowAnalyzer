"""냉기 법사 쿨기 운용 실측 — 구슬/광선 재사용 간격 + 웨이브 홀드 여부.

analyze_bm_addwave.py 패턴 그대로: rankings→player_fight→report_meta로 키 구성,
v2_cache_events.json 을 raw_decode 증분 파싱으로 냉법 키만 추출(스크래치패드 캐시).
출력: data/frost_cd_usage.json
"""
from __future__ import annotations
import json, sys, csv, os
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(__file__).parent / "data"
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")
SCRATCH.mkdir(parents=True, exist_ok=True)

ORB = 84714      # 얼어붙은 구슬 (기본 쿨 60s)
RAY = 205021     # 서리 광선 (충전식)
BLIZ_IDS = {190356, 135502, 1248829}  # 눈보라 (여러 ID 후보 — 관측치로 판단)
FLURRY = 44614   # 진눈깨비


def load_wanted():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    fr = [r for r in rows if r["class"] == "Mage" and r["spec"] == "Frost"]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    wanted = {}
    for r in fr:
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
    cache = SCRATCH / "frost_cd_events.json"
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
    json.dump(out, open(cache, "w", encoding="utf-8"))
    print(f"추출 {len(out)}/{len(wanted)}", flush=True)
    return out


def mmss(t):
    return f"{int(t)//60}:{int(t)%60:02d}"


def pct(vals, q):
    if not vals: return None
    v = sorted(vals)
    idx = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return v[idx]


def main():
    wanted = load_wanted()
    print(f"냉법 player-fights wanted: {len(wanted)}", flush=True)
    ev = stream_filter(wanted)
    print(f"events hit: {len(ev)}/{len(wanted)}", flush=True)

    # 눈보라 ID 판별
    bliz_seen = Counter()
    for e in ev.values():
        for c in (e.get("casts") or []):
            if len(c) >= 3 and c[2] == "cast" and c[1] in BLIZ_IDS:
                bliz_seen[c[1]] += 1
    print(f"눈보라 ID 관측: {dict(bliz_seen)}", flush=True)

    bybs = defaultdict(list)
    for k, info in wanted.items():
        e = ev.get(k)
        if not e: continue
        t0 = info["t0"]
        casts = [c for c in (e.get("casts") or []) if len(c) >= 3 and c[2] == "cast"]
        if len(casts) < 20: continue
        rec = {
            "rank": info["rank"], "dur": (info["t1"] - t0) / 1000,
            "orb": sorted((c[0]-t0)/1000 for c in casts if c[1] == ORB),
            "ray": sorted((c[0]-t0)/1000 for c in casts if c[1] == RAY),
            "bliz": sorted((c[0]-t0)/1000 for c in casts if c[1] in BLIZ_IDS),
            "flur": sorted((c[0]-t0)/1000 for c in casts if c[1] == FLURRY),
        }
        bybs[info["boss"]].append(rec)

    out = {"n_total": sum(len(v) for v in bybs.values()), "bosses": {}}
    for boss, lst in sorted(bybs.items(), key=lambda x: -len(x[1])):
        durs = sorted(r["dur"] for r in lst)
        med_dur = durs[len(durs)//2]

        # ---- 구슬 간격 ----
        def gaps_of(rs, field):
            g = []
            for r in rs:
                ts = r[field]
                g += [ts[i+1]-ts[i] for i in range(len(ts)-1)]
            return g

        top = [r for r in lst if r["rank"] <= 20]
        rest = [r for r in lst if r["rank"] > 20]
        orb_gaps = gaps_of(lst, "orb")
        ray_gaps = gaps_of(lst, "ray")

        def gap_stats(g):
            if not g: return None
            n = len(g)
            return {
                "n": n,
                "p25": round(pct(g, .25), 1), "med": round(pct(g, .5), 1), "p75": round(pct(g, .75), 1),
                "즉시(<=63s)": round(100*sum(1 for x in g if x <= 63)/n),
                "소홀드(63-75s)": round(100*sum(1 for x in g if 63 < x <= 75)/n),
                "대홀드(>75s)": round(100*sum(1 for x in g if x > 75)/n),
            }

        # 첫 구슬 시점
        first_orb = [r["orb"][0] for r in lst if r["orb"]]
        # 구슬 사용 효율: 실제 캐스트 수 / 이론 최대 (dur/60 + 1)
        eff = []
        for r in lst:
            if not r["orb"]: continue
            theo = r["dur"]/60 + 1
            eff.append(len(r["orb"])/theo)

        # ---- 눈보라 히스토그램 (10s bin) → 웨이브 창 ----
        bliz_hist = Counter()
        for r in lst:
            for t in r["bliz"]:
                bliz_hist[int(t//10)*10] += 1
        n_f = len(lst)
        # 웨이브 창: 판당 평균 눈보라 밀도가 높은 빈 (연속 빈 병합)
        hot = sorted(b for b, c in bliz_hist.items() if c >= n_f * 0.8 and b < med_dur)
        waves = []
        for b in hot:
            if waves and b - waves[-1][1] <= 10:
                waves[-1][1] = b + 10
            else:
                waves.append([b, b + 10])

        # ---- 웨이브 대비 구슬 홀드 흔적 ----
        # 웨이브 시작 w 근처(-5~+15s)에 구슬이 떨어진 비율 + 그 구슬의 직전 간격(홀드량)
        wave_orb_hold = []
        wave_orb_hits = 0; wave_orb_total = 0
        for r in lst:
            for i, t in enumerate(r["orb"]):
                near = any(w0 - 5 <= t <= w1 + 5 for w0, w1 in waves)
                if i > 0:
                    wave_orb_total += 1
                    if near:
                        wave_orb_hits += 1
                        wave_orb_hold.append(r["orb"][i] - r["orb"][i-1])

        # 진눈깨비 분당(로테이션 지표)
        flur_pm = []
        for r in lst:
            if r["dur"] > 0:
                flur_pm.append(len(r["flur"]) / (r["dur"]/60))

        b_out = {
            "n": n_f, "kill_med_s": round(med_dur),
            "orb_first_cast_med_s": round(pct(first_orb, .5), 1) if first_orb else None,
            "orb_casts_med_per_fight": pct(sorted(len(r["orb"]) for r in lst), .5),
            "orb_eff_med": round(pct(eff, .5), 2) if eff else None,
            "orb_gap": gap_stats(orb_gaps),
            "orb_gap_rank1_20": gap_stats(gaps_of(top, "orb")),
            "orb_gap_rank21_100": gap_stats(gaps_of(rest, "orb")),
            "ray_gap": gap_stats(ray_gaps),
            "ray_casts_med_per_fight": pct(sorted(len(r["ray"]) for r in lst), .5),
            "bliz_casts_med_per_fight": pct(sorted(len(r["bliz"]) for r in lst), .5),
            "flurry_per_min_med": round(pct(flur_pm, .5), 1) if flur_pm else None,
            "wave_windows_s": [[w0, w1] for w0, w1 in waves],
            "wave_windows_mmss": [f"{mmss(w0)}~{mmss(w1)}" for w0, w1 in waves],
            "orb_on_wave_pct": round(100*wave_orb_hits/wave_orb_total) if wave_orb_total else None,
            "orb_hold_before_wave_med_s": round(pct(wave_orb_hold, .5), 1) if wave_orb_hold else None,
            "bliz_hist_top": sorted(bliz_hist.items(), key=lambda x: -x[1])[:12],
        }
        out["bosses"][boss] = b_out

        print(f"\n===== {boss} (n={n_f}, 킬 중앙 {mmss(med_dur)})", flush=True)
        print(f"  구슬: 첫 시전 {b_out['orb_first_cast_med_s']}s, 판당 {b_out['orb_casts_med_per_fight']}회, 효율 {b_out['orb_eff_med']}")
        print(f"  구슬 간격 전체: {b_out['orb_gap']}")
        print(f"  구슬 간격 1-20위: {b_out['orb_gap_rank1_20']}")
        print(f"  구슬 간격 21-100위: {b_out['orb_gap_rank21_100']}")
        print(f"  광선 간격: {b_out['ray_gap']} (판당 {b_out['ray_casts_med_per_fight']}회)")
        print(f"  눈보라 판당 {b_out['bliz_casts_med_per_fight']}회 · 웨이브 창: {b_out['wave_windows_mmss']}")
        print(f"  구슬-웨이브 겹침 {b_out['orb_on_wave_pct']}% · 웨이브 직전 구슬 간격 중앙 {b_out['orb_hold_before_wave_med_s']}s")

    json.dump(out, open(DATA / "frost_cd_usage.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n저장: data/frost_cd_usage.json", flush=True)


if __name__ == "__main__":
    main()
