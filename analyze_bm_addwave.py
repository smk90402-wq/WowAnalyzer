"""야수냥꾼 쫄파이(다중 타겟 웨이브) 오프너 분석 — 선격노 vs 모은 뒤 격노.

1단계: 보스별 마구잡이 난타(1264359) 캐스트 분포로 쫄웨이브 시점 역산,
야수의 격노(19574)가 웨이브 대비 언제 들어가는지 top100 행동 확인.
"""
from __future__ import annotations
import json, sys, csv, os
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(__file__).parent / "data"
TMP = Path(os.environ.get("BM_TMP", "/tmp"))

WT = 1264359   # 마구잡이 난타
BW = 19574     # 야수의 격노
KC = 34026     # 살상 명령
COTW = 359844  # 야생의 부름
HOWL = 471877  # 무리의 지도자의 포효 (버프)
STAMP_IDS = {472741, 1258338, 1258344}

def load_wanted():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    bm = [r for r in rows if r["class"] == "Hunter" and r["spec"].replace(" ", "") == "BeastMastery"]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    wanted = {}
    for r in bm:
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
            "rid": rid, "fid": fid,
            "t0": f["startTime"], "t1": f["endTime"],
            "aoe_build": 102341 in set(p.get("nodes") or []),
        }
    return wanted

def stream_filter(wanted):
    cache = TMP / "bm_addwave_events.json"
    if cache.exists():
        return json.load(open(cache, encoding="utf-8"))
    s = open(DATA / "v2_cache_events.json", encoding="utf-8").read()
    dec = json.JSONDecoder()
    out, i, n = {}, 1, len(s)
    while i < n:
        while i < n and s[i] in ' \t\r\n,': i += 1
        if i >= n or s[i] == '}': break
        key, j = dec.raw_decode(s, i); i = j
        while s[i] in ' \t\r\n:': i += 1
        val, j = dec.raw_decode(s, i); i = j
        if key in wanted:
            out[key] = val
    json.dump(out, open(cache, "w", encoding="utf-8"))
    return out

def main():
    wanted = load_wanted()
    print(f"BM player-fights wanted: {len(wanted)}", flush=True)
    ev = stream_filter(wanted)
    print(f"events hit: {len(ev)}/{len(wanted)}", flush=True)

    bybs = defaultdict(list)
    for k, info in wanted.items():
        e = ev.get(k)
        if e: bybs[info["boss"]].append((info, e))

    for boss, lst in sorted(bybs.items(), key=lambda x: -len(x[1])):
        durs, wt_hist, bw_hist = [], Counter(), Counter()
        wt_users = 0; buff_ids = Counter(); wt_total = 0
        for info, e in lst:
            t0 = info["t0"]
            durs.append((info["t1"] - t0) / 1000)
            casts = [c for c in (e.get("casts") or []) if len(c) >= 3 and c[2] == "cast"]
            wts = [(c[0]-t0)/1000 for c in casts if c[1] == WT]
            bws = [(c[0]-t0)/1000 for c in casts if c[1] == BW]
            if wts: wt_users += 1
            wt_total += len(wts)
            for t in wts: wt_hist[int(t//5)*5] += 1
            for t in bws: bw_hist[int(t//5)*5] += 1
            for b in (e.get("buffs") or []):
                if len(b) >= 2 and (b[1] in STAMP_IDS or b[1] == HOWL):
                    buff_ids[b[1]] += 1
        durs.sort()
        med = durs[len(durs)//2]
        print(f"\n===== {boss} (n={len(lst)}, 킬타임중앙 {med:.0f}s, 난타사용 {wt_users}/{len(lst)}, 난타총 {wt_total})")
        line = " ".join(f"{t}:{c}" for t, c in sorted(wt_hist.items(), key=lambda x: -x[1])[:14])
        print(f"  난타 핫빈: {line}")
        line = " ".join(f"{t}:{c}" for t, c in sorted(bw_hist.items(), key=lambda x: -x[1])[:14])
        print(f"  격노 핫빈: {line}")
        print(f"  버프관측(쇄도/포효): {dict(buff_ids)}")

if __name__ == "__main__":
    main()
