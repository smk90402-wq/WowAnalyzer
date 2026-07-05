# -*- coding: utf-8 -*-
"""고통 흑마 프록/교대 규율 실측 — 일몰(Sunset)·조각의 불안정성(Shard Instability)
발동→소모 지연, 낭비율(겹침/만료), DoT(고통/부패/불안정한 고통) 재시전 간격 규율,
영혼의 조각 소비(불안정한 고통 시전) 타이밍. 등수밴드(1-20 vs 21-100) 비교.

이벤트 캐시는 casts/buffs 만 있고 대상 디버프(DoT) 타임라인은 없음
(backfill_v2 의 events 는 player buffs + casts 만 수집) → DoT 갱신 규율은
캐스트 간격(재시전 gap)을 그 스킬의 지속시간과 비교하는 방식으로 대체 측정.

스펠 ID 확정 (data/spell_db.json 공식 한글명 + data/talent_trees.json Warlock/Affliction 대조):
  일몰(Sunset) 264571/1260279 (특성 분기로 둘 중 하나만 관측 — 한 판 내 상호배타 확인됨)
    → 부패로 피해 시 발동, 다음 어둠의 화살(686) 즉시시전 또는 재앙의 손아귀(1261153) 50%가속
  조각의 불안정성(Shard Instability) 1260269 (근원 특성 스펠ID 1260264, 버프ID는 다름— 실측으로 확정)
    → 어둠의 화살(686)/영혼 흡수(198590 대체판) 피해 시 20% 확률, 다음 불안정한 고통(1259790) 조각 소모 없이 즉시시전
  DoT: 고통(980, 18초, 갱신해도 피해량 유지) / 부패(172, 14초) / 불안정한 고통(1259790, 8초, 중첩형, 해제 시 대상 침묵)
  조각 소비: 불안정한 고통(1259790, 조각1개) / 부패의 씨앗(27243, 조각1개)

파싱 패턴은 tmp_mine_frost_proc.py 를 따름 (스크래치패드 aff_cd_events.json 캐시 재사용 — 오늘자
캐시로 확인됨, 재추출 불필요). 대상: 오늘자(2026-07-05) rankings CSV 교집합 301킬(이벤트 캐시 적중분).

출력: data/aff_proc_discipline.json
"""
from __future__ import annotations
import json, sys, csv
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze\data")
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")

SUNSET_IDS = {264571, 1260279}     # 일몰 (특성분기, 상호배타)
SHARD_INSTAB = 1260269             # 조각의 불안정성 (버프)
SHADOW_BOLT = 686                  # 어둠의 화살
DRAIN_SOUL = 198590                # 영혼 흡수 (어둠의 화살 대체 노드 채택 시, 실측으로 확정된 실제 스펠ID)
MALEFIC_RAPTURE = 1261153          # 재앙의 손아귀 (일몰 소비 대안 캐스트)
UA = 1259790                       # 불안정한 고통 (조각 소모)
SEED = 27243                       # 부패의 씨앗 (조각 소모, 밤의 수혜 특성 시 일몰도 소비)
SUNSET_CONSUMERS = {SHADOW_BOLT, DRAIN_SOUL, MALEFIC_RAPTURE, SEED}
AGONY = 980                        # 고통
CORRUPTION = 172                   # 부패
AGONY_DUR_S = 18.0
CORR_DUR_S = 14.0
UA_DUR_S = 8.0
EXPIRY_SLOP = 1.3   # 자연만료 판정 여유배수

BOSS_KO = {3176: "아베르지안", 3177: "보라시우스", 3178: "바엘고어&에조라크",
           3179: "살라다르", 3180: "선봉대", 3181: "우주의 왕관",
           3182: "벨로렌", 3183: "한밤의 도래(르우라)", 3306: "카이메루스"}


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
        wanted[key] = {
            "boss": BOSS_KO.get(int(r["encounter_id"]), r["encounter_name"]),
            "rank": int(r["rank"]), "char": ch,
            "t0": f["startTime"], "t1": f["endTime"],
        }
    return wanted


def load_events(wanted):
    """오늘자 캐시 aff_cd_events.json 이 wanted 의 부분집합으로 유효함(사전 확인됨) → 재사용."""
    cache = SCRATCH / "aff_cd_events.json"
    ev = json.load(open(cache, encoding="utf-8"))
    return {k: v for k, v in ev.items() if k in wanted}


