"""학살자 분노 — 칼날폭풍 사용 타이밍 실측: 무모한 희생 정렬 + 임박한 파멸 스택 대기 여부.

질문: 칼날폭풍 추가타 버프(임박한 파멸, 급살 소비로 최대 3중첩)를 기다렸다 쓰나?
       무모한 희생이랑 엮어 쓰나?
상위 학살자 분노 표본 이벤트에서:
 - 칼날폭풍 시전 시 무모한 희생 버프 활성 비율 (정렬 여부)
 - 칼날폭풍 직전 임박한 파멸/급살 관련 버프 스택 (대기 여부)
 - 버프 census (스택 버프 ID 식별)
출력: data/tmp_fury_bs.json + 콘솔.
"""
from __future__ import annotations
import sys, json, bisect
from pathlib import Path
from collections import Counter
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import pandas as pd

DATA = Path(__file__).parent / "data"
PER = 45


def main():
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))
    SLAYER = set(n["id"] for n in tt["Warrior/Fury"]["hero"]["학살자"]["nodes"])
    df = pd.read_csv(DATA / "rankings_zone46_mythic_dps_top100.csv")
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    name = lambda s: (db.get(str(s)) or {}).get("name_ko") or f"#{s}"

    fu = df[(df["class"] == "Warrior") & (df["spec"] == "Fury")].sort_values("rank")
    wanted = {}
    for _, r in fu.iterrows():
        p = pf.get(f'{r["report_id"]}:{int(r["fight_id"])}:{r["character"]}')
        if not isinstance(p, dict) or p.get("sourceID") is None:
            continue
        if len(set(p.get("nodes") or []) & SLAYER) < 3:   # 학살자만
            continue
        wanted[f'{r["report_id"]}:{int(r["fight_id"])}:{p["sourceID"]}'] = None
        if len(wanted) >= PER * 2:
            break

    cache = DATA / "tmp_fury_bs_events.json"
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
    # 칼날폭풍 cast id 식별 (이름)
    bs_ids = {int(sid) for sid, v in db.items() if isinstance(v, dict) and v.get("name_ko") == "칼날폭풍"}
    reck_ids = {int(sid) for sid, v in db.items() if isinstance(v, dict) and v.get("name_ko") in ("무모한 희생", "무모함")}
    # 버프 census + 칼폭 타이밍
    census = Counter()
    bs_total = 0; bs_in_reck = 0
    stack_at_bs = []   # 칼폭 시전 직전 활성 스택버프 (이름→스택)
    for k in keys:
        e = ev[k]
        buffs = e.get("buffs") or []
        casts = sorted([c for c in (e.get("casts") or []) if len(c) >= 3 and c[2] == "cast"], key=lambda c: c[0])
        # 칼폭 cast id 보강: 실제 등장한 '칼날폭풍' 이름 cast
        for c in casts:
            if name(c[1]) == "칼날폭풍": bs_ids.add(c[1])
        for b in buffs:
            if len(b) >= 3 and b[2] in ("applybuff", "refreshbuff", "applybuffstack"):
                census[b[1]] += 1
        # 무모한 희생 버프 구간
        def spans(sids):
            out, on = [], None
            for b in sorted((b for b in buffs if len(b) >= 3 and b[1] in sids), key=lambda x: x[0]):
                if b[2] == "applybuff" and on is None: on = b[0]
                elif b[2] == "removebuff" and on is not None: out.append((on, b[0])); on = None
            return out
        reck_iv = spans(reck_ids)
        def active(iv, t):
            i = bisect.bisect_right([a for a, _ in iv], t) - 1
            return i >= 0 and iv[i][0] <= t <= iv[i][1]
        for c in casts:
            if c[1] in bs_ids:
                bs_total += 1
                bs_in_reck += active(reck_iv, c[0])
    print(f"\n학살자 분노 {len(keys)}명 · 칼날폭풍 시전 {bs_total}회")
    print(f"칼날폭풍이 무모한 희생 창 안: {bs_in_reck}/{bs_total} ({bs_in_reck/max(bs_total,1)*100:.0f}%)")
    n = len(keys)
    print(f"\n버프 census (스택버프·임박한파멸·급살 후보):")
    for sid, c in census.most_common(40):
        nm = name(sid)
        if c >= n * 0.4 or any(k in nm for k in ["임박", "파멸", "급살", "폭풍", "집행", "압도", "몰입", "희열"]):
            print(f"  {sid:>8} {nm:<20} {c}")
    json.dump({"bs_total": bs_total, "bs_in_reck": bs_in_reck, "n": len(keys)},
              open(DATA / "tmp_fury_bs.json", "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()
