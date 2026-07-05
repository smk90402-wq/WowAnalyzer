# -*- coding: utf-8 -*-
"""사격 사냥꾼(MM) 어둠 순찰자 vs 파수꾼 정밀 분석 — 보스별 채택률 + 타겟 고정/쫄 분배 검증.

★데이터 가용성 사전 확인 결과(중요)★
  v2_cache_events.json 는 [ts, spellID, 'cast'] / [ts, spellID, type(, targetID)] 만 담는다.
  - cast 이벤트에 target GUID 가 전혀 없음 (102351/102351 캐스트 모두 3-튜플, 4번째 원소 0건).
  - damage(피해) 이벤트 자체가 캐시에 없음.
  - v2_cache_damage.json 은 '어빌리티별 총 피해' 표(guid=스킬ID)일 뿐 target 차원 없음.
  - report_meta.actors 는 아군 플레이어명→sourceID 만, 적(넴드/쫄) 액터/GUID 테이블 없음.
  => Q2(조준/검은화살 target GUID 분포·DoT 유지)·Q3(넴드 vs 쫄 피해 분배)는
     target GUID 실측이 원천적으로 불가. '미해결'로 판정하고, 캐스트로 가능한
     간접 프록시(연발 공격/검은 화살/조준 사격 캐스트율)만 보조로 제시한다.

가능한 것:
  Q1. 어둠 순찰자 vs 파수꾼 vs 무리의 지도자 보스별 채택률 — top20 vs 전체100.
      단일성격 보스 vs 다중대상(쫄) 보스 구분. '어둠 순찰자가 단일에서도 기용 시작' 판정.

입력(캐시만, API 없음):
  data/rankings_zone46_mythic_dps_top100.csv  (Hunter/Marksmanship 900행, 9보스×100)
  data/v2_cache_player_fight.json             (nodes → 영웅트리 판별)
  data/talent_trees.json                      ('Hunter/Marksmanship' hero 노드셋)
  scratchpad/mm_cd_events.json                (기존 추출분 — casts 프록시용)
출력: data/mm_darkranger_analysis.json
"""
from __future__ import annotations
import csv, json, sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path(r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze\data")
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")
OUT = DATA / "mm_darkranger_analysis.json"

BOSS_KR = {
    "3176": "아베르지안", "3177": "보라시우스", "3178": "바엘고어",
    "3179": "살라다르", "3180": "선봉대", "3181": "우주의 왕관",
    "3182": "벨로렌", "3183": "한밤의 도래(르우라)", "3306": "카이메루스",
}
BOSS_ORDER = ["3176", "3177", "3178", "3179", "3180", "3181", "3182", "3183", "3306"]
TOP_BAND = 20

# 스펠 ID (spell_db.json name_ko 로 확정)
AIMED = 19434       # 조준 사격
BLACK_ARROW = 466930  # 검은 화살 (어둠 순찰자 전용 소모기)
VOLLEY = 260243     # 연발 공격 (광역)
RAPID = 257044      # 속사 (후보; explore 시 확인)


def load_hero_sets():
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))["Hunter/Marksmanship"]
    return {t: set(int(nd["id"]) for nd in h["nodes"]) for t, h in tt["hero"].items()}


def detect_hero(nodes, hero_sets):
    if not nodes:
        return "불명"
    ns = set(int(x) for x in nodes)
    best = max(hero_sets, key=lambda t: len(ns & hero_sets[t]))
    return best if len(ns & hero_sets[best]) >= 8 else "불명"


def load_rows():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    return [r for r in rows if r["class"] == "Hunter" and r["spec"] == "Marksmanship"]


