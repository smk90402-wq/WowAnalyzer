"""2단계: 쫄웨이브 대비 야격/쇄도발동 타이밍 실측 (top100 행동 = 정답지).

- 웨이브 탐지: 보스별 난타(1264359) 캐스트 풀링 → 1s 밀도 + 스무딩 → 피크 → 선행에지
- 플레이어별: BW캐스트/KC캐스트/쇄도버프(1258338,1258344 apply) 시각
- 지표: bw_off(웨이브 대비 격노), st_off(웨이브 대비 쇄도발동), hold(격노→쇄도발동 간격),
        쇄도 버프 지속분포(끊김 여부), 웨이브 다타겟 지속폭
"""
from __future__ import annotations
import json, sys, csv, os
from pathlib import Path
from collections import defaultdict
import numpy as np

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(__file__).parent / "data"
TMP = Path(os.environ.get("BM_TMP", "/tmp"))
WT, BW, KC = 1264359, 19574, 34026
ST_BANG, ST = 1258338, 1258344   # 쇄도! / 쇄도 버프
HOWL = 471877

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
        sid = p.get("sourceID"); m = meta.get(rid)
        if sid is None or not m: continue
        f = next((x for x in (m.get("fights") or []) if x.get("id") == fid), None)
        if not f: continue
        wanted[f"{rid}:{fid}:{sid}"] = {"boss": r["encounter_name"], "t0": f["startTime"], "t1": f["endTime"]}
    return wanted

def pairs(buffs, bid, t0):
    """apply→remove 페어 (s)."""
    evs = sorted((b[0], b[2]) for b in buffs if len(b) >= 3 and b[1] == bid)
    out, cur = [], None
    for ts, typ in evs:
        if "apply" in typ and "refresh" not in typ:
            cur = ts
        elif "remove" in typ and cur is not None:
            out.append(((cur - t0) / 1000, (ts - cur) / 1000)); cur = None
    return out  # [(start_s, dur_s)]

def main():
    wanted = load_wanted()
    ev = json.load(open(TMP / "bm_addwave_events.json", encoding="utf-8"))
    bybs = defaultdict(list)
    for k, info in wanted.items():
        if k in ev: bybs[info["boss"]].append((info, ev[k]))

    g_hold, g_dur_bang, g_dur_st = [], [], []
    for boss in ["Fallen-King Salhadaar", "Lightblinded Vanguard", "Chimaerus, the Undreamt God", "Imperator Averzian"]:
        lst = bybs.get(boss, [])
        if not lst: continue
        # ── 웨이브 탐지 (풀링 난타 밀도)
        allwt = []
        for info, e in lst:
            t0 = info["t0"]
            allwt += [(c[0]-t0)/1000 for c in e.get("casts", []) if len(c) >= 3 and c[2] == "cast" and c[1] == WT]
        if not allwt: continue
        T = int(max(allwt)) + 2
        dens = np.zeros(T)
        for t in allwt:
            if 0 <= t < T: dens[int(t)] += 1
        k = np.ones(7); sm = np.convolve(dens, k, "same")
        thr = max(3.0, 0.35 * sm.max())
        peaks = []
        for i in range(3, T - 3):
            if sm[i] >= thr and sm[i] == sm[i-3:i+4].max():
                if not peaks or i - peaks[-1] >= 20: peaks.append(i)
        # 선행 에지: 피크에서 뒤로, 밀도 15%까지
        waves = []
        for p in peaks:
            i = p
            while i > 0 and sm[i] > 0.15 * sm[p]: i -= 1
            waves.append(i + 1)
        print(f"\n===== {boss} (n={len(lst)}) 웨이브 시작(선행에지): {waves}")
        # ── 플레이어별 타이밍
        bw_off, st_off, holds, widths = [], [], [], []
        for info, e in lst:
            t0 = info["t0"]
            casts = [c for c in e.get("casts", []) if len(c) >= 3 and c[2] == "cast"]
            bws = sorted((c[0]-t0)/1000 for c in casts if c[1] == BW)
            wts = sorted((c[0]-t0)/1000 for c in casts if c[1] == WT)
            stp = pairs(e.get("buffs", []), ST_BANG, t0)
            g_dur_bang += [d for _, d in stp]
            g_dur_st += [d for _, d in pairs(e.get("buffs", []), ST, t0)]
            sts = [s for s, _ in stp]
            # hold: 각 쇄도발동 직전 BW
            for s in sts:
                prev = [b for b in bws if b <= s + 0.1]
                if prev: holds.append(s - prev[-1]); g_hold.append(s - prev[-1])
            for w in waves:
                cb = [b - w for b in bws if abs(b - w) <= 25]
                if cb: bw_off.append(min(cb, key=abs))
                cs = [s - w for s in sts if abs(s - w) <= 25]
                if cs: st_off.append(min(cs, key=abs))
                ww = [t for t in wts if w - 5 <= t <= w + 30]
                if len(ww) >= 2: widths.append(max(ww) - min(ww))
        def q(a):
            if not a: return "n=0"
            a = np.array(a); return f"n={len(a)} med={np.median(a):+.1f} [q25 {np.percentile(a,25):+.1f} ~ q75 {np.percentile(a,75):+.1f}]"
        print(f"  격노−웨이브 오프셋: {q(bw_off)}")
        print(f"  쇄도발동−웨이브 오프셋: {q(st_off)}")
        print(f"  격노→쇄도발동 hold: {q(holds)}")
        print(f"  웨이브 다타겟 지속폭(난타 span): {q(widths)}")
    def q2(a, lbl):
        a = np.array(a); print(f"{lbl}: n={len(a)} med={np.median(a):.2f} mean={a.mean():.2f} p10={np.percentile(a,10):.2f} p90={np.percentile(a,90):.2f}")
    print("\n===== 전역 (전보스)")
    q2(g_hold, "격노→쇄도발동 hold(s)")
    q2(g_dur_bang, "쇄도! (1258338) 버프지속(s)")
    q2(g_dur_st, "쇄도 (1258344) 버프지속(s)")

if __name__ == "__main__":
    main()
