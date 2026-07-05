"""사격 사냥꾼(MM) '올100' 갭 분석 — rank 1~5(사실상 100점) vs 21~100 실측 비교.

패턴은 tmp_mine_bm_parse100.py 재사용 (v2_cache_events.json 1.4GB → raw_decode 증분 스캔).
★오늘자(2026-07-05) rankings CSV에 있는 킬만 대상 (CSV report_id/fight_id로 필터)★
★영웅특성(어둠 순찰자 vs 파수꾼)이 보스별로 갈리므로 실행 지표는 영웅트리별로도 분리★

1) casts 기반: 분당 조준 사격(주스펜더), 분당 총 시전, 다운타임(3초+ 무시전 구간 합),
   필러(고정 사격/신비한 사격) 비율, 정조준(주기쿨) 분당 사용
2) 킬타임: rank1~5 킬타임 vs 보스 전체(100명) 중앙값 + 밴드별 분포
3) PI(마력주입): PI CSV(pi_received)만 사용 — events 캐시 buffs에는 외부버프(10060)가
   수집돼 있지 않음(BM 분석에서 이미 확인된 사실, MM도 동일 가정)
출력: data/mm_parse100_gap.json
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

AIMED = 19434        # 조준 사격 (주 스펜더)
ARCANE = 185358      # 신비한 사격 (필러)
STEADY = 56641       # 고정 사격 (필러/자원)
TRUESHOT = 288613    # 정조준 (주기 쿨기)
RAPIDFIRE = 257044   # 속사
PI = 10060           # 마력 주입 (사제 외부버프) — events엔 없음, PI CSV만 사용
GAP_S = 3.0          # 다운타임 판정 기준


def load_hero_sets():
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))["Hunter/Marksmanship"]
    return {t: set(nd["id"] for nd in h["nodes"]) for t, h in tt["hero"].items()}


def load_wanted():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    mm = [r for r in rows if r["class"] == "Hunter" and r["spec"] == "Marksmanship"]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    hero_sets = load_hero_sets()
    wanted, all_rows = {}, mm
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
            "boss": r["encounter_name"], "rank": int(r["rank"]), "char": ch, "hero": hero,
            "t0": f["startTime"], "t1": f["endTime"],
        }
    return wanted, all_rows


def stream_filter(wanted):
    cache = SCRATCH / "mm_parse100_events.json"
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
    downtime = sum((pts[k+1]-pts[k])/1000 for k in range(len(pts)-1) if (pts[k+1]-pts[k])/1000 >= GAP_S)
    n_gaps = sum(1 for k in range(len(pts)-1) if (pts[k+1]-pts[k])/1000 >= GAP_S)
    return {
        "dur": dur,
        "aimed_pm": ids.get(AIMED, 0) / (dur/60),
        "ts_pm": ids.get(TRUESHOT, 0) / (dur/60),
        "casts_pm": len(casts) / (dur/60),
        "downtime_s": downtime,
        "downtime_pm": downtime / (dur/60),
        "n_gaps3": n_gaps,
        "ids": ids,
    }


def band_of(rank):
    if rank <= 5: return "rank_1_5"
    if rank <= 20: return "rank_6_20"
    return "rank_21_100"


def summarize(ms):
    if not ms: return None
    def med(f): return round(pct([m[f] for m in ms], .5), 2)
    filler = []
    for m in ms:
        tot = sum(m["ids"].values())
        if tot: filler.append(100 * (m["ids"].get(ARCANE, 0) + m["ids"].get(STEADY, 0)) / tot)
    return {
        "n": len(ms),
        "aimed_per_min_med": med("aimed_pm"),
        "trueshot_per_min_med": med("ts_pm"),
        "casts_per_min_med": med("casts_pm"),
        "downtime_s_med": med("downtime_s"),
        "downtime_s_per_min_med": med("downtime_pm"),
        "gaps3s_count_med": med("n_gaps3"),
        "filler_pct_med": round(pct(filler, .5), 1) if filler else None,
    }


def main():
    wanted, all_rows = load_wanted()
    print(f"MM player-fights wanted: {len(wanted)} (CSV행 {len(all_rows)})", flush=True)
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
    hc = Counter(i["hero"] for i, _ in per)
    print(f"영웅트리(분석 대상): {dict(hc)}", flush=True)

    allids = Counter()
    for _, m in per: allids.update(m["ids"])
    print("\n시전 상위 15:")
    top_spells = []
    for sid, c in allids.most_common(15):
        d = spell_db.get(str(sid))
        name = d.get("name_ko") if isinstance(d, dict) else None
        top_spells.append({"id": sid, "name": name, "casts": c})
        print(f"  {sid} {name}: {c}")

    bosses = defaultdict(list)
    for i, m in per: bosses[i["boss"]].append((i, m))

    kt = defaultdict(list)
    for r in all_rows:
        kt[r["encounter_name"]].append((int(r["rank"]), int(r["duration_ms"]) / 1000))

    bm_pi = defaultdict(list)
    allspec_pi10 = defaultdict(Counter)
    for r in csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100_pi.csv", encoding="utf-8")):
        if r["pi_received"] == "": continue
        v = r["pi_received"] == "True"
        if int(r["rank"]) <= 10:
            allspec_pi10[r["encounter_name"]][v] += 1
        if r["class"] == "Hunter" and r["spec"] == "Marksmanship":
            bm_pi[r["encounter_name"]].append((int(r["rank"]), v))

    out = {"meta": {
        "date": "2026-07-05",
        "spec": "Hunter-Marksmanship",
        "n_csv_rows": len(all_rows), "n_with_events": len(per),
        "hero_adoption_analyzed": dict(hc),
        "bands": "rank_1_5 / rank_6_20 / rank_21_100",
        "downtime_def": "시전과 시전 사이(전투 시작/끝 포함) 3초 이상 무시전 구간의 합(초)",
        "filler_spell_ids": {"arcane_shot": ARCANE, "steady_shot": STEADY},
        "top_cast_spells": top_spells,
        "pi_source": "PI CSV pi_received만 사용. events 캐시 buffs에 마력주입(10060)이 수집돼 있지 않음(BM 분석에서 확인된 사실과 동일 가정).",
    }, "per_boss": {}, "overall": {}, "overall_by_hero": {}}

    for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
        out["overall"][b] = summarize([m for i, m in per if band_of(i["rank"]) == b])

    for hero in ("어둠 순찰자", "파수꾼"):
        sub = [(i, m) for i, m in per if i["hero"] == hero]
        out["overall_by_hero"][hero] = {
            b: summarize([m for i, m in sub if band_of(i["rank"]) == b])
            for b in ("rank_1_5", "rank_6_20", "rank_21_100")
        }

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
            "rank1_5_med_s": round(pct(top5, .5)) if top5 else None,
            "all100_med_s": round(med_all) if med_all else None,
            "rank1_5_vs_all_diff_s": round(pct(top5, .5) - med_all) if top5 and med_all else None,
            "rank1_5_vs_all_diff_pct": round(100 * (pct(top5, .5) - med_all) / med_all, 1) if top5 and med_all else None,
            "by_band_med_s": {"r1_5": band_med(1, 5), "r6_20": band_med(6, 20),
                              "r21_50": band_med(21, 50), "r51_100": band_med(51, 100)},
            "rank1_10_slower_than_med_pct": round(100 * sum(1 for s in top10 if s > med_all) / len(top10)) if top10 and med_all else None,
        }

        rows_pi = bm_pi.get(boss, [])
        def pi_band(lo, hi):
            sel = [v for r, v in rows_pi if lo <= r <= hi]
            if not sel: return None
            return {"n": len(sel), "pi": sum(sel), "pi_pct": round(100 * sum(sel) / len(sel))}
        pi_ranks_t = sorted(r for r, v in rows_pi if v)
        pi_ranks_f = sorted(r for r, v in rows_pi if not v)
        asp = allspec_pi10.get(boss, Counter())
        d["pi"] = {
            "mm_rank_1_20": pi_band(1, 20),
            "mm_rank_21_100": pi_band(21, 100),
            "mm_all_known": pi_band(1, 100),
            "mm_pi_true_rank_med": pct(pi_ranks_t, .5),
            "mm_pi_false_rank_med": pct(pi_ranks_f, .5),
            "allspec_rank1_10": {"n": asp[True] + asp[False], "pi": asp[True],
                                 "pi_pct": round(100 * asp[True] / (asp[True] + asp[False])) if (asp[True] + asp[False]) else None},
        }
        out["per_boss"][boss] = d

        print(f"\n===== {boss}")
        for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
            s = d[b]
            if s:
                print(f"  {b:12s} n={s['n']:3d} 조준/분 {s['aimed_per_min_med']:5.2f} 정조준/분 {s['trueshot_per_min_med']:5.2f} 총시전/분 {s['casts_per_min_med']:5.1f} "
                      f"다운타임 {s['downtime_s_med']:5.1f}s({s['downtime_s_per_min_med']:.1f}s/분) 필러 {s['filler_pct_med']}%")
            else:
                print(f"  {b:12s} (없음)")
        k = d["killtime"]
        if k["rank1_5_med_s"] is not None:
            print(f"  킬타임: 1~5위 {k['rank1_5_med_s']}s vs 전체중앙 {k['all100_med_s']}s ({k['rank1_5_vs_all_diff_s']:+d}s, {k['rank1_5_vs_all_diff_pct']:+.1f}%) "
                  f"밴드 {k['by_band_med_s']} 상위10 느린킬비율 {k['rank1_10_slower_than_med_pct']}%")
        print(f"  PI(MM, 판정행만): 1~20위 {d['pi']['mm_rank_1_20']} / 21~100위 {d['pi']['mm_rank_21_100']} / "
              f"True중앙랭크 {d['pi']['mm_pi_true_rank_med']} False중앙랭크 {d['pi']['mm_pi_false_rank_med']} / 전스펙 top10 {d['pi']['allspec_rank1_10']}")

    all_t = sorted(r for lst in bm_pi.values() for r, v in lst if v)
    all_f = sorted(r for lst in bm_pi.values() for r, v in lst if not v)
    t20 = sum(1 for r in all_t if r <= 20); f20 = sum(1 for r in all_f if r <= 20)
    out["pi_overall_mm"] = {
        "true_n": len(all_t), "true_rank_med": pct(all_t, .5),
        "false_n": len(all_f), "false_rank_med": pct(all_f, .5),
        "rank1_20_pi_pct": round(100 * t20 / (t20 + f20)) if (t20 + f20) else None,
        "rank1_20_known_n": t20 + f20,
    }
    print(f"\n[PI 종합/MM] True n={len(all_t)} 랭크중앙 {pct(all_t,.5)} / False n={len(all_f)} 랭크중앙 {pct(all_f,.5)} / "
          f"1~20위 판정행 {t20+f20}건 중 PI {out['pi_overall_mm']['rank1_20_pi_pct']}%")

    print("\n===== 전체 밴드 요약 =====")
    for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
        s = out["overall"][b]
        if s:
            print(f"[{b}] n={s['n']} 조준/분 {s['aimed_per_min_med']} 정조준/분 {s['trueshot_per_min_med']} 총시전/분 {s['casts_per_min_med']} "
                  f"다운타임 {s['downtime_s_med']}s({s['downtime_s_per_min_med']}s/분) 필러 {s['filler_pct_med']}%")

    print("\n===== 영웅트리별 밴드 요약 =====")
    for hero in ("어둠 순찰자", "파수꾼"):
        print(f"[{hero}]")
        for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
            s = out["overall_by_hero"][hero][b]
            if s:
                print(f"  [{b}] n={s['n']} 조준/분 {s['aimed_per_min_med']} 정조준/분 {s['trueshot_per_min_med']} 총시전/분 {s['casts_per_min_med']} "
                      f"다운타임 {s['downtime_s_med']}s({s['downtime_s_per_min_med']}s/분) 필러 {s['filler_pct_med']}%")

    json.dump(out, open(DATA / "mm_parse100_gap.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n저장: data/mm_parse100_gap.json", flush=True)


if __name__ == "__main__":
    main()
