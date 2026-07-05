# -*- coding: utf-8 -*-
"""악마 흑마 프록 채굴 1단계 — events 캐시(1.4GB)에서 악마 흑마 킬만 추출.
버프 후보를 실측으로 확정해야 하므로 buffs/casts 전체를 보존해 스크래치패드에 캐시.
파싱 패턴은 tmp_mine_frost_proc.py 를 따름(raw_decode 증분 스캔).
"""
from __future__ import annotations
import json, sys, csv
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze\data")
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")
SCRATCH.mkdir(parents=True, exist_ok=True)


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
        wanted[f"{rid}:{fid}:{sid}"] = {
            "boss": r["encounter_name"], "rank": int(r["rank"]), "char": ch,
            "t0": f["startTime"], "t1": f["endTime"],
        }
    return wanted


def main():
    wanted = load_wanted()
    print(f"demo player-fights wanted: {len(wanted)}", flush=True)
    json.dump(wanted, open(SCRATCH / "demo_wanted.json", "w", encoding="utf-8"), ensure_ascii=False)

    cache = SCRATCH / "demo_events.json"
    if cache.exists():
        print("이미 추출됨:", cache); return
    s = open(DATA / "v2_cache_events.json", encoding="utf-8").read()
    print(f"events 캐시 {len(s)/1e6:.0f}MB 스캔...", flush=True)
    dec = json.JSONDecoder()
    out, i, n, seen = {}, 1, len(s), 0
    first = True
    while i < n:
        while i < n and s[i] in " \t\r\n,": i += 1
        if i >= n or s[i] == "}": break
        key, j = dec.raw_decode(s, i); i = j
        while s[i] in " \t\r\n:": i += 1
        val, j = dec.raw_decode(s, i); i = j
        seen += 1
        if seen % 2000 == 0: print(f"  스캔 {seen}, 적중 {len(out)}", flush=True)
        if key in wanted:
            if first:
                print("value keys:", list(val.keys()), flush=True); first = False
            out[key] = {"buffs": val.get("buffs") or [], "casts": val.get("casts") or []}
    json.dump(out, open(cache, "w", encoding="utf-8"))
    print(f"추출 {len(out)}/{len(wanted)} → {cache}", flush=True)


if __name__ == "__main__":
    main()
