"""3단계: 포효 맹수 사이클 — 격노 시점에 어떤 맹수(와이번/멧돼지/곰)가 나오나 (운빨 판정).

포효 pending aura 3종(471878/472324/472325)의 removebuff = 맹수 소환(살명에 소비).
ID→맹수 매핑은 상관으로: removebuff 직후 1.5s 내 471881(와이번의 울음소리) apply → 와이번,
472640(멧돼지 기수) apply → 멧돼지, 둘 다 아니면 곰.
"""
from __future__ import annotations
import json, sys, os
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
sys.path.insert(0, str(Path(__file__).parent))
from analyze_bm_addwave import load_wanted

TMP = Path(os.environ.get("BM_TMP", "/tmp"))
PEND = [471878, 472324, 472325]
WYV_CRY, BOAR_RIDER = 471881, 472640
BW = 19574

def main():
    w = load_wanted()
    ev = json.load(open(TMP / "bm_addwave_events.json", encoding="utf-8"))
    # ── 1) ID→맹수 매핑 (상관)
    corr = {p: Counter() for p in PEND}
    for k, info in w.items():
        e = ev.get(k)
        if not e: continue
        buffs = e.get("buffs") or []
        rm = {p: [b[0] for b in buffs if b[1] == p and b[2] == "removebuff"] for p in PEND}
        wyv = [b[0] for b in buffs if b[1] == WYV_CRY and "apply" in b[2]]
        boar = [b[0] for b in buffs if b[1] == BOAR_RIDER and "apply" in b[2]]
        for p in PEND:
            for t in rm[p]:
                if any(0 <= x - t <= 1500 for x in wyv): corr[p]["wyvern"] += 1
                elif any(0 <= x - t <= 3000 for x in boar): corr[p]["boar"] += 1
                else: corr[p]["other"] += 1
    print("매핑 상관:", {p: dict(c) for p, c in corr.items()})
    label = {}
    for p in PEND:
        c = corr[p]
        if c["wyvern"] > max(c["boar"], c["other"]): label[p] = "와이번"
        elif c["boar"] > c["other"]: label[p] = "멧돼지"
        else: label[p] = "곰"
    print("매핑:", label)

    # ── 2) BW 시점 소환 맹수 분포 (전체 BW vs 웨이브 BW)
    #     웨이브 BW = 그 BW 주변 ±8s 에 난타 2회 이상 (다타겟 상황 proxy)
    WT = 1264359
    all_bw, wave_bw = Counter(), Counter()
    dbl = 0; wave_n = 0
    for k, info in w.items():
        e = ev.get(k)
        if not e: continue
        t0 = info["t0"]
        casts = [c for c in e.get("casts", []) if len(c) >= 3 and c[2] == "cast"]
        bws = [c[0] for c in casts if c[1] == BW]
        wts = [c[0] for c in casts if c[1] == WT]
        buffs = e.get("buffs") or []
        rms = sorted((b[0], b[1]) for b in buffs if b[1] in PEND and b[2] == "removebuff")
        for bt in bws:
            consumed = [(t, p) for t, p in rms if 0 <= t - bt <= 5000]
            is_wave = sum(1 for x in wts if abs(x - bt) <= 8000) >= 2
            if consumed:
                beast = label[consumed[0][1]]
                all_bw[beast] += 1
                if is_wave:
                    wave_bw[beast] += 1; wave_n += 1
                    if len(consumed) >= 2: dbl += 1
            else:
                all_bw["(소비없음)"] += 1
                if is_wave: wave_bw["(소비없음)"] += 1; wave_n += 1
    tot = sum(all_bw.values())
    print(f"\n전체 BW(n={tot}) 직후 소환: ", {k: f"{v} ({v/tot*100:.0f}%)" for k, v in all_bw.most_common()})
    print(f"웨이브 BW(n={wave_n}) 직후 소환:", {k: f"{v} ({v/max(wave_n,1)*100:.0f}%)" for k, v in wave_bw.most_common()})
    print(f"웨이브 BW 중 5s 내 더블 소환(자연포효+격노포효): {dbl} ({dbl/max(wave_n,1)*100:.0f}%)")

if __name__ == "__main__":
    main()
