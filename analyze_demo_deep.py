"""악마 흑마 심층 — 폭군창 구성·악마의 핵 관리·장신구·물약·스탯 실측.

상위 60판(tmp_caster_events + player_fight)에서:
 1. 악마 폭군(265187) 창: 길이·창 내 시전 구성(굴단의 손/악마화살/임프폭발 횟수)
 2. 악마의 핵(264173): 최대 스택, 분당 소비(악마화살)
 3. 장신구: slot 12/13 item id 빈도 → item_db 한글명 (top 조합)
 4. 물약: 무모함(1236994)·열광(1238443) 전투물약 채택률
 5. 손아귀 분쇄 등 핵심기 분당
출력: data/tmp_demo_deep.json + 콘솔.
"""
from __future__ import annotations
import sys, json, bisect
from pathlib import Path
from collections import Counter, defaultdict
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import pandas as pd

DATA = Path(__file__).parent / "data"
TYRANT = 265187      # 악마 폭군 소환 (버프 = 폭군 활성창)
DCORE = 264173       # 악마의 핵
POTIONS = {1236994: "무모함의 물약", 1238443: "열광의 물약"}
# 핵심 시전 스펠 (한글명으로 매칭)
KEY_CASTS = ["굴단의 손", "악마 화살", "어둠의 화살", "손아귀 분쇄", "악마 폭군 소환",
             "임프 폭발", "영혼 흡수", "지옥불꽃 화살", "지옥불 화살", "둠가드"]


def main():
    ev = json.load(open(DATA / "tmp_caster_events.json", encoding="utf-8"))
    df = pd.read_csv(DATA / "rankings_zone46_mythic_dps_top100.csv")
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    item_db = json.load(open(DATA / "item_db.json", encoding="utf-8"))
    name = lambda s: (db.get(str(s)) or {}).get("name_ko") or f"#{s}"
    iname = lambda i: (item_db.get(str(i)) or {}).get("name_ko") or (item_db.get(str(i)) or {}).get("name") or f"item{i}"

    demo = df[(df["class"] == "Warlock") & (df["spec"] == "Demonology")].sort_values("rank")
    players = []  # (row, sourceID, gear)
    for _, r in demo.iterrows():
        p = pf.get(f'{r["report_id"]}:{int(r["fight_id"])}:{r["character"]}')
        if not isinstance(p, dict) or p.get("sourceID") is None:
            continue
        k = f'{r["report_id"]}:{int(r["fight_id"])}:{p["sourceID"]}'
        if k in ev:
            players.append((r, p, ev[k]))
        if len(players) >= 60:
            break

    # ── 1. 폭군창 구성 + 2. 악마의 핵 + 5. 핵심기 분당 ──
    tyr_durs, tyr_inside = [], Counter()
    tyr_count_per = []
    dcore_max = []
    freq, dur_min = Counter(), 0.0
    pot_users = Counter()
    for r, p, e in players:
        casts = sorted([c for c in (e.get("casts") or []) if len(c) >= 3 and c[2] == "cast"], key=lambda c: c[0])
        buffs = e.get("buffs") or []
        if len(casts) < 30:
            continue
        dur_min += (casts[-1][0] - casts[0][0]) / 60000
        for c in casts:
            freq[c[1]] += 1
        # 폭군창 (applybuff~removebuff of TYRANT)
        tyr_iv, on = [], None
        for b in sorted((b for b in buffs if len(b) >= 3 and b[1] == TYRANT), key=lambda x: x[0]):
            if b[2] == "applybuff" and on is None: on = b[0]
            elif b[2] == "removebuff" and on is not None: tyr_iv.append((on, b[0])); on = None
        tyr_count_per.append(len(tyr_iv))
        for a, bend in tyr_iv:
            tyr_durs.append((bend - a) / 1000)
            for c in casts:
                if a <= c[0] <= bend:
                    tyr_inside[name(c[1])] += 1
        # 악마의 핵 최대 스택
        mx = max((b[4] for b in buffs if len(b) >= 5 and b[1] == DCORE and isinstance(b[4], int)), default=0)
        dcore_max.append(mx)
        # 물약
        for b in buffs:
            if len(b) >= 3 and b[1] in POTIONS and b[2] == "applybuff":
                pot_users[POTIONS[b[1]]] += 1
                break

    n = len([1 for r, p, e in players if len(e.get("casts") or []) >= 30])
    cpm = lambda nm: next((c / dur_min for s, c in freq.items() if name(s) == nm), 0)

    # ── 3. 장신구 ──
    trinket_combo = Counter()
    trinket_single = Counter()
    for r, p, e in players:
        ts = sorted((it.get("id") for it in (p.get("gear") or []) if it.get("slot") in (12, 13) and it.get("id")))
        if len(ts) == 2:
            trinket_combo[tuple(ts)] += 1
        for t in ts:
            trinket_single[t] += 1

    out = {
        "n": n,
        "tyrant_window": {
            "avg_duration_s": round(pd.Series(tyr_durs).median(), 1) if tyr_durs else None,
            "windows_per_fight": round(pd.Series(tyr_count_per).mean(), 1) if tyr_count_per else None,
            "inside_casts_top": [(k, round(v / max(len(tyr_durs), 1), 1)) for k, v in tyr_inside.most_common(8)],
        },
        "demonic_core": {"median_max_stack": int(pd.Series(dcore_max).median()) if dcore_max else None,
                         "max_seen": max(dcore_max) if dcore_max else None},
        "key_casts_per_min": {nm: round(cpm(nm), 1) for nm in
                              ["굴단의 손", "악마 화살", "어둠의 화살", "손아귀 분쇄", "악마 폭군 소환",
                               "임프 폭발", "영혼 흡수", "둠가드 소환", "지옥불 화살"]},
        "trinkets_top_single": [(iname(i), c, f"{c/n*100:.0f}%") for i, c in trinket_single.most_common(6)],
        "trinkets_top_combo": [(f"{iname(a)} + {iname(b)}", c) for (a, b), c in trinket_combo.most_common(4)],
        "potions": {nm: f"{c}/{n} ({c/n*100:.0f}%)" for nm, c in pot_users.most_common()},
    }
    json.dump(out, open(DATA / "tmp_demo_deep.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"=== 악마 심층 (n={n}) ===")
    print(f"폭군창: 평균 {out['tyrant_window']['avg_duration_s']}초 × 전투당 {out['tyrant_window']['windows_per_fight']}회")
    print(f"  창 내 시전(회/창): " + " · ".join(f"{k} {v}" for k, v in out["tyrant_window"]["inside_casts_top"]))
    print(f"악마의 핵 최대스택 중앙 {out['demonic_core']['median_max_stack']} (관측 최대 {out['demonic_core']['max_seen']})")
    print("핵심기 분당:", " · ".join(f"{k} {v}" for k, v in out["key_casts_per_min"].items() if v > 0))
    print("\n장신구 단일 빈도:")
    for nm, c, pct in out["trinkets_top_single"]: print(f"  {nm:<28} {c}명 {pct}")
    print("장신구 조합:")
    for combo, c in out["trinkets_top_combo"]: print(f"  {combo}: {c}명")
    print("\n전투물약 채택:", out["potions"] or "(미검출)")
    print("\n저장: tmp_demo_deep.json")


if __name__ == "__main__":
    main()
