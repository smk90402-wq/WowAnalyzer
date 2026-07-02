"""조작난이도 종합 v2 — 로그 실측 + 구조 요인 결합 (2026-07-02).

v1(큐레이션 단독) 비판 반영:
 - 근딜/원딜 차이: APM 은 근딜=즉시시전 연타 편향 → **역할군 내부 정규화**로 교정,
   이동 민감도는 12.0.7 실측(보스별 근딜 불리 지수 × 스펙 반응 기울기)으로 산출.
 - 특임 여부: 면역/특수기 보유 스펙의 특임 배정 부담을 별도 축으로 (구조 큐레이션, 근거 명시).
 - 로그 데이터 종합: 천장 격차(top100 IQR·max/med), 대중 격차(rank401+/1401+ 낙폭),
   킬별 변동성(parse_consistency)을 12.0.7 스냅샷에서 직접 계산.

입력:
  data/rankings_1207_snapshot.json   (12.0.7 top100 med/max/iqr, p5/p15 밴드 — 3보스)
  data/rotation_difficulty.csv       (casts 기반 apm/버튼수/엔트로피 — 12.0.5 수집분)
  data/parse_consistency.csv         (보스별 CV)
출력:
  data/spec_difficulty_v2.json / 콘솔 표

한계(정직 고지):
 - 밴드 낙폭은 3보스(3179/3178/3183)만, 표본 부족 스펙은 중앙값 대체.
 - top100 IQR 은 인구가 적은 스펙일수록 커지는 경향(선택 효과) — pop_depth 컬럼 참고.
 - apm/버튼수는 12.0.5 casts 캐시 기준(12.0.7 재수집 전).
"""
from __future__ import annotations
import sys, json
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data"

KR = {("Death Knight","Frost"):"냉죽",("Death Knight","Unholy"):"부정",("Demon Hunter","Devourer"):"포식",
("Demon Hunter","Havoc"):"파멸",("Druid","Balance"):"조화",("Druid","Feral"):"야성",
("Evoker","Augmentation"):"증강",("Evoker","Devastation"):"황폐",("Hunter","Beast Mastery"):"야수",
("Hunter","Marksmanship"):"사격",("Hunter","Survival"):"생존",("Mage","Arcane"):"비전",
("Mage","Fire"):"화염",("Mage","Frost"):"냉법",("Monk","Windwalker"):"풍운",
("Paladin","Retribution"):"징벌",("Priest","Shadow"):"암흑",("Rogue","Assassination"):"암살",
("Rogue","Outlaw"):"무법",("Rogue","Subtlety"):"잠행",("Shaman","Elemental"):"정술",
("Shaman","Enhancement"):"고양",("Warlock","Affliction"):"고통",("Warlock","Demonology"):"악마",
("Warlock","Destruction"):"파괴",("Warrior","Arms"):"무기",("Warrior","Fury"):"분노"}

# 근딜/원딜 — 포식은 KR 구인글 자체 분류("원딜(포식,냥꾼)", "원딜2: 냥꾼 흑마 악사")를 근거로 원딜.
MELEE = {"냉죽","부정","파멸","야성","암살","무법","잠행","고양","풍운","징벌","무기","분노","생존"}

# 특임/유틸 부담 (0~1, 높을수록 조작 부담↑) — 구조 큐레이션. 근거를 노트로 명시.
# 기준: ①면역·특수기 보유로 1인 특임(폭탄/장판/단독처리) 배정 빈도 ②전투 중 아군 대상 유틸 시전 의무.
UTIL_DUTY = {
 "증강":(0.90,"외생버프 대상·타이밍 관리가 로테 자체(아군 시전 의무 최상)"),
 "냥꾼공통":(0.55,"거북 면역으로 폭탄/디버프 단독 처리 특임 단골"),
 "도적공통":(0.60,"망토 면역+연막·속행 아군 유틸, 기믹 스킵 특임 배정 잦음"),
 "법사공통":(0.45,"얼방 면역 특임+시간 왜곡 관리"),
 "징벌":(0.55,"무적 특임+희생/축복류 아군 시전 의무"),
 "죽기공통":(0.45,"그립·대마보 특임(쫄 정리 각 잡기)"),
 "흑마공통":(0.40,"관문 설치/힐스톤·소환 의무(전투 중 부담은 중간)"),
 "암흑":(0.40,"마력주입 대상 관리+구원"),
 "고양":(0.30,"윈드러시/뿌리 등 보조 유틸"),
 "정술":(0.30,"동일"),
 "조화":(0.35,"이니·해감·전투부활 판단"),
 "야성":(0.35,"동일+근접"),
 "포식":(0.25,"신생 스펙, 현재 특임 배정 관행 적음(메타/별 정렬만)"),
 "파멸":(0.25,"질주/유틸 부담 낮음"),
 "황폐":(0.30,"용의 숨결 각도 정도"),
 "풍운":(0.30,"기의 고치·질풍 보조"),
 "무기":(0.20,"함성 외 특임 드묾"), "분노":(0.20,"동일"),
 "냉법":(0.45,"법사공통"), "화염":(0.45,"법사공통"), "비전":(0.45,"법사공통"),
 "야수":(0.55,"냥꾼공통"), "사격":(0.55,"냥꾼공통"), "생존":(0.55,"냥꾼공통"),
 "암살":(0.60,"도적공통"), "무법":(0.60,"도적공통"), "잠행":(0.60,"도적공통"),
 "냉죽":(0.45,"죽기공통"), "부정":(0.45,"죽기공통"),
 "고통":(0.40,"흑마공통"), "악마":(0.40,"흑마공통"), "파괴":(0.40,"흑마공통"),
}

