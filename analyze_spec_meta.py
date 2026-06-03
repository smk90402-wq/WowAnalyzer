"""4차원 종합 스펙 평가 — 쫄파이 메타 최적 딜러.

차원 (각 0~1 정규화, 높을수록 좋음):
  1. ease         : 딜사이클 쉬움 (rotation_difficulty.csv)  — 스킬수·APM·proc
  2. consistency  : 택틱 관대(격차 작음) (parse_consistency.csv) — 보스별 CV
  3. pi_indep     : 마력주입 독립 (pi_impact.csv) — |uplift| 작을수록
  4. cleave_parse : 쫄파이 파스 천장 (rankings) — 광딜 4보스 median DPS

종합 = 4차원 가중평균. 가중치 조정 가능 (사용자 우선순위).

입력 (앞 단계 산출물):
  data/rotation_difficulty.csv  (rotation_difficulty.py)
  data/parse_consistency.csv    (이미 생성)
  data/pi_impact.csv            (analyze_pi_impact.py)
  data/rankings_zone46_mythic_dps_top100.csv

출력: data/spec_meta_ranking.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd
import numpy as np

DATA = Path(__file__).parent / "data"
CLEAVE_BOSSES = {3178, 3183, 3180, 3181}  # 바엘고어/에조라크, 한밤의도래, 빛눈먼선봉대, 우주의왕관

# 가중치 (합 1) — **파스 % 관점**.
# WCL 파스는 전문화별 백분위 정규화 → raw DPS 천장(cleave_parse)은 파스력과 무관.
# 파스 잘 찍기 = 로테 쉬움(실수↓) + PI 독립 + consistency 위주.
W = {"ease": 0.45, "pi_indep": 0.35, "consistency": 0.20, "cleave_parse": 0.0}

# 딜사이클 "기본 로테" 난이도 — **최신 유튜브(12.0.5) 다중 크리에이터 종합** (로그
# APM/엔트로피는 근딜=즉시시전 편향 + 바쁨≠어려움으로 측정 불가 판명. 2026-06 리서치).
# 출처: YouTube Comeback Kids(Sky) "Easiest DPS/Ranged 난이도" + Bispril "5 easiest"
#   + Dal "easiest specs" + 멜리 fun 티어(난이도 코멘트) + aoeah/Method/Wowhead 교차.
# 핵심 교정(밸패 후 최신): 무기전사=다수 "가장 단순한 로테"(#26→11, aoeah는 성능 착각),
#   사격냥꾼=3버튼(#21→8), 화염=3버튼 슈퍼이지, 잠행=한밤서 오버심플(생각 제거),
#   야성=한밤서 스냅샷/피의발톱 제거로 단순화(#22→19, Vesp 자막 직접확인 "considerably
#   easier"). "기본 쉬움/최적화 어려움"(포식·데바스) 분리는 skill_ceiling 컬럼.
# ★Vesp 난이도 티어리스트 2영상 yt-dlp 자막 전스펙 정밀검증(2026-06):
#   암살 "so much easier·tier one"(24→17 대폭↑)·황폐 "very simple"(↑5)·정기 "rotation
#   perfect, easier"(↑13)·악마 "easier"(↑12)·화염 "로테쉽지만 reactive/fast-paced가
#   어렵게함"(4→18↓)·조화 "more complex going midnight"(↓22)·무법 "hardest, 과소평가
#   했었다"(25유지)·잠행/야성/무기/냉마 쉬움 재확인. ease_curated = 1 - (rank-1)/26.
ROTATION_RANK = {
    ("Hunter", "Beast Mastery"): 1,     ("Paladin", "Retribution"): 2,
    ("Warlock", "Destruction"): 3,      ("Mage", "Frost"): 4,
    ("Evoker", "Devastation"): 5,       ("Hunter", "Survival"): 6,
    ("Rogue", "Subtlety"): 7,           ("Hunter", "Marksmanship"): 8,
    ("Warrior", "Arms"): 9,             ("Warrior", "Fury"): 10,
    ("Death Knight", "Frost"): 11,      ("Warlock", "Demonology"): 12,
    ("Shaman", "Elemental"): 13,        ("Demon Hunter", "Devourer"): 14,
    ("Death Knight", "Unholy"): 15,     ("Shaman", "Enhancement"): 16,
    ("Rogue", "Assassination"): 17,     ("Mage", "Fire"): 18,
    ("Druid", "Feral"): 19,             ("Priest", "Shadow"): 20,
    ("Warlock", "Affliction"): 21,      ("Druid", "Balance"): 22,
    ("Demon Hunter", "Havoc"): 23,      ("Monk", "Windwalker"): 24,
    ("Rogue", "Outlaw"): 25,            ("Mage", "Arcane"): 26,
    ("Evoker", "Augmentation"): 27,
}

SPEC_KR = {
    "Frost": "냉기", "Unholy": "부정", "Devourer": "포식", "Havoc": "파멸",
    "Balance": "조화", "Feral": "야성", "Augmentation": "증강", "Devastation": "황폐",
    "Beast Mastery": "야수", "Marksmanship": "사격", "Survival": "생존",
    "Arcane": "비전", "Fire": "화염", "Windwalker": "풍운", "Retribution": "징벌",
    "Shadow": "암흑", "Assassination": "암살", "Outlaw": "무법", "Subtlety": "잠행",
    "Elemental": "정기", "Enhancement": "고양", "Affliction": "고통",
    "Demonology": "악마", "Destruction": "파괴", "Arms": "무기", "Fury": "분노",
}
CLASS_KR = {
    "Death Knight": "죽기", "Demon Hunter": "악딜", "Druid": "드루", "Evoker": "기원",
    "Hunter": "사냥", "Mage": "마법", "Monk": "수도", "Paladin": "성기",
    "Priest": "사제", "Rogue": "도적", "Shaman": "주술", "Warlock": "흑마", "Warrior": "전사",
}


def _norm(s: pd.Series, invert: bool = False) -> pd.Series:
    lo, hi = s.min(), s.max()
    if hi <= lo:
        return pd.Series(0.5, index=s.index)
    n = (s - lo) / (hi - lo)
    return 1 - n if invert else n


def main() -> None:
    # 1. cleave parse (랭킹에서 직접)
    df = pd.read_csv(DATA / "rankings_zone46_mythic_dps_top100.csv")
    df = df[df["dps"].notna() & (df["dps"] > 0)]
    cl = df[df["encounter_id"].isin(CLEAVE_BOSSES)]
    st = df[~df["encounter_id"].isin(CLEAVE_BOSSES)]
    cleave = cl.groupby(["class", "spec"])["dps"].median().reset_index()
    cleave.columns = ["class", "spec", "cleave_med"]
    st_med = st.groupby(["class", "spec"])["dps"].median().reset_index()
    st_med.columns = ["class", "spec", "st_med"]

    base = cleave.merge(st_med, on=["class", "spec"], how="left")
    # 광딜 프로필 = 쫄파이/단일 DPS 비율 (스펙 내부, 정규화 무관). 높을수록 다타겟 특화.
    # 참고용 — 파스엔 무관(정규화), 실전 기여도/레이드 적합 지표.
    base["aoe_ratio"] = base["cleave_med"] / base["st_med"]

    # 2. ease — 커뮤니티 큐레이션 난이도 (로그 기반 ease 는 폐기, 측정 불가 판명).
    #    ease = 1 - (rank-1)/26.  로그 메트릭(apm/엔트로피/스킬수)은 참고로 머지.
    base["rot_rank"] = base.apply(
        lambda r: ROTATION_RANK.get((r["class"], r["spec"])), axis=1)
    base["ease"] = base["rot_rank"].apply(
        lambda x: 1 - (x - 1) / 26 if pd.notna(x) else np.nan)
    rp = DATA / "rotation_difficulty.csv"
    if rp.exists():  # 로그 메트릭 참고용
        rot = pd.read_csv(rp)[["class", "spec", "unique_spells", "apm",
                               "bigram_entropy", "ease"]].rename(
            columns={"ease": "ease_log"})
        base = base.merge(rot, on=["class", "spec"], how="left")

    # 3. consistency
    cp = DATA / "parse_consistency.csv"
    if cp.exists():
        con = pd.read_csv(cp)[["class", "spec", "consistency"]]
        base = base.merge(con, on=["class", "spec"], how="left")
    else:
        base["consistency"] = np.nan

    # 4. pi independence
    pp = DATA / "pi_impact.csv"
    if pp.exists():
        pi = pd.read_csv(pp)[["class", "spec", "uplift_pct", "pi_rate_pct"]]
        base = base.merge(pi, on=["class", "spec"], how="left")
        base["pi_indep"] = _norm(base["uplift_pct"].abs(), invert=True)
    else:
        base["uplift_pct"] = np.nan
        base["pi_indep"] = np.nan

    # 정규화
    base["cleave_parse"] = _norm(base["cleave_med"])
    # ease, consistency 는 이미 0~1. 결측은 중앙값으로 (편향 회피)
    for col in ["ease", "consistency", "pi_indep"]:
        base[col + "_f"] = base[col].fillna(base[col].median())

    base["score"] = (
        W["ease"] * base["ease_f"]
        + W["consistency"] * base["consistency_f"]
        + W["pi_indep"] * base["pi_indep_f"]
        + W["cleave_parse"] * base["cleave_parse"]
    )
    base = base.sort_values("score", ascending=False)
    base["kr"] = base.apply(
        lambda r: f"{CLASS_KR.get(r['class'], r['class'])} {SPEC_KR.get(r['spec'], r['spec'])}",
        axis=1)

    cols = ["kr", "score", "ease", "consistency", "pi_indep", "cleave_parse",
            "cleave_med", "uplift_pct"]
    show = base[cols].copy()
    for c in ["score", "ease", "consistency", "pi_indep", "cleave_parse"]:
        show[c] = show[c].round(3)
    show["cleave_med"] = show["cleave_med"].round(0).astype("Int64")

    miss_ease = base["ease"].isna().sum()
    miss_pi = base["pi_indep"].isna().sum()
    print(f"=== 4차원 종합 (가중치 {W}) ===")
    print(f"(결측 중앙값 대체: ease {miss_ease}스펙, pi {miss_pi}스펙)\n")
    print(show.to_string(index=False))

    out = DATA / "spec_meta_ranking.csv"
    base.to_csv(out, index=False, encoding="utf-8")
    print(f"\nsaved -> {out.name}")

    try:
        from update_log import record
        record(action="analyze_spec_meta", params={"weights": W},
               result={"specs": len(base), "top": base.iloc[0]["kr"]},
               files=["data/spec_meta_ranking.csv"])
    except Exception:
        pass


if __name__ == "__main__":
    main()
