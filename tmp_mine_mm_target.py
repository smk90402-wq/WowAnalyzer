# -*- coding: utf-8 -*-
"""사격냥 어둠순찰자 vs 파수꾼 — 쫄 구간 대상별 피해 분배 실측.

질문:
 1. 쫄(다중대상) 보스에서 DR이 보스 집중형인가 분산형인가 (보스% vs 쫄%)
 2. 스킬별(마무리 53351·검은화살 466930·조준 19434·일제 257620)이 어디로 갔나
 3. (별도 스캔) 머리 조준 471363 실측 중첩

방법: table(dataType:DamageDone, sourceID) → entries[].targets[] {name,total,type}.
      type=Boss가 넴드, NPC=쫄. 대상별·스킬별 집계.

표본: DR add보스(키마이루스·아베르지안) + 파수꾼 add보스(선봉대·바엘고어)
      + split보스(아베르지안·살하다르)에서 DR/SEN 동일보스 A/B.
출력: data/mm_target_split.json (커밋 금지)
"""
import csv, json, sys, time
from pathlib import Path
from collections import defaultdict
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from wcl_v2 import WCLV2

ROOT = Path(__file__).parent
DATA = ROOT / "data"
PER_GROUP = 6   # 보스×빌드당 표본

# 관심 스킬 (기타는 합산)
KEY_ABIL = {
    53351:  "마무리사격",
    466930: "검은화살",
    19434:  "조준사격",
    257620: "일제사격",
    257044: "속사",
    212431: "폭발사격",
    186270: "예리한사격",   # Raptor? placeholder; resolved by name anyway
}

Q_TABLE = """query($code:String!,$s:Float!,$e:Float!,$sid:Int!){reportData{report(code:$code){
  table(dataType:DamageDone,startTime:$s,endTime:$e,sourceID:$sid)
}}}"""


def load_classified():
    tt = json.load(open(DATA/"talent_trees.json", encoding="utf-8"))
    hero_sets = {t: set(n["id"] for n in h["nodes"]) for t, h in tt["Hunter/Marksmanship"]["hero"].items()}
    rows = list(csv.DictReader(open(DATA/"rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    mm = [r for r in rows if r["class"]=="Hunter" and r["spec"].replace(" ","")=="Marksmanship"]
    pf = json.load(open(DATA/"v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA/"v2_cache_report_meta.json", encoding="utf-8"))
    out = []
    for r in mm:
        rid, fid, ch = r["report_id"], int(r["fight_id"]), r["character"]
        p = pf.get(f"{rid}:{fid}:{ch}")
        if not isinstance(p, dict): continue
        sid = p.get("sourceID"); m = meta.get(rid)
        if sid is None or not m: continue
        f = next((x for x in (m.get("fights") or []) if x.get("id")==fid), None)
        if not f: continue
        nodes = set(int(x) for x in (p.get("nodes") or []))
        best = max(hero_sets, key=lambda t: len(nodes & hero_sets[t]))
        hero = best if len(nodes & hero_sets[best]) >= 8 else "불명"
        out.append({"boss": r["encounter_name"], "rank": int(r["rank"]), "char": ch,
                    "rid": rid, "fid": fid, "sid": sid,
                    "t0": f["startTime"], "t1": f["endTime"],
                    "build": {"어둠 순찰자":"DR","파수꾼":"SEN"}.get(hero,"?")})
    return out


def target_split(cli, r):
    d = cli.query(Q_TABLE, {"code": r["rid"], "s": float(r["t0"]),
                            "e": float(r["t1"]), "sid": int(r["sid"])})
    tbl = d["reportData"]["report"]["table"]
    inner = tbl.get("data", tbl) if isinstance(tbl, dict) else tbl
    entries = inner.get("entries") or []
    # per target-type total, per ability->target-type, per target-name
    by_type = defaultdict(int)          # "Boss"/"NPC"/... -> dmg
    by_name = defaultdict(int)          # target name -> dmg
    name_type = {}                      # target name -> type
    abil_type = defaultdict(lambda: defaultdict(int))  # abil name -> type -> dmg
    total = 0
    for e in entries:
        aname = e.get("name") or f"#{e.get('guid')}"
        for t in (e.get("targets") or []):
            tn = t.get("name") or "?"; tt = t.get("type") or "?"; amt = t.get("total") or 0
            by_type[tt] += amt
            by_name[tn] += amt
            name_type[tn] = tt
            abil_type[aname][tt] += amt
            total += amt
    return {"total": total, "by_type": dict(by_type),
            "by_name": dict(sorted(by_name.items(), key=lambda x:-x[1])[:12]),
            "name_type": name_type,
            "abil_type": {a: dict(v) for a, v in abil_type.items()}}


def main():
    cli = WCLV2()
    allc = load_classified()
    # 표본 계획: (boss, build)
    plan = [
        ("Chimaerus, the Undreamt God", "DR"),
        ("Imperator Averzian", "DR"), ("Imperator Averzian", "SEN"),
        ("Fallen-King Salhadaar", "DR"), ("Fallen-King Salhadaar", "SEN"),
        ("Lightblinded Vanguard", "SEN"),
        ("Vaelgor & Ezzorak", "SEN"),
        ("Midnight Falls", "DR"),
    ]
    results = []
    for boss, build in plan:
        grp = sorted([c for c in allc if c["boss"]==boss and c["build"]==build],
                     key=lambda c: c["rank"])[:PER_GROUP]
        for r in grp:
            try:
                sp = target_split(cli, r)
            except Exception as ex:
                print(f"  실패 {boss[:14]} {build} {r['char'][:10]}: {str(ex)[:60]}", flush=True)
                time.sleep(20); continue
            tot = sp["total"] or 1
            bt = sp["by_type"]
            boss_pct = round(100 * bt.get("Boss", 0) / tot, 1)
            add_pct = round(100 * sum(v for k, v in bt.items() if k not in ("Boss","Player")) / tot, 1)
            results.append({"boss": boss, "build": build, "char": r["char"],
                            "rank": r["rank"], "dur_s": round((r["t1"]-r["t0"])/1000,1),
                            "total": tot, "boss_pct": boss_pct, "add_pct": add_pct,
                            "by_type": bt, "by_name": sp["by_name"],
                            "name_type": sp["name_type"], "abil_type": sp["abil_type"]})
            print(f"{boss[:16]:<16} {build:<3} {r['char'][:11]:<11} r{r['rank']:>3} "
                  f"보스 {boss_pct:>5}% 쫄 {add_pct:>5}% types={dict(bt)}", flush=True)
            time.sleep(0.05)
    json.dump(results, open(DATA/"mm_target_split.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n저장: data/mm_target_split.json ({len(results)}건)", flush=True)
    print("rate:", cli.points_left())


if __name__ == "__main__":
    main()