W = {"mech":0.30, "punish":0.20, "ceiling":0.15, "move":0.15, "variance":0.10, "duty":0.10}


def _norm(s: pd.Series, invert=False) -> pd.Series:
    lo, hi = s.min(), s.max()
    if hi <= lo: return pd.Series(0.5, index=s.index)
    n = (s - lo) / (hi - lo)
    return 1 - n if invert else n


def main() -> None:
    snap = json.loads((DATA / "rankings_1207_snapshot.json").read_text(encoding="utf-8"))
    rows = []
    for key, bosses in snap["top100"].items():
        c, s = key.split("|"); kr = KR[(c, s)]
        med = {int(b): v["med"] for b, v in bosses.items() if v["med"]}
        iqr = {int(b): v["iqr"] for b, v in bosses.items() if v["iqr"] is not None}
        mx  = {int(b): v["max"] for b, v in bosses.items() if v["max"]}
        rows.append({"class": c, "spec": s, "kr": kr, "melee": kr in MELEE,
                     "med": med, "iqr": iqr, "max": mx})
    df = pd.DataFrame(rows)
    bosses = sorted({b for m in df["med"] for b in m})

    # ── D. 이동 민감도: 보스별 근딜 불리 지수 × 스펙 상대성과 기울기 ──
    rel = pd.DataFrame({b: [r["med"].get(b, np.nan) for r in rows] for b in bosses},
                       index=df.index)
    rel = rel / rel.mean(axis=0)          # 보스 내 상대 성과
    hostility = {}
    for b in bosses:
        m = rel.loc[df["melee"], b].mean(); r_ = rel.loc[~df["melee"], b].mean()
        hostility[b] = r_ - m             # 클수록 근딜 불리 보스
    hx = pd.Series(hostility)
    print("보스별 근딜 불리 지수(+=근딜 불리):",
          {b: round(v, 3) for b, v in sorted(hostility.items(), key=lambda x: -x[1])})
    slopes = []
    for i in df.index:
        y = rel.loc[i, bosses]
        ok = y.notna()
        slopes.append(np.polyfit(hx[ok], y[ok], 1)[0] if ok.sum() >= 5 else np.nan)
    df["move_slope"] = slopes             # 음수 = 근딜불리 보스에서 같이 하락
    df["move_pen"] = _norm(pd.Series(slopes, index=df.index), invert=False)
    df["move_pen"] = 1 - df["move_pen"]   # 하락 클수록(기울기 음수) 페널티↑

    # ── B. 천장 격차: top100 내 IQR/med + (max-med)/med — 보스별 중앙값 ──
    df["iqr_ratio"] = [np.nanmedian([r["iqr"][b] / r["med"][b] for b in r["iqr"] if b in r["med"]]) for r in rows]
    df["head_room"] = [np.nanmedian([(r["max"][b] - r["med"][b]) / r["med"][b] for b in r["max"] if b in r["med"]]) for r in rows]
    df["ceiling"] = 0.5 * _norm(df["iqr_ratio"]) + 0.5 * _norm(df["head_room"])

    # ── C. 대중 격차(처벌성): 밴드 낙폭 1 - p15/p1 (없으면 p5), 3보스 평균 ──
    # 인구 꼬리 가드: 밴드가 그 스펙 인구의 '끝자락'이면 관전/사망 노이즈로 낙폭이 뻥튀기됨.
    # p15 는 n>=90 이고 med>=0.45*p1 일 때만, p5 는 해당 보스에 p15 가 존재(인구>=1400)할 때만 사용.
    punish = []
    for key in df["class"] + "|" + df["spec"]:
        b_ = snap["bands"].get(key, {})
        drops = []
        for boss in ("3179", "3178", "3183"):
            p1 = snap["top100"].get(key, {}).get(boss, {}).get("med")
            if not p1:
                continue
            p15o = b_.get(f"{boss}|p15", {}); p5o = b_.get(f"{boss}|p5", {})
            low = None
            if p15o.get("med") and p15o.get("n", 0) >= 90 and p15o["med"] >= 0.45 * p1:
                low = p15o["med"]
            elif p5o.get("med") and p15o.get("n", 0) >= 90 and p5o["med"] >= 0.45 * p1:
                low = p5o["med"]      # 인구 깊은 스펙만 p5 fallback
            if low:
                drops.append(1 - low / p1)
        punish.append(np.mean(drops) if drops else np.nan)
    df["band_drop"] = punish
    df["pop_depth"] = [sum(1 for k, v in snap["bands"].get(key, {}).items()
                           if k.endswith("p15") and v["n"] >= 90)
                      for key in df["class"] + "|" + df["spec"]]  # 0~3 (인구 깊이)
    df["punish"] = _norm(df["band_drop"].fillna(df["band_drop"].median()))

    # ── A. 기계적 부하: APM(역할군 내 정규화) + 버튼 수 ──
    rot = pd.read_csv(DATA / "rotation_difficulty.csv")[["class", "spec", "unique_spells", "apm", "bigram_entropy"]]
    df = df.merge(rot, on=["class", "spec"], how="left")
    apm_group = df.groupby("melee")["apm"].transform(lambda s: (s - s.min()) / (s.max() - s.min()))
    df["mech"] = 0.55 * apm_group + 0.45 * _norm(df["unique_spells"])

    # ── E. 킬별 변동성 ──
    con = pd.read_csv(DATA / "parse_consistency.csv")[["class", "spec", "avg_cv"]]
    df = df.merge(con, on=["class", "spec"], how="left")
    df["variance"] = _norm(df["avg_cv"].fillna(df["avg_cv"].median()))

    # ── G. 특임 부담 ──
    df["duty"] = df["kr"].map(lambda k: UTIL_DUTY.get(k, (0.3, ""))[0])
    df["duty_note"] = df["kr"].map(lambda k: UTIL_DUTY.get(k, (0.3, "기본"))[1])

    for col in ["mech", "punish", "ceiling", "move_pen", "variance"]:
        df[col] = df[col].fillna(df[col].median())
    df["difficulty"] = (W["mech"] * df["mech"] + W["punish"] * df["punish"]
                        + W["ceiling"] * df["ceiling"] + W["move"] * df["move_pen"]
                        + W["variance"] * df["variance"] + W["duty"] * df["duty"])
    df["ease_v2"] = 1 - df["difficulty"]
    df = df.sort_values("difficulty")

    show = df[["kr", "melee", "difficulty", "mech", "punish", "ceiling", "move_pen",
               "variance", "duty", "apm", "unique_spells", "band_drop", "pop_depth"]].copy()
    for c in show.columns:
        if show[c].dtype == float: show[c] = show[c].round(3)
    print(f"=== 조작난이도 종합 v2 (낮을수록 쉬움) — 가중치 {W} ===")
    print(show.to_string(index=False))

    out = {"_meta": {"date": "2026-07-02", "weights": W,
           "axes": {"mech": "APM(역할군내 정규화)+버튼수 [12.0.5 casts]",
                    "punish": "rank401+/1401+ 밴드 낙폭 [12.0.7, 3보스]",
                    "ceiling": "top100 IQR/med+(max-med)/med [12.0.7, 9보스]",
                    "move_pen": "보스 근딜불리지수×상대성과 기울기 [12.0.7 실측]",
                    "variance": "킬별 CV [parse_consistency]",
                    "duty": "특임/아군유틸 의무 [구조 큐레이션]"},
           "limits": "밴드 3보스·희소스펙 중앙값대체·IQR 인구선택효과(pop_depth 참조)·casts는 12.0.5"},           "rows": json.loads(df.drop(columns=["med", "iqr", "max"]).to_json(orient="records", force_ascii=False))}
    (DATA / "spec_difficulty_v2.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nsaved -> data/spec_difficulty_v2.json")

    try:
        from update_log import record
        record(action="analyze_spec_difficulty_v2", params={"weights": W},
               result={"specs": len(df), "easiest": df.iloc[0]["kr"], "hardest": df.iloc[-1]["kr"]},
               files=["data/spec_difficulty_v2.json"])
    except Exception:
        pass


if __name__ == "__main__":
    main()