def build():
    hero_sets = load_hero_sets()
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    rows = load_rows()

    # 각 행에 hero 태깅 + player_fight key 매핑
    tagged = []
    unmatched = 0
    for r in rows:
        rid, fid, ch = r["report_id"], int(r["fight_id"]), r["character"]
        p = pf.get(f"{rid}:{fid}:{ch}")
        hero = "불명"
        if isinstance(p, dict):
            hero = detect_hero(p.get("nodes"), hero_sets)
        else:
            unmatched += 1
        tagged.append({
            "eid": r["encounter_id"], "boss": BOSS_KR.get(r["encounter_id"], r["encounter_name"]),
            "rank": int(r["rank"]), "char": ch, "hero": hero,
            "rid": rid, "fid": fid,
            "sid": p.get("sourceID") if isinstance(p, dict) else None,
        })

    # ── Q1: 보스별 채택률 (top20 vs 전체) ──────────────────────
    HEROES = ["어둠 순찰자", "파수꾼", "무리의 지도자", "불명"]

    def tally(items):
        c = Counter(t["hero"] for t in items)
        n = len(items)
        return {"n": n, **{h: c.get(h, 0) for h in HEROES if c.get(h, 0)},
                "어둠순찰자_pct": round(100 * c.get("어둠 순찰자", 0) / n, 1) if n else None,
                "파수꾼_pct": round(100 * c.get("파수꾼", 0) / n, 1) if n else None}

    per_boss = {}
    for eid in BOSS_ORDER:
        allb = [t for t in tagged if t["eid"] == eid]
        top = sorted(allb, key=lambda t: t["rank"])[:TOP_BAND]
        per_boss[BOSS_KR[eid]] = {
            "eid": eid,
            "top20": tally(top),
            "full100": tally(allb),
        }

    overall = {"top20_pooled": tally(sorted(tagged, key=lambda t: t["rank"])[: TOP_BAND * len(BOSS_ORDER)]),
               "full_pooled": tally(tagged)}
    # top20 pooled 를 보스별 top20 합집합으로 재정의(위는 rank 뒤섞임 방지 위해 보스별 top20 합산)
    top20_all = [t for eid in BOSS_ORDER for t in sorted([x for x in tagged if x["eid"] == eid], key=lambda x: x["rank"])[:TOP_BAND]]
    overall["top20_pooled"] = tally(top20_all)

    # ── 보스 단일/다중 성격 분류 (연발 공격 캐스트율 = 광역 프록시로 실측 보정) ──
    # 사전 라벨(도메인): 쫄/다중대상 알려진 보스 표기 후, 연발 공격 판당 캐스트로 검증.
    BOSS_ADDS_PRIOR = {
        "3176": ("다중/쫄", "임페라토르 아베르지안 — 소환 쫄 페이즈 존재"),
        "3177": ("단일", "보라시우스 — 사실상 순수 단일 성격"),
        "3178": ("다중/쫄", "바엘고어&에조라크 — 2대상 + 분열체"),
        "3179": ("다중/쫄", "살라다르 — 페이즈 쫄/무기 다중"),
        "3180": ("다중/쫄", "선봉대 — 다중 적 광역"),
        "3181": ("혼합", "우주의 왕관 — 별도 오브젝트/분산"),
        "3182": ("단일", "벨로렌 — 사실상 단일 집중"),
        "3183": ("혼합", "한밤의 도래(르우라) — 페이즈 전환/이동"),
        "3306": ("다중/쫄", "카이메루스 — 다두/쫄 성격"),
    }

    # ── 캐스트 프록시 (target GUID 부재를 대체하는 유일 신호) ──────
    proxy = {}
    proxy_totals = {}
    cache = SCRATCH / "mm_cd_events.json"
    ev = json.load(open(cache, encoding="utf-8")) if cache.exists() else {}
    # key = rid:fid:sid
    key_of = {}
    for t in tagged:
        if t["sid"] is not None:
            key_of[(t["rid"], t["fid"], t["sid"])] = t

    # 보스별·hero별 판당 캐스트율
    agg = defaultdict(lambda: defaultdict(lambda: {"fights": 0, "aimed": 0, "black": 0, "volley": 0, "dur": 0.0}))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    for k, e in ev.items():
        rid, fid, sid = k.split(":")
        tinfo = key_of.get((rid, int(fid), int(sid)))
        if not tinfo:
            continue
        # duration
        m = meta.get(rid)
        dur = None
        if m:
            f = next((x for x in (m.get("fights") or []) if x.get("id") == int(fid)), None)
            if f:
                dur = (f["endTime"] - f["startTime"]) / 1000
        casts = e.get("casts") or []
        na = sum(1 for c in casts if len(c) >= 2 and c[1] == AIMED)
        nb = sum(1 for c in casts if len(c) >= 2 and c[1] == BLACK_ARROW)
        nv = sum(1 for c in casts if len(c) >= 2 and c[1] == VOLLEY)
        slot = agg[tinfo["eid"]][tinfo["hero"]]
        slot["fights"] += 1
        slot["aimed"] += na
        slot["black"] += nb
        slot["volley"] += nv
        if dur:
            slot["dur"] += dur

    for eid in BOSS_ORDER:
        label, note = BOSS_ADDS_PRIOR[eid]
        entry = {"boss": BOSS_KR[eid], "prior_label": label, "prior_note": note, "by_hero": {}}
        for hero in ("어둠 순찰자", "파수꾼"):
            s = agg[eid].get(hero)
            if not s or s["fights"] == 0:
                continue
            mins = s["dur"] / 60 if s["dur"] else None
            entry["by_hero"][hero] = {
                "fights_with_events": s["fights"],
                "volley_per_min": round(s["volley"] / mins, 2) if mins else None,
                "black_arrow_per_min": round(s["black"] / mins, 2) if mins else None,
                "aimed_per_min": round(s["aimed"] / mins, 2) if mins else None,
            }
        proxy[BOSS_KR[eid]] = entry

    # hero별 전 보스 통합 캐스트율 (target 무관, GCD 배분 신호)
    for hero in ("어둠 순찰자", "파수꾼"):
        tot = {"fights": 0, "aimed": 0, "black": 0, "volley": 0, "dur": 0.0}
        for eid in BOSS_ORDER:
            s = agg[eid].get(hero)
            if not s:
                continue
            for kk in tot:
                tot[kk] += s[kk]
        mins = tot["dur"] / 60 if tot["dur"] else None
        proxy_totals[hero] = {
            "fights_with_events": tot["fights"],
            "volley_per_min": round(tot["volley"] / mins, 2) if mins else None,
            "black_arrow_per_min": round(tot["black"] / mins, 2) if mins else None,
            "aimed_per_min": round(tot["aimed"] / mins, 2) if mins else None,
        }

    # ── 판정: 어둠 순찰자 단일 기용 여부 ──────────────────────
    single_bosses = [eid for eid, (lbl, _) in BOSS_ADDS_PRIOR.items() if lbl == "단일"]
    verdict_single = {}
    for eid in single_bosses:
        b = per_boss[BOSS_KR[eid]]
        verdict_single[BOSS_KR[eid]] = {
            "top20_어둠순찰자_pct": b["top20"]["어둠순찰자_pct"],
            "full100_어둠순찰자_pct": b["full100"]["어둠순찰자_pct"],
        }

    result = {
        "_meta": {
            "date": "2026-07-05",
            "spec": "Hunter/Marksmanship (12.0.7)",
            "source": "rankings_zone46_mythic_dps_top100.csv (900 rows, 9 boss × 100)",
            "hero_detection": "player_fight nodes ∩ talent_trees hero node-set (>=8 overlap)",
            "unmatched_player_fight": unmatched,
            "DATA_LIMITATION": (
                "v2_cache_events.json 에는 damage 이벤트도, cast target GUID 도 없음"
                "(캐스트 102351건 전부 3-튜플). v2_cache_damage.json 은 어빌리티별 총피해 표로 "
                "target 차원 부재. 따라서 Q2(타겟전환 손해·조준/검은화살 target 분포·검은화살 DoT "
                "유지)와 Q3(넴드 vs 쫄 피해 분배)는 실측 불가 → '미해결'."
            ),
        },
        "Q1_hero_adoption": {
            "overall": overall,
            "per_boss": per_boss,
            "boss_character_PRIOR_unvalidated": {BOSS_KR[e]: BOSS_ADDS_PRIOR[e][0] for e in BOSS_ORDER},
            "boss_character_note": (
                "이 라벨은 도메인 사전지식이며 본 캐스트-only 캐시로는 검증 불가(연발 공격율이 "
                "보스 무관 균일). 단일/다중 판정 근거로 과신하지 말 것."),
            "single_target_bosses_darkranger_check": verdict_single,
        },
        "Q1_proxy_casts_per_min": {
            "note": ("target GUID 부재로 넴드/쫄 분리 불가. 아래는 판당 분당 캐스트율."),
            "finding_volley_not_discriminative": (
                "연발 공격(260243) 캐스트율이 모든 보스·양 영웅에서 1.0~1.2/min 로 거의 동일 "
                "(고정 ~45s 쿨을 쿨마다 소진). 따라서 연발 공격율로는 단일/다중 보스를 구분할 수 없다. "
                "위 boss_character 라벨은 이 데이터로 검증되지 않은 '외부/도메인 사전지식'이며, "
                "본 캐시(캐스트-only)로는 보스의 단일/다중 성격을 실측 검증할 수 없다."
            ),
            "finding_gcd_tradeoff": (
                "실측 가능한 유일한 확정 신호: 어둠 순찰자는 검은 화살(466930)에 GCD를 쓰느라 "
                "조준 사격 캐스트율이 낮고(약 17~21/min), 파수꾼은 검은 화살 0 + 조준 사격 "
                "높음(약 22~26/min). 검은 화살은 어둠 순찰자 전용(파수꾼 0.0/min 확인)."
            ),
            "by_hero_all_bosses": proxy_totals,
            "per_boss": proxy,
        },
        "Q2_target_switch_loss": {
            "verdict": "미해결 (UNRESOLVED)",
            "reason": ("조준 사격(19434)·검은 화살(466930) 캐스트에 target GUID 가 이벤트 캐시에 "
                       "존재하지 않음(0/102351). 한 대상 집중 vs 분산, 검은 화살 DoT 대상별 유지 패턴을 "
                       "실측할 방법이 현 캐시로 없음. 판정하려면 targetID 포함 damage/cast 이벤트 재수집 필요."),
        },
        "Q3_damage_split_boss_vs_adds": {
            "verdict": "미해결 (UNRESOLVED)",
            "reason": ("피해 이벤트 및 적(넴드/쫄) 액터 GUID 테이블이 캐시에 없음. per-target 피해 비중을 "
                       "산출할 소스가 전무. 판정하려면 target 포함 damage 이벤트 또는 타겟별 damage-done 표 필요."),
        },
    }
    return result


