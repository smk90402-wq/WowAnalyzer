# -*- coding: utf-8 -*-
"""야냥(BM) vs 격냥(MM) — 노PI 전제 보스별 배정 분석.

입력(전부 로컬):
 - data/rankings_zone46_mythic_dps_top100_pi.csv  (오늘자, pi_received)
 - data/bm_parse100_gap.json / mm_parse100_gap.json (킬타임·다운타임)
 - data/mm_talent_splits.json (MM 영웅특성 per_boss)
 - data/bm_target_split.json / mm_target_split.json (WCL 대상별 실측)
출력: data/hunter_nopi_assignment.json (커밋 금지)
"""
import csv, json, sys
from pathlib import Path
from statistics import median
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(__file__).parent / "data"

KO = {
    "Imperator Averzian": "아베르지안",
    "Vorasius": "보라시우스",
    "Vaelgor & Ezzorak": "바엘고어",
    "Fallen-King Salhadaar": "살라다르",
    "Lightblinded Vanguard": "선봉대",
    "Crown of the Cosmos": "우주의 왕관",
    "Belo'ren, Child of Al'ar": "벨로렌",
    "Midnight Falls": "한밤의 도래(르우라)",
    "Chimaerus, the Undreamt God": "카이메루스",
}
BOSS_ORDER = list(KO)


def pi_stats(rows):
    """top20/top100 PI 비율, 노PI 최고 등수, top20 내 노PI 수, DPS 격차."""
    rows = sorted(rows, key=lambda r: int(r["rank"]))
    def rate(sub):
        known = [r for r in sub if r["pi_received"] in ("True", "False")]
        if not known: return None
        return round(100 * sum(r["pi_received"] == "True" for r in known) / len(known))
    top20 = [r for r in rows if int(r["rank"]) <= 20]
    nopi = [r for r in rows if r["pi_received"] == "False"]
    best = nopi[0] if nopi else None
    r1_dps = float(rows[0]["dps"]) if rows else None
    return {
        "top20_pi_rate": rate(top20),
        "top100_pi_rate": rate(rows),
        "best_nopi_rank": int(best["rank"]) if best else None,
        "best_nopi_dps_vs_rank1_pct": (round(100 * float(best["dps"]) / r1_dps, 1)
                                       if best and r1_dps else None),
        "nopi_in_top20": sum(1 for r in top20 if r["pi_received"] == "False"),
        "nopi_in_top20_known": sum(1 for r in top20 if r["pi_received"] in ("True", "False")),
    }


def killtime_note(kt):
    if not kt: return None
    d = kt.get("rank1_5_vs_all_diff_pct")
    slow = kt.get("rank1_10_slower_than_med_pct")
    base = f"상위1-5 킬 {kt['rank1_5_med_s']}s vs 전체중앙 {kt['all100_med_s']}s ({d:+}%)"
    if d is not None and d >= 15:
        return base + f" — 긴 킬 유리(상위10 중 {slow}%가 중앙보다 느림)"
    if d is not None and d <= -8:
        return base + " — 빠른 컷 전제"
    return base + " — 킬타임 중립"