def analyze_fight(e, t0, t1):
    buffs = sorted(e.get("buffs") or [], key=lambda b: b[0])
    casts = sorted(e.get("casts") or [], key=lambda c: c[0])
    cast_only = [(c[0], c[1]) for c in casts if len(c) >= 3 and c[2] == "cast"]

    def next_cast_after(ts, ids, within_ms=8000):
        for ct, cid in cast_only:
            if ct < ts: continue
            if ct - ts > within_ms: return None
            if cid in ids: return ct - ts
        return None

    r = {
        "dur_s": (t1 - t0) / 1000,
        "sunset_holds": [], "sunset_gains": 0, "sunset_overwrites": 0, "sunset_expiries": 0,
        "shard_holds": [], "shard_gains": 0, "shard_overwrites": 0, "shard_expiries": 0,
        "ua_casts": [], "agony_casts": [], "corr_casts": [], "seed_casts": [],
    }

    # ── 일몰 (스택형: applybuff/applybuffstack 진입, removebuffstack/removebuff 소모) ──
    active = 0
    gain_ts = []
    for b in buffs:
        if b[1] not in SUNSET_IDS: continue
        ts, typ = b[0], b[2]
        if typ == "applybuff":
            if active > 0: r["sunset_overwrites"] += 1
            active = 1; gain_ts = [ts]; r["sunset_gains"] += 1
        elif typ == "applybuffstack":
            active += 1; gain_ts.append(ts); r["sunset_gains"] += 1
        elif typ == "removebuffstack":
            if gain_ts:
                consumed_ts = gain_ts.pop(0)
                delay = next_cast_after(ts, SUNSET_CONSUMERS)
                if delay is not None: r["sunset_holds"].append(delay / 1000)
            active = max(0, active - 1)
        elif typ == "removebuff":
            if gain_ts:
                delay = next_cast_after(ts, SUNSET_CONSUMERS)
                if delay is not None:
                    r["sunset_holds"].append(delay / 1000)
                else:
                    r["sunset_expiries"] += 1
                gain_ts = []
            active = 0

    # ── 조각의 불안정성 (단일 스택 apply→remove) ──
    active_at = None
    for b in buffs:
        if b[1] != SHARD_INSTAB: continue
        ts, typ = b[0], b[2]
        if typ == "applybuff":
            if active_at is not None: r["shard_overwrites"] += 1
            active_at = ts; r["shard_gains"] += 1
        elif typ == "refreshbuff":
            r["shard_overwrites"] += 1
            r["shard_gains"] += 1
            active_at = ts
        elif typ == "removebuff":
            if active_at is not None:
                delay = next_cast_after(ts, {UA})
                if delay is not None:
                    r["shard_holds"].append(delay / 1000)
                else:
                    r["shard_expiries"] += 1
            active_at = None

    r["ua_casts"] = [t for t, i in cast_only if i == UA]
    r["agony_casts"] = [t for t, i in cast_only if i == AGONY]
    r["corr_casts"] = [t for t, i in cast_only if i == CORRUPTION]
    r["seed_casts"] = [t for t, i in cast_only if i == SEED]
    return r


def gaps_of(ts_list):
    return [(b - a) / 1000 for a, b in zip(ts_list, ts_list[1:])]


def pct(vals, q):
    if not vals: return None
    v = sorted(vals)
    idx = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return round(v[idx], 2)


def dot_discipline(gaps, dur_s):
    """재시전 간격을 DoT 지속시간과 비교 — 조기(클리핑)/적정/지연(공백) 분류."""
    if not gaps: return None
    early = sum(1 for g in gaps if g < dur_s * 0.5)          # 절반도 안 됐는데 재시전(조각/시간 낭비)
    near = sum(1 for g in gaps if dur_s * 0.5 <= g <= dur_s * EXPIRY_SLOP)  # 만료 직전~직후 적정 리필
    late = sum(1 for g in gaps if g > dur_s * EXPIRY_SLOP)   # 만료 후 한참 지나 공백 있었음
    n = len(gaps)
    return {
        "n_recasts": n,
        "gap_median_s": pct(gaps, 0.5), "gap_p75_s": pct(gaps, 0.75), "gap_p90_s": pct(gaps, 0.9),
        "early_clip_pct": round(100 * early / n, 1),
        "near_expiry_refill_pct": round(100 * near / n, 1),
        "late_gap_pct": round(100 * late / n, 1),
        "dur_s": dur_s,
    }