if __name__ == "__main__":
    res = build()
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    # 콘솔 요약
    print("=" * 70)
    print("Q1 어둠 순찰자 vs 파수꾼 보스별 채택률 (top20 / full100)")
    print("=" * 70)
    bc = res["Q1_hero_adoption"]["boss_character_PRIOR_unvalidated"]
    for boss, b in res["Q1_hero_adoption"]["per_boss"].items():
        t, f = b["top20"], b["full100"]
        print(f"\n[{boss}]  성격={bc[boss]}")
        print(f"  top20 : 어둠순찰자 {t.get('어둠 순찰자',0):>3} ({t['어둠순찰자_pct']}%)  |  파수꾼 {t.get('파수꾼',0):>3} ({t['파수꾼_pct']}%)  n={t['n']}")
        print(f"  full  : 어둠순찰자 {f.get('어둠 순찰자',0):>3} ({f['어둠순찰자_pct']}%)  |  파수꾼 {f.get('파수꾼',0):>3} ({f['파수꾼_pct']}%)  n={f['n']}")
    ov = res["Q1_hero_adoption"]["overall"]
    print("\n[전체 pooled]")
    print("  top20:", ov["top20_pooled"])
    print("  full :", ov["full_pooled"])
    print("\n단일 보스 어둠 순찰자 기용 체크:", json.dumps(res["Q1_hero_adoption"]["single_target_bosses_darkranger_check"], ensure_ascii=False))
    print("\nQ2:", res["Q2_target_switch_loss"]["verdict"])
    print("Q3:", res["Q3_damage_split_boss_vs_adds"]["verdict"])
    print("\n출력:", OUT)