def main():
    rows = list(csv.DictReader(open(DATA/"rankings_zone46_mythic_dps_top100_pi.csv",
                                    encoding="utf-8")))
    bm_gap = json.load(open(DATA/"bm_parse100_gap.json", encoding="utf-8"))
    mm_gap = json.load(open(DATA/"mm_parse100_gap.json", encoding="utf-8"))
    mm_hero = json.load(open(DATA/"mm_talent_splits.json", encoding="utf-8"))["hero_tree"]["per_boss"]
    bm_ts = json.load(open(DATA/"bm_target_split.json", encoding="utf-8"))
    mm_ts = json.load(open(DATA/"mm_target_split.json", encoding="utf-8"))
    mm_means = mm_ts["_verdict"]["boss_build_means"]

    out = {"_meta": {
        "date": "2026-07-05",
        "premise": "PI(마력 주입) 불가 공대 전제. 목표=파스 99~100 안정 달성.",
        "sources": ["rankings_zone46_mythic_dps_top100_pi.csv",
                    "bm/mm_parse100_gap.json", "mm_talent_splits.json",
                    "bm_target_split.json(WCL 실측 12로그)", "mm_target_split.json(기존 48로그)"],
        "vanguard_note": "선봉대는 3넴드 의회형 — 대상 전원 type=Boss라 쫄 패딩 개념 없음(상시 3타겟 클리브)."
    }}

    for eng in BOSS_ORDER:
        ko = KO[eng]
        brow = [r for r in rows if r["class"]=="Hunter" and r["spec"]=="Beast Mastery"
                and r["encounter_name"]==eng]
        mrow = [r for r in rows if r["class"]=="Hunter" and r["spec"]=="Marksmanship"
                and r["encounter_name"]==eng]
        bm = pi_stats(brow)
        mm = pi_stats(mrow)

        bkt = bm_gap["per_boss"].get(eng, {})
        mkt = mm_gap["per_boss"].get(eng, {})
        bm["killtime_note"] = killtime_note(bkt.get("killtime"))
        mm["killtime_note"] = killtime_note(mkt.get("killtime"))
        b15 = bkt.get("rank_1_5") or {}
        m15 = mkt.get("rank_1_5") or {}
        bm["downtime_s_per_min_r1_5"] = b15.get("downtime_s_per_min_med")
        mm["downtime_s_per_min_r1_5"] = m15.get("downtime_s_per_min_med")
        mm["hero"] = mm_hero.get(ko)

        # 쫄 패딩 실측
        ap = None
        bm_logs = [r for r in bm_ts if r["boss"] == eng]
        if bm_logs:
            bm_boss = round(median(r["boss_pct"] for r in bm_logs), 1)
            mm_keys = [k for k in mm_means if k.startswith(eng + "|")]
            mm_part = {k.split("|")[1]: mm_means[k]["boss_pct"] for k in mm_keys}
            ap = {
                "bm_boss_pct_med": bm_boss,
                "bm_add_pct_med": round(100 - bm_boss, 1),
                "bm_logs": [{"rank": r["rank"], "pi": r["pi"], "dur_s": r["dur_s"],
                             "boss_pct": r["boss_pct"]} for r in bm_logs],
                "mm_boss_pct_mean_by_hero": mm_part or None,
            }
        entry = {"bm": bm, "mm": mm}
        if ap: entry["add_padding"] = ap
        out[ko] = entry

    # 보스별 실측 기반 판정 주석(데이터 요약 수준, 추천은 보고서에서)
    out["살라다르"]["add_padding"]["판정"] = (
        "확인됨: BM 노PI 1·2·4위 전부 320s+ 긴 킬이고 쫄딜 46~64% — 100점은 쫄 패딩에서 온다. "
        "MM도 파수꾼이 쫄딜 32.5%로 어순(19.4%)보다 분산형.")
    out["아베르지안"]["add_padding"]["판정"] = (
        "쫄딜 35~49% — 상위 파스 절반 가까이가 쫄 패딩. MM 어순 37.6%/파수꾼 43.6%로 둘 다 패딩형.")
    out["바엘고어"]["add_padding"]["판정"] = (
        "BM 상위 노PI 쫄딜 57~63%(공허구슬 단일 최대 타겟) — 패딩 의존 최상. MM 파수꾼도 34.7%.")
    out["선봉대"]["add_padding"]["판정"] = (
        "쫄 패딩 아님 — 3넴드 전원 Boss 타입 상시 클리브. 분배 좋은 스펙이 유리한 구조.")

    # 보스별 추천 (노PI 전제, 목표=99~100 파스 안정)
    RECO = {
        "아베르지안": {"추천": "야냥", "확신": "높음", "근거":
            "양쪽 다 노PI 1위 실존(top20 PI 21%/25%)이지만 MM은 빠른 컷 전제(-14%)·다운타임 13.8s/min, BM은 킬타임 중립·완전 이동딜. 쫄딜 44%로 BM 패딩도 잘 됨."},
        "보라시우스": {"추천": "어순 격냥", "확신": "낮음(애매)", "근거":
            "둘 다 top20 PI 55~60%로 PI 의존 최악 보스. 노PI 천장은 MM(4위·1위 dps의 99%)이 BM(10위·95.7%)보다 좋음. MM 영웅은 어순 100%. 어느 쪽이든 노PI 99+는 이 보스가 제일 어려움."},
        "바엘고어": {"추천": "야냥(→못 가면 파수꾼 격냥)", "확신": "중간", "근거":
            "BM 노PI 1위 실존, top20 노PI 12/20 vs MM 8/20(PI 60%). BM 상위 노PI가 쫄딜 57~63%(공허구슬 패딩) — 패딩 접근성 좋음. MM 가면 파수꾼 97%가 표준."},
        "살라다르": {"추천": "야냥", "확신": "높음(단, 킬타임 조건부)", "근거":
            "BM 노PI 1·2·4위 전부 320s+ 긴 킬 & 쫄딜 46~64% — 100점이 쫄 패딩에서 옴을 실측 확인. 공대가 쫄 웨이브를 오래 보는 킬이면 BM 확정. 빠른 컷(200s)이면 BM 100점 불가·MM(빠른컷 전제)로 전환 고려."},
        "선봉대": {"추천": "야냥", "확신": "높음", "근거":
            "MM top20 PI 79%로 사실상 PI 필수(노PI 최고 8위·94.2%). BM은 top20 PI 25%·노PI 1위 실존. 3넴드 상시 클리브 + BM 이동딜(다운타임 1.7 vs MM 17.6s/min)."},
        "우주의 왕관": {"추천": "야냥(근소)", "확신": "낮음(애매)", "근거":
            "BM 노PI 4위(97.4%)·킬타임 중립 vs MM 노PI 3위(94.6%)·빠른컷 전제(-10%). top20 PI율 42% vs 35%로 비슷. 차이 작음 — 편한 쪽."},
        "벨로렌": {"추천": "야냥(근소) / 느린 공대면 파수꾼 격냥", "확신": "낮음(애매)", "근거":
            "BM top20 노PI 15/19로 노PI 천장 우위지만 빠른 컷 전제(-12%). MM은 킬타임 중립·파수꾼 96% 표준이나 top20 PI 40%·다운타임 18s/min(무빙 보스에서 캐스팅 손해)."},
        "한밤의 도래(르우라)": {"추천": "어순 격냥", "확신": "중간", "근거":
            "BM top20 PI 65%로 전 보스 중 BM PI 의존 최고(노PI 최고 5위·top20 노PI 7/20). MM은 PI 40%·노PI 2위(96.5%)·어순 94% 표준. 노PI 제약에서 MM이 명확히 유리."},
        "카이메루스": {"추천": "야냥(근소) 또는 어순 격냥", "확신": "낮음(둘 다 됨)", "근거":
            "145s 단기 폭딜전. BM 노PI 1위, MM 노PI 2위(99.0%) — 둘 다 노PI 천장 뚫려 있음. MM 어순 93% 표준. 본캐 숙련도로 결정해도 됨."},
    }
    for ko, r in RECO.items():
        out[ko]["추천"] = r

    json.dump(out, open(DATA/"hunter_nopi_assignment.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # 콘솔 요약
    hdr = f"{'보스':<12} {'BM t20PI%':>9} {'BM 노PI최고':>9} {'BM t20노PI':>9} | {'MM t20PI%':>9} {'MM 노PI최고':>9} {'MM t20노PI':>9}  MM영웅"
    print(hdr)
    for eng in BOSS_ORDER:
        ko = KO[eng]; e = out[ko]
        b, m = e["bm"], e["mm"]
        hero = max(m["hero"], key=m["hero"].get) if m.get("hero") else "?"
        print(f"{ko:<12} {b['top20_pi_rate']!s:>9} r{b['best_nopi_rank']!s:>8} {b['nopi_in_top20']:>4}/{b['nopi_in_top20_known']:<4} | "
              f"{m['top20_pi_rate']!s:>9} r{m['best_nopi_rank']!s:>8} {m['nopi_in_top20']:>4}/{m['nopi_in_top20_known']:<4}  {hero} {m['hero'].get(max(m['hero'],key=m['hero'].get))}%")
    print("\n저장: data/hunter_nopi_assignment.json")


if __name__ == "__main__":
    main()
