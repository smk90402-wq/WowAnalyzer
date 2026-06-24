"""KR 막공 취업 시장 분석 — fetch_kr_pug_market.py 산출물 → kr_pug_market.json.

스펙별:
 - mythic_unique: KR 신화 9보스 유니크 캐릭 (자리를 실제로 얻은 사람)
 - heroic_pop:    KR 영웅 유니크 캐릭 (지원자 풀 — "영웅은 아무나 데려가거든")
 - employment:    mythic_unique / heroic_pop = 취업률 (TO 뚫는 비율)
 - slots_per_raid: 신화 킬 로스터 기준 공대당 평균 자리수 (TO 절대치)
 - p_present:     공대에 1명이라도 있을 확률
 - pug vs guild:  무길드(막공 프록시) 공대 vs 길드 공대 자리수 비교
클래스별: 공대당 총원 (탱힐 포함) — "팔라딘 1자리 룰" 검증.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from collections import Counter, defaultdict
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(__file__).parent / "data"

# CamelCase(WCL) → main.py PUG_WELCOME 키 (공백형)
CLS_NORM = {"DeathKnight": "Death Knight", "DemonHunter": "Demon Hunter"}
SPEC_NORM = {"BeastMastery": "Beast Mastery"}
KR_SPEC = {
    ("Mage", "Frost"): "냉법", ("Mage", "Fire"): "화염", ("Mage", "Arcane"): "비전",
    ("Hunter", "Beast Mastery"): "야수", ("Hunter", "Marksmanship"): "사격", ("Hunter", "Survival"): "생존",
    ("Demon Hunter", "Devourer"): "포식", ("Demon Hunter", "Havoc"): "파멸",
    ("Warlock", "Demonology"): "악마", ("Warlock", "Destruction"): "파괴", ("Warlock", "Affliction"): "고통",
    ("Priest", "Shadow"): "암흑", ("Druid", "Balance"): "조화", ("Druid", "Feral"): "야성",
    ("Evoker", "Devastation"): "황폐", ("Evoker", "Augmentation"): "증강",
    ("Death Knight", "Unholy"): "부정", ("Death Knight", "Frost"): "냉죽",
    ("Shaman", "Elemental"): "정술", ("Shaman", "Enhancement"): "고양",
    ("Monk", "Windwalker"): "풍운",
    ("Rogue", "Assassination"): "암살", ("Rogue", "Outlaw"): "무법", ("Rogue", "Subtlety"): "잠행",
    ("Paladin", "Retribution"): "징벌", ("Warrior", "Arms"): "무기", ("Warrior", "Fury"): "분노",
}


def norm(cls, spec):
    return CLS_NORM.get(cls, cls), SPEC_NORM.get(spec, spec)


def main():
    mythic = json.loads((DATA / "kr_mythic_rankings.json").read_text(encoding="utf-8"))
    heroic = json.loads((DATA / "kr_heroic_pop.json").read_text(encoding="utf-8"))
    rosters = json.loads((DATA / "v2_cache_kr_roster.json").read_text(encoding="utf-8"))

    # ── 1) 신화 유니크 캐릭 per spec ──
    myth_chars: dict[tuple, set] = defaultdict(set)
    for key, blk in mythic.items():
        if str(key).startswith("_"):
            continue
        for e in blk["entries"]:
            k = norm(e["class"], e["spec"])
            myth_chars[k].add(f'{e["name"]}@{e["server"]}')

    # ── 2) 영웅 풀 per spec (보스별 유니크 합집합 — 둘 다 깬 사람 중복 제거) ──
    hero_chars: dict[tuple, set] = defaultdict(set)
    hero_capped: dict[tuple, bool] = defaultdict(bool)
    for key, blk in heroic.items():
        if str(key).startswith("_"):
            continue
        eid, cn, sn = key.split("|")
        k = norm(cn, sn)
        hero_chars[k].update(blk["chars"])
        hero_capped[k] |= blk.get("capped", False)

    # ── 3) 로스터 → 공대당 자리수 ──
    valid = {k: v for k, v in rosters.items() if v}
    n_raids = len(valid)
    pug = {k: v for k, v in valid.items() if not v.get("guild")}
    gld = {k: v for k, v in valid.items() if v.get("guild")}

    def dps_count(rs):
        """roster 집합 → {speckey: [총자리수, 등장공대수]}"""
        slots: dict[tuple, int] = Counter()
        present: dict[tuple, int] = Counter()
        for r in rs.values():
            c = Counter(norm(p["class"], p["spec"]) for p in (r.get("dps") or []) if p.get("spec"))
            for k, n in c.items():
                slots[k] += n
                present[k] += 1
        return slots, present

    slots_all, present_all = dps_count(valid)
    slots_pug, _ = dps_count(pug)
    slots_gld, _ = dps_count(gld)

    # 클래스 총원 (탱힐 포함) — 팔라딘 1자리 룰 + "클래스 자체가 없으면 데려간다" 동학
    cls_total: dict[str, int] = Counter()
    cls_present: dict[str, int] = Counter()     # 공대에 ≥1명 있는 공대 수
    cls_filler: dict[str, Counter] = defaultdict(Counter)  # 클래스 슬롯을 차지한 스펙(역할 포함) 분포
    for r in valid.values():
        seen = Counter()
        for role in ("dps", "healers", "tanks"):
            for p in (r.get(role) or []):
                cn = CLS_NORM.get(p["class"], p["class"])
                if cn:
                    seen[cn] += 1
                    sp = SPEC_NORM.get(p.get("spec") or "?", p.get("spec") or "?")
                    cls_filler[cn][f"{sp}({role[0]})"] += 1
        for cn, n in seen.items():
            cls_total[cn] += n
            cls_present[cn] += 1

    # ── 통합 ──
    specs_out = []
    for k, kr in KR_SPEC.items():
        mu = len(myth_chars.get(k, ()))
        hp = len(hero_chars.get(k, ()))
        emp = round(mu / hp, 3) if hp else None
        spr = round(slots_all.get(k, 0) / n_raids, 2) if n_raids else None
        ppr = round(present_all.get(k, 0) / n_raids * 100) if n_raids else None
        s_pug = round(slots_pug.get(k, 0) / len(pug), 2) if pug else None
        s_gld = round(slots_gld.get(k, 0) / len(gld), 2) if gld else None
        specs_out.append({
            "class": k[0], "spec": k[1], "kr": kr,
            "mythic_unique": mu, "heroic_pop": hp,
            "heroic_capped": hero_capped.get(k, False),
            "employment": emp,                  # 취업률 = 신화/영웅
            "slots_per_raid": spr,              # 공대당 평균 자리수 (TO)
            "p_present_pct": ppr,               # 공대 채용 확률
            "slots_pug": s_pug, "slots_guild": s_gld,
        })
    specs_out.sort(key=lambda x: -(x["employment"] or 0))

    out = {
        "n_raids": n_raids, "n_pug": len(pug), "n_guild": len(gld),
        "class_per_raid": {c: round(n / n_raids, 2) for c, n in sorted(cls_total.items(), key=lambda x: -x[1])},
        # "클래스 자체가 없으면 데려간다" — 보유율 높을수록 그 클래스 1자리는 사실상 고정 TO
        "class_presence_pct": {c: round(cls_present[c] / n_raids * 100) for c in cls_total},
        # 그 클래스 슬롯을 누가 차지하는가 (d=딜 h=힐 t=탱) — 징벌 vs 홀팔/보팔 경쟁 가시화
        "class_filler": {c: dict(f.most_common(6)) for c, f in cls_filler.items()},
        "specs": specs_out,
        "note": "KR 12.0.5. employment=신화유니크/영웅유니크(우주의왕관+살라다르 합집합). "
                "로스터=신화 킬 보스당 150 표본. pug=업로더 무길드 (프록시).",
    }
    (DATA / "kr_pug_market.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"공대(킬 전투) {n_raids} = 무길드 {len(pug)} + 길드 {len(gld)}")
    print(f"\n클래스 공대당 총원(탱힐 포함): " + ", ".join(f"{c} {v}" for c, v in out["class_per_raid"].items()))
    print(f"클래스 보유율%: " + ", ".join(f"{c} {v}" for c, v in
          sorted(out["class_presence_pct"].items(), key=lambda x: -x[1])))
    for c in ("Paladin", "Shaman", "Warrior", "Monk", "Evoker"):
        if c in out["class_filler"]:
            print(f"  {c} 슬롯 점유: {out['class_filler'][c]}")
    print(f"\n{'스펙':<6} {'신화':>5} {'영웅풀':>6} {'취업률':>6} {'자리/공대':>8} {'채용%':>5} {'막공':>5} {'길드':>5}")
    for s in specs_out:
        print(f"{s['kr']:<6} {s['mythic_unique']:>5} {s['heroic_pop']:>6}{'+' if s['heroic_capped'] else ' '} "
              f"{s['employment'] if s['employment'] is not None else '-':>6} {s['slots_per_raid']:>8} "
              f"{s['p_present_pct']:>4}% {s['slots_pug'] if s['slots_pug'] is not None else '-':>5} "
              f"{s['slots_guild'] if s['slots_guild'] is not None else '-':>5}")


if __name__ == "__main__":
    main()
