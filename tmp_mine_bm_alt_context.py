"""BM 살상 명령 연속시전(b2b)의 맥락 분석 — 어느 상황에서 나오나.

tmp_mine_bm_alternation.py 가 만든 스크래치 캐시(bm_alt_events.json) 재사용.
- 야수의 격노(15s)/야생의 부름(20s) 창 안 b2b 농축도
- 마구잡이 난타 ±10s(광 페이즈) 안 b2b 농축도
- KC 사이 필러 개수 분포(0/1/2/3+)
- 광/단일 구간별 필러 구성, 날카로운 사격 장기 방치 비율
결과를 data/bm_alternation.json 의 "context" 키로 병합 저장.
"""
from __future__ import annotations
import json, sys, csv, re
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze\data")
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")

KC = 34026; BARB = 217200; COBRA = 193455
WT_IDS = {1264359, 1264355}
BW = 19574; COTW = 359844
OFFGCD = {20572, 186257, 204526, 212382, 212396, 219199, 227723, 274738,
          304051, 1234768, 1236616, 1236998, 1253050, 1283817, 1283818}

BOSS_KO = {3176: "아베르지안", 3177: "보라시우스", 3178: "바엘고어", 3179: "살라다르",
           3180: "선봉대", 3181: "우주의왕관", 3182: "벨로렌", 3183: "한밤의도래(르우라)",
           3306: "카이메루스"}


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
        key = f"{rid}:{fid}:{sid}"
        if key in wanted: continue
        wanted[key] = {"boss": BOSS_KO.get(int(r["encounter_id"]), r["encounter_name"]),
                       "rank": int(r["rank"]), "t0": f["startTime"], "t1": f["endTime"]}
    return wanted


