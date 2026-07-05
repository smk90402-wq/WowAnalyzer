# -*- coding: utf-8 -*-
"""고통 흑마 이벤트 추출 — v2_cache_events.json(1.4GB) 스트리밍 스캔.

오늘자 rankings_zone46_mythic_dps_top100.csv 의 Warlock/Affliction 킬만 골라
casts/buffs 전체 타임라인을 스크래치패드 aff_events.json 으로 떨굼.
(버프 ID 후보를 아직 모르는 단계라 슬림화 없이 전부 보존 — 이후 분석 스크립트가 재사용)

패턴: tmp_mine_frost_proc.py 의 stream_filter 를 따름.
"""
from __future__ import annotations
import json, sys, csv
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze\data")
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")
SCRATCH.mkdir(parents=True, exist_ok=True)
OUT = SCRATCH / "aff_events.json"
META_OUT = SCRATCH / "aff_wanted.json"


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
        wanted[f"{rid}:{fid}:{sid}"] = {
            "boss": r["encounter_name"], "rank": int(r["rank"]), "char": ch,
            "t0": f["startTime"], "t1": f["endTime"],
        }
    return wanted


def main():
    wanted = load_wanted()
    print(f"aff player-fights wanted: {len(wanted)}", flush=True)
    json.dump(wanted, open(META_OUT, "w", encoding="utf-8"), ensure_ascii=False)

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
            out[key] = {"casts": val.get("casts") or [], "buffs": val.get("buffs") or []}
    json.dump(out, open(OUT, "w", encoding="utf-8"))
    print(f"추출 {len(out)}/{len(wanted)} → {OUT}", flush=True)


if __name__ == "__main__":
    main()
