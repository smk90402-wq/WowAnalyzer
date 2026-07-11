"""무기 전사(Arms) '올100' 갭 분석 — rank 1~5(사실상 100점) vs 21~100 실측 비교.

패턴은 tmp_mine_mm_parse100.py 재사용. events 원본 스캔 대신 스크래치패드의
arms_cd_events.json(쿨기 분석 때 v2_cache_events.json 1.4GB에서 추출한 casts+buffs
캐시, 2026-07-11 01:37 생성 — events 캐시 최종 갱신 07-10 23:52 이후)을 재사용.
★오늘자 rankings CSV에 있는 킬만 대상 (CSV report_id/fight_id로 필터)★
★영웅특성(거신/학살자)이 갈리므로 실행 지표는 영웅트리별로도 분리★
★주의: events 백필이 보스당 밴드별 층화표본(1~5위 5명 / 6~20위 15명 / 21~100위 13명)★

1) casts 기반: 분당 필사의일격(주 스펜더), 분당 제압, 분당 마무리일격, 분당 격돌,
   분당 총 시전, 다운타임(3초+ 무시전 구간 합), 거인의강타 분당 사용
2) 킬타임: rank1~5 킬타임 vs 보스 전체(100명) 중앙값 + 밴드별 분포 (CSV 900행 전체 사용)
3) PI(마력주입): PI CSV(pi_received)만 사용 — events 캐시 buffs에 외부버프(10060)가
   수집돼 있지 않음(BM/MM 분석과 동일, 이번에도 확인함)
출력: data/arms_parse100_gap.json
"""
from __future__ import annotations
import json, sys, csv
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(r"C:\Users\MKSEORTV\Desktop\WowAnalyzer\data")
SCRATCH = Path(r"C:\Users\MKSEORTV\AppData\Local\Temp\claude\C--Users-MKSEORTV-Desktop-WowAnalyzer\30b0abb8-5226-4b13-9c1c-14e4a1562211\scratchpad")

SPEC_KEY = "Warrior/Arms"
CSV_CLASS, CSV_SPEC = "Warrior", "Arms"
CACHE_NAME = "arms_cd_events.json"
OUT_NAME = "arms_parse100_gap.json"
HEROES = ("거신", "학살자")

MORTALSTRIKE = 12294         # 필사의 일격 (주 스펜더)
OVERPOWER = 7384             # 제압
EXECUTE = {281000, 163201}   # 마무리 일격 (두 ID 모두 캐스트로 관측됨)
SLAM = 1464                  # 격돌 (필러)
COLOSSUS = 167105            # 거인의 강타 (주기 쿨기)
FILLER = {1464, 845}         # 격돌 + 회전베기 (필러/광역 필러)
GAP_S = 3.0                  # 다운타임 판정 기준


def stream_filter(wanted):
    """스크래치패드 cd 캐시 재사용 — 없을 때만 1.4GB 원본 스캔."""
    cache = SCRATCH / CACHE_NAME
    if cache.exists():
        raw = json.load(open(cache, encoding="utf-8"))
        out = {}
        for k, val in raw.items():
            if k not in wanted: continue
            casts = [[c[0], c[1]] for c in (val.get("casts") or []) if len(c) >= 3 and c[2] == "cast"]
            out[k] = {"casts": casts}
        return out
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
    return out


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
            "boss": r["encounter_name"], "rank": int(r["rank"]), "char": ch, "hero": hero,
            "t0": f["startTime"], "t1": f["endTime"],
        }
    return wanted, sel


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
        "spender_pm": ids.get(MORTALSTRIKE, 0) / (dur/60),
        "op_pm": ids.get(OVERPOWER, 0) / (dur/60),
        "exec_pm": sum(ids.get(x, 0) for x in EXECUTE) / (dur/60),
        "slam_pm": ids.get(SLAM, 0) / (dur/60),
        "cd_pm": ids.get(COLOSSUS, 0) / (dur/60),
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
        if tot: filler.append(100 * sum(m["ids"].get(x, 0) for x in FILLER) / tot)
    return {
        "n": len(ms),
        "mortalstrike_per_min_med": med("spender_pm"),
        "overpower_per_min_med": med("op_pm"),
        "execute_per_min_med": med("exec_pm"),
        "slam_per_min_med": med("slam_pm"),
        "colossus_per_min_med": med("cd_pm"),
        "casts_per_min_med": med("casts_pm"),
        "downtime_s_med": med("downtime_s"),
        "downtime_s_per_min_med": med("downtime_pm"),
        "gaps3s_count_med": med("n_gaps3"),
        "filler_pct_med": round(pct(filler, .5), 1) if filler else None,
    }