def main():
    wanted = load_wanted()
    ev = json.load(open(SCRATCH / "bm_alt_events.json", encoding="utf-8"))

    # 광기 툴팁에서 지속시간 확인
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    tip = (db.get("272790") or {}).get("tooltip_ko", "")
    m = re.findall(r"[0-9.]+초", re.sub(r"<[^>]+>", " ", tip))
    print(f"광기(272790) 툴팁의 초 단위 숫자: {m}")

    tot = Counter()   # 전체 전환 상황별
    b2b = Counter()   # b2b 전환 상황별
    fill_hist = Counter()
    b2b_gap = []
    boss_win = defaultdict(lambda: [0, 0, 0, 0])  # boss -> [b2b_in_burst, b2b, trans_in_burst, trans]
    fill_aoe, fill_st = Counter(), Counter()
    barb_gaps = []
    for k, e in ev.items():
        info = wanted.get(k)
        if not info: continue
        casts = sorted((c[0], c[1]) for c in e["casts"] if c[0] >= info["t0"] - 1000)
        gseq = [(t, i) for t, i in casts if i not in OFFGCD]
        kc_idx = [x for x, (t, i) in enumerate(gseq) if i == KC]
        if len(kc_idx) < 10: continue
        bw_ts = [t for t, i in casts if i == BW]
        cotw_ts = [t for t, i in casts if i == COTW]
        wt_ts = [t for t, i in casts if i in WT_IDS]
        bts = [t for t, i in gseq if i == BARB]
        barb_gaps += [(y - x) / 1000 for x, y in zip(bts, bts[1:])]

        def in_burst(t):
            return (any(0 <= (t - b) / 1000 <= 15 for b in bw_ts)
                    or any(0 <= (t - c) / 1000 <= 20 for c in cotw_ts))

        def in_aoe(t):
            return any(abs(t - w) / 1000 <= 10 for w in wt_ts)

        for a, b in zip(kc_idx, kc_idx[1:]):
            nfill = b - a - 1
            fill_hist[min(nfill, 5)] += 1
            t = gseq[b][0]
            burst = in_burst(t); aoe = in_aoe(t)
            tot["n"] += 1
            if burst: tot["burst"] += 1
            if aoe: tot["aoe"] += 1
            for x in range(a + 1, b):
                (fill_aoe if aoe else fill_st)[gseq[x][1]] += 1
            bw4 = boss_win[info["boss"]]
            bw4[3] += 1
            if burst: bw4[2] += 1
            if nfill == 0:
                b2b["n"] += 1
                if burst: b2b["burst"] += 1
                if aoe: b2b["aoe"] += 1
                b2b_gap.append((gseq[b][0] - gseq[a][0]) / 1000)
                bw4[1] += 1
                if burst: bw4[0] += 1

    print(f"\n전체 전환 {tot['n']}, b2b {b2b['n']} ({100*b2b['n']/tot['n']:.2f}%)")
    print(f"버스트 창(격노15s/야생부름20s) 안: 전체 전환의 {100*tot['burst']/tot['n']:.1f}% vs b2b의 {100*b2b['burst']/b2b['n']:.1f}%")
    print(f"광 페이즈(난타 ±10s) 안:        전체 전환의 {100*tot['aoe']/tot['n']:.1f}% vs b2b의 {100*b2b['aoe']/b2b['n']:.1f}%")
    g = sorted(b2b_gap)
    print(f"b2b 간격 중앙 {g[len(g)//2]:.2f}s (연타 확인)")
    n = tot["n"]
    print("\nKC 사이 필러 개수 분포: " + " ".join(f"{k}개:{100*v/n:.1f}%" for k, v in sorted(fill_hist.items())))
    print("\n보스별 b2b 중 버스트창 비율 / 전환 중 버스트창 비율:")
    for boss, (bb_in, bb, tr_in, tr) in sorted(boss_win.items(), key=lambda x: -(x[1][1] / max(1, x[1][3]))):
        if bb == 0:
            print(f"  {boss:14s} b2b 0건")
            continue
        print(f"  {boss:14s} b2b {bb:4d}건: 버스트 안 {100*bb_in/bb:5.1f}% (기저 {100*tr_in/tr:4.1f}%)")

    # ── bm_alternation.json 에 context 병합 ──
    def share(c, top=8):
        s = sum(c.values())
        out = {}
        for sid, cnt in c.most_common(top):
            nm = (db.get(str(sid)) or {}).get("name_ko") or f"spell{sid}"
            out[f"{nm}({sid})"] = round(100 * cnt / s, 2)
        return out

    barb_gaps.sort()
    nb = len(barb_gaps)
    import bisect
    context = {
        "b2b_gap_median_s": round(g[len(g)//2], 2),
        "window_share_pct": {
            "burst_bw15s_cotw20s": {"all_transitions": round(100*tot["burst"]/n, 1),
                                     "b2b": round(100*b2b["burst"]/b2b["n"], 1)},
            "aoe_wildthrash_pm10s": {"all_transitions": round(100*tot["aoe"]/n, 1),
                                      "b2b": round(100*b2b["aoe"]/b2b["n"], 1)},
        },
        "fillers_between_kc_hist_pct": {str(k) + ("+" if k == 5 else ""): round(100*v/n, 1)
                                         for k, v in sorted(fill_hist.items())},
        "filler_share_by_window_pct": {"aoe": share(fill_aoe), "single_target": share(fill_st)},
        "barbed_gap_gt_pct": {f">{th}s": round(100*(nb - bisect.bisect_right(barb_gaps, th))/nb, 2)
                               for th in (8, 10, 12, 15, 18)},
        "tooltip_facts": {
            "살상 명령": "기본 쿨 7.5초·집중 30, 우두머리 포식자(102368)로 2충전 — 표본 362/362 채택",
            "코브라 사격": "시전마다 살상 명령 쿨 1초 감소 (+날카로운 비늘: 날카 쿨 2초 감소)",
            "날카로운 사격": "재충전 18초·2충전, 12초 출혈(잔여 피해 합산=덮어써도 손실 없음), 8초간 집중 20 생성",
            "마구잡이 난타": "쿨 8초·집중 35, 2타겟 이상이면 +200% 피해",
        },
        "frenzy_note": "광기(272790) 버프 이벤트가 apply 위주로만 캐시됨(2623 apply/16 remove, 스택 이벤트 0) → 유지율 계산 불가. 날카 시전 간격을 대리 지표로 사용.",
    }
    path = DATA / "bm_alternation.json"
    d = json.load(open(path, encoding="utf-8"))
    d["context"] = context
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\ncontext 병합 저장: data/bm_alternation.json")


if __name__ == "__main__":
    main()