def summarize(fights):
    tot_min = sum(f["dur_s"] for f in fights) / 60
    sunset_holds = sorted(h for f in fights for h in f["sunset_holds"])
    shard_holds = sorted(h for f in fights for h in f["shard_holds"])
    sunset_gains = sum(f["sunset_gains"] for f in fights)
    sunset_waste = sum(f["sunset_overwrites"] + f["sunset_expiries"] for f in fights)
    shard_gains = sum(f["shard_gains"] for f in fights)
    shard_waste = sum(f["shard_overwrites"] + f["shard_expiries"] for f in fights)

    agony_gaps = sorted(g for f in fights for g in gaps_of(f["agony_casts"]) if g < 60)
    corr_gaps = sorted(g for f in fights for g in gaps_of(f["corr_casts"]) if g < 60)
    ua_gaps = sorted(g for f in fights for g in gaps_of(f["ua_casts"]) if g < 60)

    ua_per_min = sum(len(f["ua_casts"]) for f in fights) / tot_min if tot_min else None
    seed_per_min = sum(len(f["seed_casts"]) for f in fights) / tot_min if tot_min else None

    return {
        "n_fights": len(fights),
        "sunset": {
            "gains": sunset_gains,
            "n_consumed_tracked": len(sunset_holds),
            "consume_delay_s_median": pct(sunset_holds, 0.5), "p75": pct(sunset_holds, 0.75), "p90": pct(sunset_holds, 0.9),
            "used_within_2s_pct": round(100 * sum(1 for h in sunset_holds if h <= 2) / len(sunset_holds), 1) if sunset_holds else None,
            "used_within_4s_pct": round(100 * sum(1 for h in sunset_holds if h <= 4) / len(sunset_holds), 1) if sunset_holds else None,
            "waste_pct": round(100 * sunset_waste / sunset_gains, 1) if sunset_gains else None,
            "overwrites": sum(f["sunset_overwrites"] for f in fights),
            "expiries_or_unmatched": sum(f["sunset_expiries"] for f in fights),
            "procs_per_min": round(sunset_gains / tot_min, 2) if tot_min else None,
        },
        "shard_instability": {
            "gains": shard_gains,
            "n_consumed_tracked": len(shard_holds),
            "consume_delay_s_median": pct(shard_holds, 0.5), "p75": pct(shard_holds, 0.75), "p90": pct(shard_holds, 0.9),
            "used_within_2s_pct": round(100 * sum(1 for h in shard_holds if h <= 2) / len(shard_holds), 1) if shard_holds else None,
            "used_within_4s_pct": round(100 * sum(1 for h in shard_holds if h <= 4) / len(shard_holds), 1) if shard_holds else None,
            "waste_pct": round(100 * shard_waste / shard_gains, 1) if shard_gains else None,
            "overwrites": sum(f["shard_overwrites"] for f in fights),
            "expiries_or_unmatched": sum(f["shard_expiries"] for f in fights),
            "procs_per_min": round(shard_gains / tot_min, 2) if tot_min else None,
        },
        "dot_recast_discipline": {
            "agony": dot_discipline(agony_gaps, AGONY_DUR_S),
            "corruption": dot_discipline(corr_gaps, CORR_DUR_S),
            "unstable_affliction": dot_discipline(ua_gaps, UA_DUR_S),
        },
        "shard_spend_per_min": {
            "unstable_affliction": round(ua_per_min, 2) if ua_per_min else None,
            "seed_of_corruption": round(seed_per_min, 2) if seed_per_min else None,
        },
    }