def main():
    wanted, all_rows = load_wanted()
    print(f"{CSV_SPEC} player-fights wanted: {len(wanted)} (CSV행 {len(all_rows)})", flush=True)
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

    spec_pi = defaultdict(list)
    allspec_pi10 = defaultdict(Counter)
    for r in csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100_pi.csv", encoding="utf-8")):
        if r["pi_received"] == "": continue
        v = r["pi_received"] == "True"
        if int(r["rank"]) <= 10:
            allspec_pi10[r["encounter_name"]][v] += 1
        if r["class"] == CSV_CLASS and r["spec"] == CSV_SPEC:
            spec_pi[r["encounter_name"]].append((int(r["rank"]), v))

    out = {"meta": {
        "date": "2026-07-11",
        "spec": f"{CSV_CLASS}-{CSV_SPEC}",
        "n_csv_rows": len(all_rows), "n_with_events": len(per),
        "hero_adoption_analyzed": dict(hc),
        "bands": "rank_1_5 / rank_6_20 / rank_21_100",
        "sampling_note": "events 백필은 보스당 밴드별 층화표본(1~5위 5명/6~20위 15명/21~100위 13명 내외). 킬타임·PI는 CSV 전수(보스당 100명).",
        "downtime_def": "시전과 시전 사이(전투 시작/끝 포함) 3초 이상 무시전 구간의 합(초)",
        "spell_ids": {"mortal_strike": MORTALSTRIKE, "overpower": OVERPOWER, "execute": sorted(EXECUTE),
                      "slam": SLAM, "colossus_smash": COLOSSUS, "filler": sorted(FILLER)},
        "top_cast_spells": top_spells,
        "pi_source": "PI CSV pi_received만 사용. events 캐시 buffs에 마력주입(10060)이 수집돼 있지 않음(직접 확인).",
    }, "per_boss": {}, "overall": {}, "overall_by_hero": {}}

    for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
        out["overall"][b] = summarize([m for i, m in per if band_of(i["rank"]) == b])

    for hero in HEROES:
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

        rows_pi = spec_pi.get(boss, [])
        def pi_band(lo, hi):
            sel2 = [v for r, v in rows_pi if lo <= r <= hi]
            if not sel2: return None
            return {"n": len(sel2), "pi": sum(sel2), "pi_pct": round(100 * sum(sel2) / len(sel2))}
        pi_ranks_t = sorted(r for r, v in rows_pi if v)
        pi_ranks_f = sorted(r for r, v in rows_pi if not v)
        asp = allspec_pi10.get(boss, Counter())
        d["pi"] = {
            "spec_rank_1_20": pi_band(1, 20),
            "spec_rank_21_100": pi_band(21, 100),
            "spec_all_known": pi_band(1, 100),
            "spec_pi_true_rank_med": pct(pi_ranks_t, .5),
            "spec_pi_false_rank_med": pct(pi_ranks_f, .5),
            "allspec_rank1_10": {"n": asp[True] + asp[False], "pi": asp[True],
                                 "pi_pct": round(100 * asp[True] / (asp[True] + asp[False])) if (asp[True] + asp[False]) else None},
        }
        out["per_boss"][boss] = d

        print(f"\n===== {boss}")
        for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
            s = d[b]
            if s:
                print(f"  {b:12s} n={s['n']:3d} 필일/분 {s['mortalstrike_per_min_med']:5.2f} 거강/분 {s['colossus_per_min_med']:4.2f} 총시전/분 {s['casts_per_min_med']:5.1f} "
                      f"다운타임 {s['downtime_s_med']:5.1f}s({s['downtime_s_per_min_med']:.1f}s/분) 필러 {s['filler_pct_med']}%")
            else:
                print(f"  {b:12s} (없음)")
        k = d["killtime"]
        if k["rank1_5_med_s"] is not None:
            print(f"  킬타임: 1~5위 {k['rank1_5_med_s']}s vs 전체중앙 {k['all100_med_s']}s ({k['rank1_5_vs_all_diff_s']:+d}s, {k['rank1_5_vs_all_diff_pct']:+.1f}%) "
                  f"밴드 {k['by_band_med_s']} 상위10 느린킬비율 {k['rank1_10_slower_than_med_pct']}%")
        print(f"  PI({CSV_SPEC}, 판정행만): 1~20위 {d['pi']['spec_rank_1_20']} / 21~100위 {d['pi']['spec_rank_21_100']} / "
              f"True중앙랭크 {d['pi']['spec_pi_true_rank_med']} False중앙랭크 {d['pi']['spec_pi_false_rank_med']} / 전스펙 top10 {d['pi']['allspec_rank1_10']}")

    all_t = sorted(r for lst in spec_pi.values() for r, v in lst if v)
    all_f = sorted(r for lst in spec_pi.values() for r, v in lst if not v)
    t20 = sum(1 for r in all_t if r <= 20); f20 = sum(1 for r in all_f if r <= 20)
    t5 = sum(1 for r in all_t if r <= 5); f5 = sum(1 for r in all_f if r <= 5)
    out["pi_overall_spec"] = {
        "true_n": len(all_t), "true_rank_med": pct(all_t, .5),
        "false_n": len(all_f), "false_rank_med": pct(all_f, .5),
        "rank1_5_pi_pct": round(100 * t5 / (t5 + f5)) if (t5 + f5) else None,
        "rank1_5_known_n": t5 + f5,
        "rank1_20_pi_pct": round(100 * t20 / (t20 + f20)) if (t20 + f20) else None,
        "rank1_20_known_n": t20 + f20,
        "rank21_100_pi_pct": round(100 * (len(all_t) - t20) / ((len(all_t) - t20) + (len(all_f) - f20))) if ((len(all_t) - t20) + (len(all_f) - f20)) else None,
    }
    print(f"\n[PI 종합/{CSV_SPEC}] True n={len(all_t)} 랭크중앙 {pct(all_t,.5)} / False n={len(all_f)} 랭크중앙 {pct(all_f,.5)} / "
          f"1~5위 PI {out['pi_overall_spec']['rank1_5_pi_pct']}%({t5+f5}건) / 1~20위 PI {out['pi_overall_spec']['rank1_20_pi_pct']}%({t20+f20}건) / "
          f"21~100위 PI {out['pi_overall_spec']['rank21_100_pi_pct']}%")

    print("\n===== 전체 밴드 요약 =====")
    for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
        s = out["overall"][b]
        if s:
            print(f"[{b}] n={s['n']} 필일/분 {s['mortalstrike_per_min_med']} 제압/분 {s['overpower_per_min_med']} 마일/분 {s['execute_per_min_med']} "
                  f"격돌/분 {s['slam_per_min_med']} 거강/분 {s['colossus_per_min_med']} 총시전/분 {s['casts_per_min_med']} "
                  f"다운타임 {s['downtime_s_med']}s({s['downtime_s_per_min_med']}s/분, 갭 {s['gaps3s_count_med']}회) 필러 {s['filler_pct_med']}%")

    print("\n===== 영웅트리별 밴드 요약 =====")
    for hero in HEROES:
        print(f"[{hero}]")
        for b in ("rank_1_5", "rank_6_20", "rank_21_100"):
            s = out["overall_by_hero"][hero][b]
            if s:
                print(f"  [{b}] n={s['n']} 필일/분 {s['mortalstrike_per_min_med']} 거강/분 {s['colossus_per_min_med']} 총시전/분 {s['casts_per_min_med']} "
                      f"다운타임 {s['downtime_s_med']}s({s['downtime_s_per_min_med']}s/분)")

    json.dump(out, open(DATA / OUT_NAME, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n저장: data/{OUT_NAME}", flush=True)


if __name__ == "__main__":
    main()
