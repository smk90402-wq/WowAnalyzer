"""BM 사냥꾼 장식(embellishment) 채택 — 세계지기(보조) vs 비전매듭 통찰(주스탯) 실측.

상위 BM 표본의 이벤트에서 장식 프록 버프 집계:
 - 비전매듭 통찰 1229746 (주스탯 프록)
 - 세계지기 프록 (이름으로 식별 — 버프 census 후)
events 캐시에서 BM 키만 추출(tmp_bm_embellish_events.json 캐시).
출력: 콘솔 (버프 census + 두 장식 채택률).
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from collections import Counter
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import pandas as pd

DATA = Path(__file__).parent / "data"
PER = 70


def main():
    df = pd.read_csv(DATA / "rankings_zone46_mythic_dps_top100.csv")
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    name = lambda s: (db.get(str(s)) or {}).get("name_ko") or f"#{s}"
    bm = df[(df["class"] == "Hunter") & (df["spec"] == "Beast Mastery")].sort_values("rank")
    wanted = {}
    for _, r in bm.iterrows():
        p = pf.get(f'{r["report_id"]}:{int(r["fight_id"])}:{r["character"]}')
        if isinstance(p, dict) and p.get("sourceID") is not None:
            wanted[f'{r["report_id"]}:{int(r["fight_id"])}:{p["sourceID"]}'] = None
        if len(wanted) >= PER * 3:
            break
    cache = DATA / "tmp_bm_embellish_events.json"
    if cache.exists():
        ev = json.load(open(cache, encoding="utf-8"))
    else:
        s = open(DATA / "v2_cache_events.json", encoding="utf-8").read()
        print(f"events {len(s)/1e6:.0f}MB 스캔...", flush=True)
        dec = json.JSONDecoder(); ev, i, n, seen = {}, 1, len(s), 0
        while i < n:
            while i < n and s[i] in " \t\r\n,": i += 1
            if i >= n or s[i] == "}": break
            k, j = dec.raw_decode(s, i); i = j
            while s[i] in " \t\r\n:": i += 1
            v, j = dec.raw_decode(s, i); i = j
            seen += 1
            if seen % 1000 == 0: print(f"  스캔 {seen} 적중 {len(ev)}", flush=True)
            if k in wanted: ev[k] = v
        json.dump(ev, open(cache, "w", encoding="utf-8"))
        print(f"추출 {len(ev)}", flush=True)

    keys = [k for k in wanted if k in ev][:PER]
    # 버프 census (보유 플레이어 수)
    census = Counter()
    for k in keys:
        seen = set()
        for b in (ev[k].get("buffs") or []):
            if len(b) >= 3 and b[2] in ("applybuff", "refreshbuff") and b[1] not in seen:
                census[b[1]] += 1; seen.add(b[1])
    n = len(keys)
    print(f"\nBM {n}명 버프 census (장식·장신구 후보):")
    # 장식/장신구 키워드
    KW = ["비전매듭", "통찰", "세계지기", "세계", "꽁지깃", "잿불", "알른", "상자", "수수께끼"]
    for sid, c in census.most_common(40):
        nm = name(sid)
        mark = " ★" if any(k in nm for k in KW) else ""
        if c >= n * 0.15 or mark:
            print(f"  {sid:>8} {nm:<22} {c}/{n} ({c/n*100:.0f}%){mark}")
    # 비전매듭 통찰 명시 집계
    arcane = census.get(1229746, 0)
    print(f"\n비전매듭 통찰(1229746, 주스탯): {arcane}/{n} ({arcane/n*100:.0f}%)")
    # 세계지기: 이름에 세계지기 들어간 버프
    wk = [(sid, c) for sid, c in census.items() if "세계지기" in name(sid) or "세계 지기" in name(sid)]
    print("세계지기 프록 후보:", [(name(s), f"{c}/{n}") for s, c in wk] or "(이름 매칭 없음 — census 위 목록서 식별)")


if __name__ == "__main__":
    main()
