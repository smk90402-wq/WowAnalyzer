"""사격냥 어둠순찰자 딜사이클 실측 — 오프너·검은화살 간격·캐스트 빈도 (빌드 대조).

v2_cache_events.json(수백MB)에서 MM 키만 증분 추출 → data/tmp_mm_events.json 캐시.
키 형식: rid:fid:sourceID (casts: [t, spellID, type], buffs: [t, spellID, type]).

분석:
 1. 빌드별 캐스트 빈도 (분당) — 어떤 스킬을 얼마나 누르나
 2. 오프너: 첫 20캐스트 시퀀스 최빈 패턴 (빌드별)
 3. 검은 화살(466930) 시전 간격 분포 — 프록 리셋이면 기본쿨보다 짧은 간격 다수
 4. 버프 스택 추적: applybuffstack 최대 스택 (속사류 스택 시스템 확인)
출력: data/tmp_mm_cycle.json + 콘솔.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from collections import Counter, defaultdict
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import pandas as pd

DATA = Path(__file__).parent / "data"
BLACK_ARROW = 466930


def extract_mm_events():
    cache = DATA / "tmp_mm_events.json"
    if cache.exists():
        return json.load(open(cache, encoding="utf-8"))
    d = pd.read_csv(DATA / "tmp_mm_builds.csv")
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    wanted = {}
    for _, r in d.iterrows():
        p = pf.get(f"{r.rid}:{int(r.fid)}:{r.char}")
        if isinstance(p, dict) and p.get("sourceID") is not None:
            wanted[f"{r.rid}:{int(r.fid)}:{p['sourceID']}"] = None
    print(f"MM 대상 키: {len(wanted)}", flush=True)
    s = open(DATA / "v2_cache_events.json", encoding="utf-8").read()
    print(f"events 캐시 {len(s)/1e6:.0f}MB 읽음, 스캔...", flush=True)
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
        if seen % 500 == 0:
            print(f"  스캔 {seen}, 적중 {len(out)}", flush=True)
        if key in wanted:
            out[key] = val
    json.dump(out, open(cache, "w", encoding="utf-8"))
    print(f"추출 완료: {len(out)}/{len(wanted)}", flush=True)
    return out


def main():
    ev = extract_mm_events()
    d = pd.read_csv(DATA / "tmp_mm_builds.csv")
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    name = lambda sid: (db.get(str(sid)) or {}).get("name_ko") or f"#{sid}"

    rows = []
    for _, r in d.iterrows():
        p = pf.get(f"{r.rid}:{int(r.fid)}:{r.char}") or {}
        sid = p.get("sourceID")
        e = ev.get(f"{r.rid}:{int(r.fid)}:{sid}") if sid is not None else None
        if e:
            rows.append((r, e))
    print(f"이벤트 보유 MM: {len(rows)}명 (DR {sum(1 for r,_ in rows if r.build=='DR')}, 파 {sum(1 for r,_ in rows if r.build=='SEN')})")

    out = {"per_build": {}}
    for build in ("DR", "SEN"):
        sub = [(r, e) for r, e in rows if r.build == build]
        if not sub:
            continue
        freq = Counter()          # 스킬 → 총 시전
        openers = Counter()       # 첫 12캐스트 시퀀스(이름 축약) 빈도
        ba_gaps = []              # 검은화살 간격(s)
        stacks = defaultdict(int) # buff spellID → 최대 스택
        dur_min = 0.0
        for r, e in sub:
            casts = [c for c in (e.get("casts") or []) if len(c) >= 3 and c[2] == "cast"]
            if not casts:
                continue
            t0 = casts[0][0]
            dur_min += (casts[-1][0] - t0) / 60000
            for c in casts:
                freq[c[1]] += 1
            seq = [name(c[1])[:6] for c in casts[:12]]
            openers[" → ".join(seq)] += 1
            ba = [c[0] for c in casts if c[1] == BLACK_ARROW]
            ba_gaps += [round((b - a) / 1000, 1) for a, b in zip(ba, ba[1:])]
            for b in (e.get("buffs") or []):
                if len(b) >= 4 and b[2] == "applybuffstack":
                    stacks[b[1]] = max(stacks[b[1]], b[3] if isinstance(b[3], int) else 0)
        top_freq = [(name(s), round(c / dur_min, 1)) for s, c in freq.most_common(14)] if dur_min else []
        gap_hist = Counter(int(g // 5) * 5 for g in ba_gaps)   # 5초 버킷
        out["per_build"][build] = {
            "n": len(sub),
            "casts_per_min": top_freq,
            "opener_top3": openers.most_common(3),
            "black_arrow_gaps_5s_bucket": dict(sorted(gap_hist.items())),
            "max_stacks_top": sorted(((name(s), st) for s, st in stacks.items() if st >= 5),
                                     key=lambda x: -x[1])[:10],
        }
        print(f"\n=== {build} (n={len(sub)}) 분당 시전 ===")
        for nm, cpm in top_freq:
            print(f"  {nm:<14} {cpm}/분")
        print("오프너 최빈:", openers.most_common(1)[0] if openers else "-")
        if ba_gaps:
            s_ = pd.Series(ba_gaps)
            print(f"검은화살 간격: 중앙 {s_.median():.1f}s · 최빈버킷 {gap_hist.most_common(1)} · n={len(ba_gaps)}")
        print("스택버프(≥5):", out["per_build"][build]["max_stacks_top"])
    json.dump(out, open(DATA / "tmp_mm_cycle.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n저장: tmp_mm_cycle.json")


if __name__ == "__main__":
    main()
