"""스펙별 딜사이클 난이도 정량화 — cast 이벤트 기반.

사용자 정의 난이도 = "스킬 개수 적고 + proc 반응 단순할수록 쉬움".
3개 지표 (스펙별 백필된 캐릭들의 median):

  1. unique_spells : 한 전투에서 시전한 고유 스펠 수 (스킬 종류). 적을수록 쉬움.
  2. apm          : 분당 시전 횟수 (입력 빈도). 낮을수록 쉬움.
  3. bigram_entropy : 직전 스펠 → 다음 스펠 조건부 엔트로피(bits).
                     낮으면 고정 로테(예측 가능=쉬움), 높으면 proc 분기 많음(어려움).

난이도 종합 = 세 지표 정규화 평균 (높을수록 어려움 → ease = 1-difficulty).

입력 (백필 캐시):
  data/v2_cache_player_fight.json  (char→sourceID)
  data/v2_cache_events.json        (casts)
  data/v2_cache_report_meta.json   (fight window=시간)
  data/rankings_zone46_{label}_dps_top100.csv  (행→spec)

출력: data/rotation_difficulty.csv

CLI: python rotation_difficulty.py [label]   (mythic/heroic, 기본 mythic)
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

DATA = Path(__file__).parent / "data"
MIN_CASTS = 20          # 이보다 적게 시전한 로그는 제외 (불완전)
MIN_CHARS_PER_SPEC = 8  # 스펙당 최소 캐릭 수


def _load(name: str) -> dict:
    p = DATA / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


OFFGCD_GAP_MS = 700   # 같은 스펠이 이보다 빨리 반복되면 오프-GCD 연타로 보고 접음

def cast_metrics(casts: list, dur_min: float) -> tuple[int, float, float] | None:
    """(unique_spells, apm, bigram_entropy) — type=='cast' 만.

    apm 은 오프-GCD 스팸(같은 스펠 <700ms 반복)을 접어 실제 로테 페이스 반영.
    (포식 등 자동/프록성 1버튼 연타가 APM 부풀리는 것 방지.)
    unique/entropy 는 전체 시퀀스 사용 — 연타는 엔트로피 낮춰 '쉬움' 으로 정확히 반영.
    """
    ev = [(int(c[0]), int(c[1])) for c in casts
          if isinstance(c, list) and len(c) >= 3 and c[2] == "cast" and c[1]
          and isinstance(c[0], (int, float))]
    seq = [sid for _, sid in ev]
    if len(seq) < MIN_CASTS or dur_min <= 0:
        return None
    unique = len(set(seq))
    # 유효 시전 수: 같은 스펠이 OFFGCD_GAP_MS 안에 반복되면 1회로 병합
    eff = 0
    last_ts: dict[int, int] = {}
    for ts, sid in ev:
        if sid in last_ts and (ts - last_ts[sid]) < OFFGCD_GAP_MS:
            last_ts[sid] = ts
            continue
        eff += 1
        last_ts[sid] = ts
    apm = eff / dur_min
    # bigram 조건부 엔트로피: H = sum_a P(a) * H(next | a)
    trans: dict[int, Counter] = defaultdict(Counter)
    for a, b in zip(seq[:-1], seq[1:]):
        trans[a][b] += 1
    total_pairs = len(seq) - 1
    H = 0.0
    for a, nexts in trans.items():
        pa = sum(nexts.values()) / total_pairs
        tot_a = sum(nexts.values())
        ha = 0.0
        for b, c in nexts.items():
            p = c / tot_a
            ha -= p * math.log2(p)
        H += pa * ha
    return unique, apm, H


def main(label: str = "mythic") -> None:
    src = DATA / f"rankings_zone46_{label}_dps_top100.csv"
    if not src.exists():
        sys.exit(f"랭킹 CSV 없음: {src.name}")
    df = pd.read_csv(src)
    df = df[df["report_id"].notna() & df["fight_id"].notna()].copy()
    df["fid"] = df["fight_id"].astype(int)

    pfight = _load("v2_cache_player_fight.json")
    events = _load("v2_cache_events.json")
    meta = _load("v2_cache_report_meta.json")

    # 스펙별 메트릭 수집
    spec_rows: dict[tuple, list] = defaultdict(list)
    used = 0
    for _, r in df.iterrows():
        rid = str(r["report_id"]); fid = int(r["fid"]); char = str(r["character"])
        pf = pfight.get(f"{rid}:{fid}:{char}")
        if not isinstance(pf, dict):
            continue
        sid = pf.get("sourceID")
        if not isinstance(sid, int):
            continue
        ev = events.get(f"{rid}:{fid}:{sid}")
        if not isinstance(ev, dict):
            continue
        casts = ev.get("casts") or []
        # 전투 길이
        m = meta.get(rid) or {}
        f = next((x for x in (m.get("fights") or []) if x.get("id") == fid), None)
        if not f:
            continue
        dur_min = (f["endTime"] - f["startTime"]) / 60000.0
        res = cast_metrics(casts, dur_min)
        if res is None:
            continue
        spec_rows[(r["class"], r["spec"])].append(res)
        used += 1

    out = []
    for (cls, spec), vals in spec_rows.items():
        if len(vals) < MIN_CHARS_PER_SPEC:
            continue
        uq = pd.Series([v[0] for v in vals]).median()
        ap = pd.Series([v[1] for v in vals]).median()
        en = pd.Series([v[2] for v in vals]).median()
        out.append({"class": cls, "spec": spec, "n": len(vals),
                    "unique_spells": round(uq, 1), "apm": round(ap, 1),
                    "bigram_entropy": round(en, 3)})
    res = pd.DataFrame(out)
    if res.empty:
        print(f"백필된 cast 데이터 부족 — backfill 먼저. (used={used})")
        return

    # 정규화 → 난이도(높을수록 어려움) → ease
    for col in ["unique_spells", "apm", "bigram_entropy"]:
        lo, hi = res[col].min(), res[col].max()
        res[col + "_n"] = (res[col] - lo) / (hi - lo) if hi > lo else 0.0
    res["difficulty"] = res[["unique_spells_n", "apm_n", "bigram_entropy_n"]].mean(axis=1)
    res["ease"] = 1 - res["difficulty"]
    res = res.sort_values("ease", ascending=False)

    cols = ["class", "spec", "n", "unique_spells", "apm", "bigram_entropy",
            "difficulty", "ease"]
    print(f"=== 딜사이클 난이도 ({label}, 백필 {used} 로그) — ease 높을수록 쉬움 ===")
    show = res[cols].copy()
    show["difficulty"] = show["difficulty"].round(3)
    show["ease"] = show["ease"].round(3)
    print(show.to_string(index=False))

    outp = DATA / "rotation_difficulty.csv"
    res[cols].to_csv(outp, index=False, encoding="utf-8")
    print(f"\nsaved -> {outp.name}")

    try:
        from update_log import record
        record(action="rotation_difficulty",
               params={"label": label, "logs_used": used},
               result={"specs": len(res)},
               files=["data/rotation_difficulty.csv"])
    except Exception:
        pass


if __name__ == "__main__":
    lbl = sys.argv[1] if len(sys.argv) > 1 else "mythic"
    main(lbl)
