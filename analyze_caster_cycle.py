"""정기 주술사 · 악마 흑마 — 로그 기반 딜사이클/버튼/유틸 실측.

사용자 결정 기준: 딜사이클 복잡도 + '눌러야 할 유틸 기술 수'.
신화 top100 표본(스펙당 상위 ~50판)의 cast/buff 이벤트에서:
 - 분당 시전(버튼별), 고유 시전 스펠 수(=버튼 가짓수)
 - 오프너 시퀀스 최빈
 - 유틸/생존/이속/차단 시전 빈도 (딜 외 버튼)
출력: data/tmp_caster_events.json(캐시) + data/tmp_caster_cycle.json.

events 캐시(대용량)에서 정기/악마 키만 증분 추출.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from collections import Counter, defaultdict
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import pandas as pd

DATA = Path(__file__).parent / "data"
SPECS = [("Shaman", "Elemental"), ("Warlock", "Demonology")]
PER_SPEC = 60   # 스펙당 상위 표본 (보스 가로질러)

# 딜 외 '유틸' 스펠 분류용 키워드 (한글명 기준). 정확 분류는 출력 후 큐레이션.
UTIL_KW = ["차단", "발차기", "바람 폭발", "공포", "주문 잠금", "정화", "해제", "토템", "관문",
           "순간이동", "쇄도", "벽", "보호", "생명력 전환", "결속", "환영", "분산", "질주",
           "치유", "회복", "선조", "영혼의 우물", "돌", "부활", "감전", "묶기"]


def build_sample():
    df = pd.read_csv(DATA / "rankings_zone46_mythic_dps_top100.csv")
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    rows = []
    for cls, sp in SPECS:
        sub = df[(df["class"] == cls) & (df["spec"] == sp)].sort_values("rank")
        n = 0
        for _, r in sub.iterrows():
            key = f'{r["report_id"]}:{int(r["fight_id"])}:{r["character"]}'
            p = pf.get(key)
            if not isinstance(p, dict) or p.get("sourceID") is None:
                continue
            m = meta.get(r["report_id"]) or {}
            f = next((x for x in (m.get("fights") or []) if x.get("id") == int(r["fight_id"])), None)
            if not f:
                continue
            rows.append({"cls": cls, "spec": sp, "rid": r["report_id"], "fid": int(r["fight_id"]),
                         "char": r["character"], "sid": p["sourceID"],
                         "boss": r["encounter_name"], "rank": int(r["rank"])})
            n += 1
            if n >= PER_SPEC:
                break
    return rows


def extract_events(rows):
    cache = DATA / "tmp_caster_events.json"
    if cache.exists():
        return json.load(open(cache, encoding="utf-8"))
    wanted = {f'{r["rid"]}:{r["fid"]}:{r["sid"]}' for r in rows}
    print(f"대상 키: {len(wanted)}", flush=True)
    s = open(DATA / "v2_cache_events.json", encoding="utf-8").read()
    print(f"events 캐시 {len(s)/1e6:.0f}MB 스캔...", flush=True)
    dec = json.JSONDecoder(); out, i, n, seen = {}, 1, len(s), 0
    while i < n:
        while i < n and s[i] in " \t\r\n,": i += 1
        if i >= n or s[i] == "}": break
        key, j = dec.raw_decode(s, i); i = j
        while s[i] in " \t\r\n:": i += 1
        val, j = dec.raw_decode(s, i); i = j
        seen += 1
        if seen % 1000 == 0: print(f"  스캔 {seen}, 적중 {len(out)}", flush=True)
        if key in wanted: out[key] = val
    json.dump(out, open(cache, "w", encoding="utf-8"))
    print(f"추출 {len(out)}/{len(wanted)}", flush=True)
    return out


def main():
    rows = build_sample()
    print("표본:", Counter(f'{r["cls"]}/{r["spec"]}' for r in rows))
    ev = extract_events(rows)
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    name = lambda s: (db.get(str(s)) or {}).get("name_ko") or f"#{s}"

    out = {}
    for cls, sp in SPECS:
        sub = [r for r in rows if r["cls"] == cls and r["spec"] == sp]
        freq, dur_min = Counter(), 0.0
        openers = Counter()
        n_fights = 0
        for r in sub:
            e = ev.get(f'{r["rid"]}:{r["fid"]}:{r["sid"]}')
            if not e: continue
            casts = [c for c in (e.get("casts") or []) if len(c) >= 3 and c[2] == "cast"]
            if len(casts) < 30: continue
            n_fights += 1
            dur_min += (casts[-1][0] - casts[0][0]) / 60000
            for c in casts:
                freq[c[1]] += 1
            openers[" → ".join(name(c[1])[:6] for c in casts[:10])] += 1
        if not dur_min:
            continue
        # 분당 시전
        cpm = [(name(s), round(c / dur_min, 1)) for s, c in freq.most_common(40)]
        # 유틸 분리
        util = [(n, v) for n, v in cpm if any(k in n for k in UTIL_KW)]
        deal = [(n, v) for n, v in cpm if not any(k in n for k in UTIL_KW)]
        # 버튼 수: 분당 0.3회 이상 시전된 고유 스펠 (노이즈 컷)
        active_buttons = [n for n, v in cpm if v >= 0.3]
        out[f"{cls}|{sp}"] = {
            "n_fights": n_fights,
            "unique_spells": len(freq),
            "active_buttons_0.3pm": len(active_buttons),
            "casts_per_min_total": round(sum(freq.values()) / dur_min, 1),
            "deal_buttons": deal[:18],
            "util_buttons": util,
            "opener_top": openers.most_common(2),
        }
        print(f"\n===== {cls}/{sp} (n={n_fights}) =====")
        print(f"총 분당시전 {out[f'{cls}|{sp}']['casts_per_min_total']} · 고유스펠 {len(freq)} · 능동버튼(≥0.3/분) {len(active_buttons)}")
        print("딜 버튼:", " · ".join(f"{n} {v}" for n, v in deal[:14]))
        print("유틸 버튼:", " · ".join(f"{n} {v}" for n, v in util) or "(키워드매칭 없음 — 출력 검토)")
        print("오프너:", openers.most_common(1)[0] if openers else "-")
    json.dump(out, open(DATA / "tmp_caster_cycle.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n저장: tmp_caster_cycle.json")


if __name__ == "__main__":
    main()
