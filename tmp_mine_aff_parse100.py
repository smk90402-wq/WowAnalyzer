"""고통 흑마(Warlock-Affliction) '올100' 갭 분석 — rank 1~5 vs 21~100 실측 비교.

1) casts 기반: 분당 총 시전, 스펜더(사악한 환희=영혼 조각 소비)/분, 필러/도트 비율,
   다운타임(3초+ 무시전 구간 합), 도트 리캐스트 간격(갱신 규율 프록시),
   스펜더 연속 클러스터 크기(조각 모아 쓰기 vs 나오는 대로 쓰기)
2) 킬타임: rank1~5 vs 보스 중앙값 (CSV duration_ms 전 100명) + 밴드 기울기
3) PI(마력주입): PI CSV(pi_received)만 사용 — events 캐시 buffs에는 10060(마력주입)이
   전혀 수집되지 않음(CSV로 pi_received=True 확정된 킬을 직접 열어 raw buffs 확인 — 0/301
   전부 미검출. BM과 동일한 캐시 한계, tmp_mine_bm_parse100.py pi_source 주석 참고)

파싱 패턴은 tmp_mine_bm_parse100.py 재사용(1.4GB events raw_decode 증분 스캔 → 슬림 캐시).
출력: data/aff_parse100_gap.json
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

PI = 10060      # 마력 주입 (사제 외부버프)
GAP_S = 3.0     # 다운타임 판정 기준
CLUSTER_GAP = 2.5  # 스펜더 연속시전 판정 간격(초)

# ---- 스펠 분류 (probe 결과로 확정, 2026-07-05) ----
# probe 모드: python tmp_mine_aff_parse100.py probe → top40만 출력
SPENDER = 1259790   # 불안정한 고통(조각 소비, 8초 중첩형) — 판당 68.3회, 명실상부 최다 시전
DOTS = {980: "고통", 172: "부패", 1259790: "불안정한 고통"}   # 유지 도트
FILLERS = {686: "어둠의 화살", 198590: "영혼 흡수"}           # 필러(대체 노드로 상호배타)
AGONY = 980         # 리캐스트 간격 추적 대상(주 도트, 갱신해도 피해량 유지 — 클리핑 손해 없음)


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
        wanted[key] = {"boss": r["encounter_name"], "rank": int(r["rank"]), "char": ch,
                       "t0": f["startTime"], "t1": f["endTime"]}
    return wanted, aff, rows


def stream_filter(wanted):
    cache = SCRATCH / "aff_parse100_events.json"
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
    del s
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
    m = {
        "dur": dur,
        "casts_pm": len(casts) / (dur/60),
        "downtime_s": downtime,
        "downtime_pm": downtime / (dur/60),
        "n_gaps3": n_gaps,
        "ids": ids,
    }
    if SPENDER:
        sp_ts = [c[0] for c in casts if c[1] == SPENDER]
        m["spender_pm"] = len(sp_ts) / (dur/60)
        # 클러스터: 연속 스펜더 시전(간격<CLUSTER_GAP) 묶음 크기
        clusters, cur = [], 1
        for k in range(1, len(sp_ts)):
            if (sp_ts[k]-sp_ts[k-1])/1000 < CLUSTER_GAP: cur += 1
            else: clusters.append(cur); cur = 1
        if sp_ts: clusters.append(cur)
        m["spender_cluster_mean"] = (sum(clusters)/len(clusters)) if clusters else None
        m["spender_pct_in_cluster2plus"] = (100*sum(c for c in clusters if c >= 2)/len(sp_ts)) if sp_ts else None
    if AGONY:
        ag_ts = [c[0] for c in casts if c[1] == AGONY]
        iv = [(ag_ts[k+1]-ag_ts[k])/1000 for k in range(len(ag_ts)-1)]
        m["agony_recast_med"] = pct(iv, .5)
        m["agony_recasts"] = len(iv)
    if FILLERS:
        tot = sum(ids.values())
        m["filler_pct"] = 100*sum(ids.get(f, 0) for f in FILLERS)/tot if tot else None
        m["filler_pm"] = sum(ids.get(f, 0) for f in FILLERS)/(dur/60)
    if DOTS:
        m["dot_casts_pm"] = sum(ids.get(d, 0) for d in DOTS)/(dur/60)
    return m


def band_of(rank):
    if rank <= 5: return "rank_1_5"
    if rank <= 20: return "rank_6_20"
    return "rank_21_100"


def summarize(ms):
    if not ms: return None
    def med(f, r=2):
        vals = [m[f] for m in ms if m.get(f) is not None]
        return round(pct(vals, .5), r) if vals else None
    return {
        "n": len(ms),
        "casts_per_min_med": med("casts_pm", 1),
        "spender_per_min_med": med("spender_pm"),
        "filler_per_min_med": med("filler_pm"),
        "filler_pct_med": med("filler_pct", 1),
        "dot_casts_per_min_med": med("dot_casts_pm"),
        "downtime_s_med": med("downtime_s", 1),
        "downtime_s_per_min_med": med("downtime_pm", 2),
        "gaps3s_count_med": med("n_gaps3", 0),
        "agony_recast_med_s": med("agony_recast_med", 1),
        "spender_cluster_mean_med": med("spender_cluster_mean"),
        "spender_pct_in_cluster2plus_med": med("spender_pct_in_cluster2plus", 1),
    }


def main(probe=False):
    wanted, aff_rows, _all = load_wanted()
    print(f"AFF player-fights wanted: {len(wanted)} (CSV행 {len(aff_rows)})", flush=True)
    ev = stream_filter(wanted)
    print(f"events 적중: {len(ev)}/{len(wanted)}", flush=True)

    spell_db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))

    allids = Counter()
    for k in ev:
        allids.update(c[1] for c in ev[k]["casts"])
    top_spells = []
    print("\n시전 상위 40:")
    for sid, c in allids.most_common(40):
        d = spell_db.get(str(sid))
        name = d.get("name_ko") if isinstance(d, dict) else None
        top_spells.append({"id": sid, "name": name, "casts": c})
        print(f"  {sid} {name}: {c}")
    if probe:
        json.dump(top_spells, open(SCRATCH / "aff_top_casts.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return

    per = []
    for k, info in wanted.items():
        e = ev.get(k)
        if not e: continue
        m = fight_metrics(e, info["t0"], info["t1"])
        if m: per.append((info, m))
    print(f"분석 대상 킬: {len(per)}", flush=True)

    out = {"meta": {
        "date": "2026-07-05",
        "spec": "Warlock-Affliction",
        "n_csv_rows": len(aff_rows), "n_with_events": len(per),
        "bands": "rank_1_5 / rank_6_20 / rank_21_100",
        "downtime_def": "시전과 시전 사이(전투 시작/끝 포함) 3초 이상 무시전 구간의 합(초)",
        "spender_id": SPENDER, "dot_ids": DOTS, "filler_ids": FILLERS, "agony_id": AGONY,
        "spender_cluster_def": f"간격 {CLUSTER_GAP}초 미만 연속 스펜더 시전 묶음 — 평균 묶음 크기와 2연속+ 비중(조각 모아쓰기 지표)",
        "top_cast_spells": top_spells[:20],
    }, "per_boss": {}, "overall": {}}

    # 전체 밴드 요약
    for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
        out["overall"][b] = summarize([m for i, m in per if band_of(i["rank"]) == b])

    # 킬타임: CSV 전체 100명
    kt = defaultdict(list)
    for r in aff_rows:
        kt[r["encounter_name"]].append((int(r["rank"]), int(r["duration_ms"]) / 1000))

    # PI CSV
    aff_pi = defaultdict(list)
    allspec_pi10 = defaultdict(Counter)
    for r in csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100_pi.csv", encoding="utf-8")):
        if r["pi_received"] == "": continue
        v = r["pi_received"] == "True"
        if int(r["rank"]) <= 10:
            allspec_pi10[r["encounter_name"]][v] += 1
        if r["class"] == "Warlock" and r["spec"] == "Affliction":
            aff_pi[r["encounter_name"]].append((int(r["rank"]), v))

    out["meta"]["pi_source"] = ("PI CSV pi_received만 사용. events 캐시 buffs에는 마력주입(10060)이 "
        "전혀 수집되지 않음 — CSV로 pi_received=True 확정된 킬을 직접 열어 raw buffs 확인했으나 0건 검출. "
        "BM 분석 때와 동일한 캐시 한계(tmp_mine_bm_parse100.py 참고).")

    bosses = defaultdict(list)
    for i, m in per: bosses[i["boss"]].append((i, m))

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
            "rank1_10_slower_than_med_pct": round(100 * sum(1 for s in top10 if s > med_all) / len(top10)) if top10 else None,
        }

        rows_pi = aff_pi.get(boss, [])
        def pi_band(lo, hi):
            sel = [v for r, v in rows_pi if lo <= r <= hi]
            if not sel: return None
            return {"n": len(sel), "pi": sum(sel), "pi_pct": round(100 * sum(sel) / len(sel))}
        pi_t = sorted(r for r, v in rows_pi if v)
        pi_f = sorted(r for r, v in rows_pi if not v)
        asp = allspec_pi10.get(boss, Counter())
        d["pi"] = {
            "aff_rank_1_5": pi_band(1, 5),
            "aff_rank_1_20": pi_band(1, 20),
            "aff_rank_21_100": pi_band(21, 100),
            "aff_all_known": pi_band(1, 100),
            "aff_pi_true_rank_med": pct(pi_t, .5),
            "aff_pi_false_rank_med": pct(pi_f, .5),
            "allspec_rank1_10": {"n": asp[True] + asp[False], "pi": asp[True],
                "pi_pct": round(100 * asp[True] / (asp[True] + asp[False])) if (asp[True] + asp[False]) else None},
        }
        out["per_boss"][boss] = d

        print(f"\n===== {boss}")
        for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
            s = d[b]
            if s:
                print(f"  {b:12s} n={s['n']:3d} 시전/분 {s['casts_per_min_med']} 스펜더/분 {s['spender_per_min_med']} "
                      f"필러 {s['filler_pct_med']}% 다운 {s['downtime_s_med']}s 고통리캐 {s['agony_recast_med_s']}s "
                      f"클러스터 {s['spender_cluster_mean_med']}")
            else:
                print(f"  {b:12s} (없음)")
        k2 = d["killtime"]
        print(f"  킬타임: 1~5위 {k2['rank1_5_med_s']}s vs 전체중앙 {k2['all100_med_s']}s ({k2['rank1_5_vs_all_diff_s']:+d}s, {k2['rank1_5_vs_all_diff_pct']:+.1f}%) 밴드 {k2['by_band_med_s']}")
        print(f"  PI(CSV): 1~5위 {d['pi']['aff_rank_1_5']} / 1~20위 {d['pi']['aff_rank_1_20']} / 21~100위 {d['pi']['aff_rank_21_100']} / 전스펙 top10 {d['pi']['allspec_rank1_10']}")

    # PI 종합
    all_t = sorted(r for lst in aff_pi.values() for r, v in lst if v)
    all_f = sorted(r for lst in aff_pi.values() for r, v in lst if not v)
    def pi_range(lo, hi):
        t = sum(1 for r in all_t if lo <= r <= hi); f = sum(1 for r in all_f if lo <= r <= hi)
        return {"n": t+f, "pi": t, "pi_pct": round(100*t/(t+f))} if t+f else None
    out["pi_overall_aff"] = {
        "true_n": len(all_t), "true_rank_med": pct(all_t, .5),
        "false_n": len(all_f), "false_rank_med": pct(all_f, .5),
        "rank_1_5": pi_range(1, 5), "rank_6_20": pi_range(6, 20), "rank_21_100": pi_range(21, 100),
    }
    print(f"\n[PI 종합/AFF] True n={len(all_t)}(랭크중앙 {pct(all_t,.5)}) False n={len(all_f)}(랭크중앙 {pct(all_f,.5)})")
    print(f"  1~5위 {out['pi_overall_aff']['rank_1_5']} / 6~20위 {out['pi_overall_aff']['rank_6_20']} / 21~100위 {out['pi_overall_aff']['rank_21_100']}")

    json.dump(out, open(DATA / "aff_parse100_gap.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("저장: data/aff_parse100_gap.json", flush=True)


if __name__ == "__main__":
    main(probe="probe" in sys.argv)
