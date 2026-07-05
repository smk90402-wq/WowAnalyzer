"""악마 흑마 '올100' 갭 분석 — rank 1~5(사실상 100점) vs 21~100 실측 비교.

tmp_mine_bm_parse100.py 템플릿 복제 (2026-07-05, 오늘자 rankings CSV 기준).
1) casts 기반: 분당 총 시전, 분당 굴단의 손/악마 화살, 다운타임(3초+/5초+ 무시전 구간 합),
   악마 폭군 소환 횟수(전투당)
2) 킬타임: rank1~5 vs 전체 중앙 (CSV duration_ms) + 밴드 기울기
3) PI(마력주입): PI CSV(pi_received)만 사용 (events buffs엔 외부버프 미수집 — BM에서 실측 확인)
주의: 캐스터라 하드캐스트(악마 화살 기본 4.5초) 탓에 3초 갭이 과다계상될 수 있어
5초 기준도 병행 산출. 밴드 간 '비교'용으로는 동일 기준이라 유효.
출력: data/demo_parse100_gap.json
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

TYRANT = 265187   # 악마 폭군 소환
HOG = 105174      # 굴단의 손
DEMONBOLT = 264178
SHADOWBOLT = 686
IMPLOSION = 196277  # 임프 폭발 (다중타겟 지표)
GAPS = (3.0, 5.0)


def load_wanted():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    demo = [r for r in rows if r["class"] == "Warlock" and r["spec"].replace(" ", "") == "Demonology"]
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
    return wanted, demo, rows


def stream_filter(wanted):
    cache = SCRATCH / "demo_parse100_events.json"
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
            casts = [[c[0], c[1]] for c in (val.get("casts") or []) if len(c) >= 3 and c[2] == "cast"]
            out[key] = {"casts": casts}
    json.dump(out, open(cache, "w", encoding="utf-8"))
    print(f"추출 {len(out)}/{len(wanted)}", flush=True)
    return out


def pct(vals, q):
    if not vals: return None
    v = sorted(vals)
    idx = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return v[idx]


def fight_metrics(e, t0, t1):
    dur = (t1 - t0) / 1000
    if dur <= 0: return None
    casts = sorted(e["casts"])
    if len(casts) < 20: return None
    ts = [c[0] for c in casts]
    ids = Counter(c[1] for c in casts)
    pts = [t0] + ts + [t1]
    diffs = [(pts[k+1]-pts[k])/1000 for k in range(len(pts)-1)]
    m = {
        "dur": dur,
        "casts_pm": len(casts) / (dur/60),
        "hog_pm": ids.get(HOG, 0) / (dur/60),
        "db_pm": ids.get(DEMONBOLT, 0) / (dur/60),
        "sb_pm": ids.get(SHADOWBOLT, 0) / (dur/60),
        "tyrant_n": ids.get(TYRANT, 0),
        "ids": ids,
    }
    for g in GAPS:
        m[f"downtime{int(g)}_s"] = sum(d for d in diffs if d >= g)
        m[f"downtime{int(g)}_pm"] = m[f"downtime{int(g)}_s"] / (dur/60)
        m[f"n_gaps{int(g)}"] = sum(1 for d in diffs if d >= g)
    return m


def band_of(rank):
    if rank <= 5: return "rank_1_5"
    if rank <= 20: return "rank_6_20"
    return "rank_21_100"


def summarize(ms):
    if not ms: return None
    def med(f): return round(pct([m[f] for m in ms], .5), 2)
    return {
        "n": len(ms),
        "casts_per_min_med": med("casts_pm"),
        "hog_per_min_med": med("hog_pm"),
        "demonbolt_per_min_med": med("db_pm"),
        "shadowbolt_per_min_med": med("sb_pm"),
        "tyrant_per_fight_med": med("tyrant_n"),
        "downtime3s_s_med": med("downtime3_s"),
        "downtime3s_per_min_med": med("downtime3_pm"),
        "gaps3s_count_med": med("n_gaps3"),
        "downtime5s_s_med": med("downtime5_s"),
        "downtime5s_per_min_med": med("downtime5_pm"),
        "gaps5s_count_med": med("n_gaps5"),
    }


def main():
    wanted, demo_rows, _ = load_wanted()
    print(f"Demo player-fights wanted: {len(wanted)} (CSV행 {len(demo_rows)})", flush=True)
    ev = stream_filter(wanted)
    print(f"events 적중: {len(ev)}/{len(wanted)}", flush=True)

    spell_db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))

    per = []
    for k, info in wanted.items():
        e = ev.get(k)
        if not e: continue
        m = fight_metrics(e, info["t0"], info["t1"])
        if m: per.append((info, m))
    print(f"분석 대상 킬: {len(per)}", flush=True)

    allids = Counter()
    for _, m in per: allids.update(m["ids"])
    print("\n시전 상위 20:")
    top_spells = []
    for sid, c in allids.most_common(20):
        d = spell_db.get(str(sid))
        name = d.get("name_ko") if isinstance(d, dict) else None
        top_spells.append({"id": sid, "name": name, "casts": c})
        print(f"  {sid} {name}: {c}")

    bosses = defaultdict(list)
    for i, m in per: bosses[i["boss"]].append((i, m))

    # 킬타임: CSV 전체 100명 기준
    kt = defaultdict(list)
    for r in demo_rows:
        kt[r["encounter_name"]].append((int(r["rank"]), int(r["duration_ms"]) / 1000))

    # PI: CSV만
    demo_pi = defaultdict(list)
    allspec_pi10 = defaultdict(Counter)
    for r in csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100_pi.csv", encoding="utf-8")):
        if r["pi_received"] == "": continue
        v = r["pi_received"] == "True"
        if int(r["rank"]) <= 10:
            allspec_pi10[r["encounter_name"]][v] += 1
        if r["class"] == "Warlock" and r["spec"].replace(" ", "") == "Demonology":
            demo_pi[r["encounter_name"]].append((int(r["rank"]), v))

    out = {"meta": {
        "date": "2026-07-05",
        "spec": "Warlock-Demonology",
        "n_csv_rows": len(demo_rows), "n_with_events": len(per),
        "bands": "rank_1_5 / rank_6_20 / rank_21_100",
        "downtime_def": "시전-시전 간(전투 시작/끝 포함) X초 이상 무시전 구간 합. 캐스터라 하드캐스트가 3초 기준에 일부 걸릴 수 있어 5초 기준 병행 — 밴드 간 비교는 동일 기준이라 유효",
        "top_cast_spells": top_spells,
        "pi_source": "PI CSV pi_received만 사용 (events buffs엔 외부버프 미수집 — BM 분석에서 실측 확인)",
    }, "per_boss": {}, "overall": {}}

    for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
        out["overall"][b] = summarize([m for i, m in per if band_of(i["rank"]) == b])

    for boss, lst in sorted(bosses.items(), key=lambda x: -len(x[1])):
        d = {}
        for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
            d[b] = summarize([m for i, m in lst if band_of(i["rank"]) == b])
        d["all"] = summarize([m for _, m in lst])
        d["ranks_with_events"] = sorted(i["rank"] for i, _ in lst)[:10]

        kts = kt[boss]
        allkt = [s for _, s in kts]
        med_all = pct(allkt, .5)
        def band_med(lo, hi):
            v = [s for r, s in kts if lo <= r <= hi]
            return round(pct(v, .5)) if v else None
        top5 = [s for r, s in kts if r <= 5]
        top10 = [s for r, s in kts if r <= 10]
        d["killtime"] = {
            "rank1_5_med_s": round(pct(top5, .5)),
            "all100_med_s": round(med_all),
            "rank1_5_vs_all_diff_s": round(pct(top5, .5) - med_all),
            "rank1_5_vs_all_diff_pct": round(100 * (pct(top5, .5) - med_all) / med_all, 1),
            "by_band_med_s": {"r1_5": band_med(1, 5), "r6_20": band_med(6, 20),
                              "r21_50": band_med(21, 50), "r51_100": band_med(51, 100)},
            "rank1_10_slower_than_med_pct": round(100 * sum(1 for s in top10 if s > med_all) / len(top10)),
        }

        rows_pi = demo_pi.get(boss, [])
        def pi_band(lo, hi):
            sel = [v for r, v in rows_pi if lo <= r <= hi]
            if not sel: return None
            return {"n": len(sel), "pi": sum(sel), "pi_pct": round(100 * sum(sel) / len(sel))}
        pi_ranks_t = sorted(r for r, v in rows_pi if v)
        pi_ranks_f = sorted(r for r, v in rows_pi if not v)
        asp = allspec_pi10.get(boss, Counter())
        d["pi"] = {
            "demo_rank_1_5": pi_band(1, 5),
            "demo_rank_1_20": pi_band(1, 20),
            "demo_rank_21_100": pi_band(21, 100),
            "demo_all_known": pi_band(1, 100),
            "demo_pi_true_rank_med": pct(pi_ranks_t, .5),
            "demo_pi_false_rank_med": pct(pi_ranks_f, .5),
            "allspec_rank1_10": {"n": asp[True] + asp[False], "pi": asp[True],
                                 "pi_pct": round(100 * asp[True] / (asp[True] + asp[False])) if (asp[True] + asp[False]) else None},
        }
        out["per_boss"][boss] = d

        print(f"\n===== {boss}")
        for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
            s = d[b]
            if s:
                print(f"  {b:12s} n={s['n']:3d} 총시전/분 {s['casts_per_min_med']:5.1f} 굴단 {s['hog_per_min_med']:.2f} 악화 {s['demonbolt_per_min_med']:.2f} "
                      f"폭군/판 {s['tyrant_per_fight_med']:.1f} 다운3s {s['downtime3s_s_med']:5.1f}s 다운5s {s['downtime5s_s_med']:5.1f}s")
            else:
                print(f"  {b:12s} (없음)")
        k = d["killtime"]
        print(f"  킬타임: 1~5위 {k['rank1_5_med_s']}s vs 전체중앙 {k['all100_med_s']}s ({k['rank1_5_vs_all_diff_s']:+d}s, {k['rank1_5_vs_all_diff_pct']:+.1f}%) "
              f"밴드 {k['by_band_med_s']} 상위10 느린킬비율 {k['rank1_10_slower_than_med_pct']}%")
        print(f"  PI: 1~5위 {d['pi']['demo_rank_1_5']} / 1~20위 {d['pi']['demo_rank_1_20']} / 21~100위 {d['pi']['demo_rank_21_100']} / "
              f"전스펙 top10 {d['pi']['allspec_rank1_10']}")

    # ---- 딥다이브: 폭군 횟수 vs 랭크/킬타임 ----
    ty = defaultdict(lambda: defaultdict(list))  # boss -> tyrant_n -> [(rank, dur)]
    for i, m in per:
        ty[i["boss"]][m["tyrant_n"]].append((i["rank"], m["dur"]))
    dd = {}
    for boss, byn in ty.items():
        dd[boss] = {str(n): {"n": len(v),
                             "rank_med": pct([r for r, _ in v], .5),
                             "dur_med_s": round(pct([d for _, d in v], .5))}
                    for n, v in sorted(byn.items())}
    out["deep_dive_tyrant_count"] = {
        "note": "악마 폭군 소환(265187) 전투당 시전 횟수별 랭크/킬타임 중앙값 — 폭군 사이클 수와 킬타임 컷의 관계",
        "per_boss": dd,
    }

    # ---- PI 종합 ----
    all_t = sorted(r for lst in demo_pi.values() for r, v in lst if v)
    all_f = sorted(r for lst in demo_pi.values() for r, v in lst if not v)
    def band_pi(lo, hi):
        t = sum(1 for r in all_t if lo <= r <= hi); f = sum(1 for r in all_f if lo <= r <= hi)
        return {"n": t + f, "pi_pct": round(100 * t / (t + f)) if (t + f) else None}
    out["pi_overall_demo"] = {
        "true_n": len(all_t), "true_rank_med": pct(all_t, .5),
        "false_n": len(all_f), "false_rank_med": pct(all_f, .5),
        "by_band": {"r1_5": band_pi(1, 5), "r6_20": band_pi(6, 20),
                    "r21_50": band_pi(21, 50), "r51_100": band_pi(51, 100)},
    }
    p = out["pi_overall_demo"]
    print(f"\n[PI 종합/Demo] True n={p['true_n']} 랭크중앙 {p['true_rank_med']} / False n={p['false_n']} 랭크중앙 {p['false_rank_med']} / 밴드 {p['by_band']}")

    json.dump(out, open(DATA / "demo_parse100_gap.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("저장: data/demo_parse100_gap.json", flush=True)


if __name__ == "__main__":
    main()