def main():
    wanted = load_wanted()
    print(f"고통 흑마 player-fights wanted: {len(wanted)}", flush=True)
    ev = load_events(wanted)
    print(f"events 적중(오늘자 캐시 재사용): {len(ev)}/{len(wanted)}", flush=True)

    per = []
    for k, info in ev.items():
        w = wanted.get(k)
        if not w: continue
        r = analyze_fight(ev[k], w["t0"], w["t1"])
        if len(r["ua_casts"]) < 5:
            continue
        per.append((w, r))
    print(f"분석 대상 킬: {len(per)}", flush=True)

    def band(i): return "rank_1_20" if i["rank"] <= 20 else "rank_21_100"

    out = {
        "meta": {
            "collected": "2026-07-05 rankings CSV 교집합, events 캐시 적중분",
            "n_kills": len(per),
            "bands": {b: sum(1 for i, _ in per if band(i) == b) for b in ("rank_1_20", "rank_21_100")},
            "rank_1_10_n": sum(1 for i, _ in per if i["rank"] <= 10),
            "spells": {
                "sunset": sorted(SUNSET_IDS), "shard_instability_buff": SHARD_INSTAB,
                "shadow_bolt": SHADOW_BOLT, "drain_soul": DRAIN_SOUL, "malefic_rapture": MALEFIC_RAPTURE,
                "unstable_affliction": UA, "seed_of_corruption": SEED,
                "agony": AGONY, "corruption": CORRUPTION,
            },
            "note": ("sunset consume_delay = 일몰 버프 소모(스택 감소/제거) 시점→이후 8초 내 "
                     "어둠의 화살/영혼 흡수/재앙의 손아귀/부패의 씨앗(밤의 수혜 특성 시) 시전까지 지연. "
                     "매칭 실패는 waste(만료 추정)로 집계. "
                     "shard_instability 동일 로직, 대상 스킬은 불안정한 고통. "
                     "dot_recast_discipline: 재시전 간격을 지속시간과 비교 — early_clip(50% 미만 시점 재시전)/"
                     "near_expiry_refill(50%~130%, 적정)/late_gap(130% 초과, 공백 발생). "
                     "DoT는 디버프 타임라인이 캐시에 없어 캐스트 간격으로 대체 측정(직접 만료 관측 아님). "
                     "★부패(Corruption) 주의★: '완전한 부패'(row5 CHOICE, 부패 무한 지속)가 사실상 표준 채택이라 "
                     "판당 재시전 1~4회뿐(773회/286킬) — 갱신 규율이 아니라 '1회 시전 후 방치'가 정상. "
                     "이 스펠의 early_clip/late_gap 수치는 목표 대상 교체·초반 재시전 잡음일 뿐 '규율 위반'으로 해석 금지."),
        },
        "overall": {}, "per_boss": {},
    }

    for b in ("rank_1_20", "rank_21_100"):
        out["overall"][b] = summarize([r for i, r in per if band(i) == b])
    out["overall"]["all"] = summarize([r for _, r in per])
    out["overall"]["rank_1_10"] = summarize([r for i, r in per if i["rank"] <= 10])

    bosses = defaultdict(list)
    for i, r in per: bosses[i["boss"]].append((i, r))
    for boss, lst in sorted(bosses.items(), key=lambda x: -len(x[1])):
        d = {}
        for b in ("all", "rank_1_20", "rank_21_100"):
            sub = lst if b == "all" else [(i, r) for i, r in lst if band(i) == b]
            d[b] = summarize([r for _, r in sub])
        out["per_boss"][boss] = d

    json.dump(out, open(DATA / "aff_proc_discipline.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("저장: data/aff_proc_discipline.json", flush=True)

    for b in ("rank_1_20", "rank_21_100"):
        s = out["overall"][b]
        if not s: continue
        print(f"\n[{b}] n={s['n_fights']}")
        su = s["sunset"]
        print(f"  일몰: 소모지연 중앙 {su['consume_delay_s_median']}s p90 {su['p90']}s "
              f"2s내 {su['used_within_2s_pct']}% 낭비 {su['waste_pct']}% (획득 {su['gains']}, 분당 {su['procs_per_min']})")
        sh = s["shard_instability"]
        print(f"  조각불안정성: 소모지연 중앙 {sh['consume_delay_s_median']}s 2s내 {sh['used_within_2s_pct']}% "
              f"낭비 {sh['waste_pct']}% (획득 {sh['gains']}, 분당 {sh['procs_per_min']})")
        dd = s["dot_recast_discipline"]
        for name, key in (("고통", "agony"), ("부패", "corruption"), ("불안정한고통", "unstable_affliction")):
            v = dd[key]
            if v:
                print(f"  {name} 재시전: 중앙간격 {v['gap_median_s']}s(지속 {v['dur_s']}s) "
                      f"조기클립 {v['early_clip_pct']}% 적정 {v['near_expiry_refill_pct']}% 공백 {v['late_gap_pct']}%")


if __name__ == "__main__":
    main()
