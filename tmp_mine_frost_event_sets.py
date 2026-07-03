"""냉기 법사 노드 해석용 — events 캐시에서 냉법 키만 뽑아
플레이어별 '시전 스펠 집합 / 버프 집합'만 컴팩트하게 저장.

출력: scratchpad/frost_event_sets.json
  { "rid:fid:sid": {"casts": {spellId: count}, "buffs": [spellId,...]} }
"""
from __future__ import annotations
import json, sys, csv, os
from pathlib import Path
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path(__file__).parent / "data"
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")
OUT = SCRATCH / "frost_event_sets.json"


def load_wanted() -> dict[str, str]:
    """rid:fid:sid → rid:fid:char (냉법 표본)"""
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    frost = [r for r in rows if r["class"] == "Mage" and r["spec"] == "Frost"]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    wanted = {}
    for r in frost:
        key = f'{r["report_id"]}:{int(r["fight_id"])}:{r["character"]}'
        p = pf.get(key)
        if not isinstance(p, dict) or p.get("sourceID") is None:
            continue
        wanted[f'{r["report_id"]}:{int(r["fight_id"])}:{p["sourceID"]}'] = key
    return wanted


def main() -> None:
    wanted = load_wanted()
    print(f"frost wanted keys: {len(wanted)}", flush=True)
    if OUT.exists():
        print("already exists, skip")
        return
    s = open(DATA / "v2_cache_events.json", encoding="utf-8").read()
    print(f"events cache {len(s)/1e6:.0f}MB scan...", flush=True)
    dec = json.JSONDecoder()
    out, i, n, seen = {}, 1, len(s), 0
    while i < n:
        while i < n and s[i] in " \t\r\n,":
            i += 1
        if i >= n or s[i] == "}":
            break
        key, j = dec.raw_decode(s, i); i = j
        while s[i] in " \t\r\n:":
            i += 1
        val, j = dec.raw_decode(s, i); i = j
        seen += 1
        if seen % 2000 == 0:
            print(f"  scan {seen}, hit {len(out)}", flush=True)
        if key in wanted and isinstance(val, dict):
            casts = Counter(c[1] for c in (val.get("casts") or [])
                            if len(c) >= 3 and c[2] == "cast")
            buffs = sorted({b[1] for b in (val.get("buffs") or []) if len(b) >= 2})
            out[key] = {"pfkey": wanted[key],
                        "casts": {str(k): v for k, v in casts.items()},
                        "buffs": buffs}
    json.dump(out, open(OUT, "w", encoding="utf-8"))
    print(f"saved {len(out)}/{len(wanted)} -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
