"""4단계: 웨이브 격노 전후 글쿨 시퀀스 — 난타/날사/살명 순서 실측.

웨이브 BW(±8s 내 난타 2회 이상) 기준으로 BW-6s~+6s 캐스트 순서를 까서:
  - BW 직전 1·2번째 캐스트 분포 (난타가 먼저인가)
  - BW 직후 1·2번째 캐스트 분포 (살명이 바로인가, 난타가 끼는가)
  - BW-6~0s 내 날카로운 사격 횟수 (디버프 선작업 실태)
  - 첫 살명(=쇄도 발동) 지연
"""
from __future__ import annotations
import json, sys, os
from pathlib import Path
from collections import Counter
import statistics as st

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
sys.path.insert(0, str(Path(__file__).parent))
from analyze_bm_addwave import load_wanted

TMP = Path(os.environ.get("BM_TMP", "/tmp"))
WT, BW, KC, BARB, COBRA = 1264359, 19574, 34026, 217200, 193455
DB = json.load(open(Path(__file__).parent / "data" / "spell_db.json", encoding="utf-8"))
NOISE = {20572, 33702, 33697, 1236616, 109215, 118922, 781, 186257, 186258, 264735}
def nm(s):
    return DB.get(str(s), {}).get("name_ko") or f"#{s}"

def main():
    w = load_wanted()
    ev = json.load(open(TMP / "bm_addwave_events.json", encoding="utf-8"))
    prev1, prev2, next1, next2 = Counter(), Counter(), Counter(), Counter()
    barb_pre, wt_pre, wt_post, kc_delay = [], 0, 0, []
    nwave = 0
    for k, info in w.items():
        e = ev.get(k)
        if not e: continue
        t0 = info["t0"]
        casts = sorted((c[0], c[1]) for c in e.get("casts", [])
                       if len(c) >= 3 and c[2] == "cast" and c[1] not in NOISE)
        # 750ms 접기 (오프GCD 노이즈)
        seq = []
        for t, a in casts:
            if seq and t - seq[-1][0] < 750 and a == seq[-1][1]: continue
            seq.append((t, a))
        wts = [t for t, a in seq if a == WT]
        for i, (t, a) in enumerate(seq):
            if a != BW: continue
            if sum(1 for x in wts if abs(x - t) <= 8000) < 2: continue  # 웨이브 BW만
            nwave += 1
            win_pre = [(x, b) for x, b in seq if t - 6000 <= x < t and b != BW]
            win_post = [(x, b) for x, b in seq if t < x <= t + 6000 and b != BW]
            if win_pre:
                prev1[nm(win_pre[-1][1])] += 1
                if len(win_pre) >= 2: prev2[nm(win_pre[-2][1])] += 1
            if win_post:
                next1[nm(win_post[0][1])] += 1
                if len(win_post) >= 2: next2[nm(win_post[1][1])] += 1
            barb_pre.append(sum(1 for _, b in win_pre if b == BARB))
            if any(b == WT for _, b in win_pre): wt_pre += 1
            if any(b == WT for _, b in win_post): wt_post += 1
            kcs = [x for x, b in win_post if b == KC]
            if kcs: kc_delay.append((kcs[0] - t) / 1000)
    print(f"웨이브 BW 표본: {nwave}")
    print(f"\nBW 직전 캐스트:  {prev1.most_common(6)}")
    print(f"BW 전전 캐스트:  {prev2.most_common(6)}")
    print(f"BW 직후 캐스트:  {next1.most_common(6)}")
    print(f"BW 후후 캐스트:  {next2.most_common(6)}")
    print(f"\nBW-6s 내 날카로운 사격 횟수 분포: {Counter(barb_pre).most_common()}")
    print(f"난타 위치: BW 전 6s 내 {wt_pre}/{nwave} ({wt_pre/nwave*100:.0f}%) vs BW 후 6s 내 {wt_post}/{nwave} ({wt_post/nwave*100:.0f}%)")
    print(f"BW→첫 살상명령: med {st.median(kc_delay):.2f}s (n={len(kc_delay)})")

if __name__ == "__main__":
    main()
