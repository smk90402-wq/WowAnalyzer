"""야수냥 '올100' 갭 분석 — rank 1~5(사실상 100점) vs 21~100 실측 비교.

1) casts 기반: 분당 살상 명령, 분당 총 시전, 다운타임(3초+ 무시전 구간 합), 필러(코브라) 비율
2) 킬타임: rank1~5 킬타임 vs 보스 중앙값 (CSV duration_ms, 전 100명) + 밴드별 기울기
3) PI(마력주입): PI CSV(pi_received)만 사용 — events 캐시 buffs에는 외부버프(10060)가
   수집돼 있지 않음을 실측 확인(1차 실행에서 42건 True 로그 전부 buffs에 부재).

파싱 패턴은 tmp_mine_frost_cd.py / analyze_bm_addwave.py 재사용
(1.4GB events 캐시 → raw_decode 증분 스캔, 스크래치패드에 슬림 캐시).
출력: data/bm_parse100_gap.json
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

KC = 34026      # 살상 명령
BARBED = 217200 # 날카로운 사격
WT = 1264359    # 마구잡이 난타 (다중타겟 전용 — 쫄 유무 판별용)
PI = 10060      # 마력 주입 (사제 외부버프) — events엔 없음, 슬림캐시 필드만 유지
GAP_S = 3.0     # 다운타임 판정 기준


def load_wanted():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    bm = [r for r in rows if r["class"] == "Hunter" and r["spec"].replace(" ", "") == "BeastMastery"]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    wanted, all_rows = {}, bm
    for r in bm:
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
    return wanted, all_rows


def stream_filter(wanted):
    cache = SCRATCH / "bm_parse100_events.json"
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
            pi_ev = [[b[0], b[2]] for b in (val.get("buffs") or []) if len(b) >= 3 and b[1] == PI]
            out[key] = {"casts": casts, "pi": pi_ev}
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
    # 다운타임: 시작→첫시전, 시전 간, 마지막→끝 중 3초 이상 구간 합
    pts = [t0] + ts + [t1]
    downtime = sum((pts[k+1]-pts[k])/1000 for k in range(len(pts)-1) if (pts[k+1]-pts[k])/1000 >= GAP_S)
    n_gaps = sum(1 for k in range(len(pts)-1) if (pts[k+1]-pts[k])/1000 >= GAP_S)
    return {
        "dur": dur,
        "kc_pm": ids.get(KC, 0) / (dur/60),
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


def summarize(ms, filler_id):
    if not ms: return None
    def med(f): return round(pct([m[f] for m in ms], .5), 2)
    fil = []
    for m in ms:
        tot = sum(m["ids"].values())
        if tot: fil.append(100 * m["ids"].get(filler_id, 0) / tot)
    barbed = [m["ids"].get(BARBED, 0) / (m["dur"]/60) for m in ms]
    return {
        "n": len(ms),
        "kc_per_min_med": med("kc_pm"),
        "barbed_per_min_med": round(pct(barbed, .5), 2),
        "casts_per_min_med": med("casts_pm"),
        "downtime_s_med": med("downtime_s"),
        "downtime_s_per_min_med": med("downtime_pm"),
        "gaps3s_count_med": med("n_gaps3"),
        "filler_pct_med": round(pct(fil, .5), 1) if fil else None,
    }


def main():
    wanted, all_rows = load_wanted()
    print(f"BM player-fights wanted: {len(wanted)} (CSV행 {len(all_rows)})", flush=True)
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

    # 시전 ID 상위 확인 → 필러(코브라) ID 실측 판별
    allids = Counter()
    for _, m in per: allids.update(m["ids"])
    print("\n시전 상위 15:")
    filler_id, top_spells = None, []
    for sid, c in allids.most_common(15):
        d = spell_db.get(str(sid))
        name = d.get("name_ko") if isinstance(d, dict) else None
        top_spells.append({"id": sid, "name": name, "casts": c})
        print(f"  {sid} {name}: {c}")
        if filler_id is None and name and "코브라" in str(name):
            filler_id = sid
    if filler_id is None: filler_id = 193455
    print(f"필러(코브라) ID: {filler_id}")

    # ---- 보스별 집계 ----
    bosses = defaultdict(list)
    for i, m in per: bosses[i["boss"]].append((i, m))

    # 킬타임: CSV 전체 100명 기준 (events 없어도)
    kt = defaultdict(list)
    for r in all_rows:
        kt[r["encounter_name"]].append((int(r["rank"]), int(r["duration_ms"]) / 1000))

    # PI: CSV(pi_received)만 신뢰 — BM행 + 전스펙 rank1~10 맥락
    bm_pi = defaultdict(list)      # boss -> [(rank, True/False)]
    allspec_pi10 = defaultdict(Counter)  # boss -> Counter(True/False) @ rank<=10 전스펙
    for r in csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100_pi.csv", encoding="utf-8")):
        if r["pi_received"] == "": continue
        v = r["pi_received"] == "True"
        if int(r["rank"]) <= 10:
            allspec_pi10[r["encounter_name"]][v] += 1
        if r["class"] == "Hunter" and r["spec"].replace(" ", "") == "BeastMastery":
            bm_pi[r["encounter_name"]].append((int(r["rank"]), v))

    out = {"meta": {
        "date": "2026-07-03",
        "spec": "Hunter-BeastMastery",
        "n_csv_rows": len(all_rows), "n_with_events": len(per),
        "bands": "rank_1_5 / rank_6_20 / rank_21_100",
        "downtime_def": "시전과 시전 사이(전투 시작/끝 포함) 3초 이상 무시전 구간의 합(초)",
        "filler_spell_id": filler_id,
        "top_cast_spells": top_spells,
        "pi_source": "PI CSV pi_received만 사용. events 캐시 buffs에 마력주입(10060)이 수집돼 있지 않음(PI=True 표본 4건 raw buffs 직접 확인). BM 900행 중 판정값 있는 행 107(True 42/False 65) — 부분표본임.",
    }, "per_boss": {}, "overall": {}}

    # 전체 밴드 요약
    for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
        out["overall"][b] = summarize([m for i, m in per if band_of(i["rank"]) == b], filler_id)

    for boss, lst in sorted(bosses.items(), key=lambda x: -len(x[1])):
        d = {}
        # 1) casts 밴드 비교
        for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
            d[b] = summarize([m for i, m in lst if band_of(i["rank"]) == b], filler_id)
        d["all"] = summarize([m for _, m in lst], filler_id)
        d["ranks_with_events"] = sorted(i["rank"] for i, _ in lst)[:10]

        # 2) 킬타임 (CSV 100명) + 밴드 기울기
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

        # 3) PI — CSV 판정값 있는 행만
        rows_pi = bm_pi.get(boss, [])
        def pi_band(lo, hi):
            sel = [v for r, v in rows_pi if lo <= r <= hi]
            if not sel: return None
            return {"n": len(sel), "pi": sum(sel), "pi_pct": round(100 * sum(sel) / len(sel))}
        pi_ranks_t = sorted(r for r, v in rows_pi if v)
        pi_ranks_f = sorted(r for r, v in rows_pi if not v)
        asp = allspec_pi10.get(boss, Counter())
        d["pi"] = {
            "bm_rank_1_20": pi_band(1, 20),
            "bm_rank_21_100": pi_band(21, 100),
            "bm_all_known": pi_band(1, 100),
            "bm_pi_true_rank_med": pct(pi_ranks_t, .5),
            "bm_pi_false_rank_med": pct(pi_ranks_f, .5),
            "allspec_rank1_10": {"n": asp[True] + asp[False], "pi": asp[True],
                                 "pi_pct": round(100 * asp[True] / (asp[True] + asp[False])) if (asp[True] + asp[False]) else None},
        }
        out["per_boss"][boss] = d

        print(f"\n===== {boss}")
        for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
            s = d[b]
            if s:
                print(f"  {b:12s} n={s['n']:3d} 살상/분 {s['kc_per_min_med']:5.2f} 날사/분 {s['barbed_per_min_med']:5.2f} 총시전/분 {s['casts_per_min_med']:5.1f} "
                      f"다운타임 {s['downtime_s_med']:5.1f}s({s['downtime_s_per_min_med']:.1f}s/분) 코브라 {s['filler_pct_med']}%")
            else:
                print(f"  {b:12s} (없음)")
        k = d["killtime"]
        print(f"  킬타임: 1~5위 {k['rank1_5_med_s']}s vs 전체중앙 {k['all100_med_s']}s ({k['rank1_5_vs_all_diff_s']:+d}s, {k['rank1_5_vs_all_diff_pct']:+.1f}%) "
              f"밴드 {k['by_band_med_s']} 상위10 느린킬비율 {k['rank1_10_slower_than_med_pct']}%")
        print(f"  PI(BM, 판정행만): 1~20위 {d['pi']['bm_rank_1_20']} / 21~100위 {d['pi']['bm_rank_21_100']} / "
              f"True중앙랭크 {d['pi']['bm_pi_true_rank_med']} False중앙랭크 {d['pi']['bm_pi_false_rank_med']} / 전스펙 top10 {d['pi']['allspec_rank1_10']}")

    # ---- 딥다이브: 살라다르 두 가지 킬 전략 (쫄 있는 긴 킬 vs 쫄 스킵 짧은 킬) ----
    sal = []
    for i, m in bosses.get("Fallen-King Salhadaar", []):
        sal.append({"rank": i["rank"], "dur_s": round(m["dur"]),
                    "wild_thrash_casts": m["ids"].get(WT, 0)})
    sal.sort(key=lambda x: x["rank"])
    with_adds = [x for x in sal if x["wild_thrash_casts"] > 0]
    no_adds = [x for x in sal if x["wild_thrash_casts"] == 0]
    out["deep_dive_salhadaar"] = {
        "note": "마구잡이 난타(다중타겟 전용) 시전 유무로 '쫄 페이즈를 본 킬'과 '쫄 전에 끝낸 킬'을 구분",
        "kills_with_adds": {"n": len(with_adds),
                            "dur_med_s": pct([x["dur_s"] for x in with_adds], .5),
                            "rank_med": pct([x["rank"] for x in with_adds], .5)},
        "kills_no_adds": {"n": len(no_adds),
                          "dur_med_s": pct([x["dur_s"] for x in no_adds], .5),
                          "rank_med": pct([x["rank"] for x in no_adds], .5)},
        "top5_with_adds": sum(1 for x in with_adds if x["rank"] <= 5),
        "per_kill": sal,
    }
    dd = out["deep_dive_salhadaar"]
    print(f"\n[살라다르 딥다이브] 쫄킬 n={dd['kills_with_adds']['n']} (킬 {dd['kills_with_adds']['dur_med_s']}s, 랭크중앙 {dd['kills_with_adds']['rank_med']}) "
          f"vs 노쫄킬 n={dd['kills_no_adds']['n']} (킬 {dd['kills_no_adds']['dur_med_s']}s, 랭크중앙 {dd['kills_no_adds']['rank_med']}) / top5 중 쫄킬 {dd['top5_with_adds']}")

    # ---- PI 종합 (BM 판정행 107건) ----
    all_t = sorted(r for lst in bm_pi.values() for r, v in lst if v)
    all_f = sorted(r for lst in bm_pi.values() for r, v in lst if not v)
    t20 = sum(1 for r in all_t if r <= 20); f20 = sum(1 for r in all_f if r <= 20)
    out["pi_overall_bm"] = {
        "true_n": len(all_t), "true_rank_med": pct(all_t, .5),
        "false_n": len(all_f), "false_rank_med": pct(all_f, .5),
        "rank1_20_pi_pct": round(100 * t20 / (t20 + f20)) if (t20 + f20) else None,
        "rank1_20_known_n": t20 + f20,
    }
    print(f"[PI 종합/BM] True n={len(all_t)} 랭크중앙 {pct(all_t,.5)} / False n={len(all_f)} 랭크중앙 {pct(all_f,.5)} / "
          f"1~20위 판정행 {t20+f20}건 중 PI {out['pi_overall_bm']['rank1_20_pi_pct']}%")

    json.dump(out, open(DATA / "bm_parse100_gap.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("저장: data/bm_parse100_gap.json", flush=True)


if __name__ == "__main__":
    main()
