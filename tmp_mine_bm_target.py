# -*- coding: utf-8 -*-
"""야냥(BM) 쫄웨이브 보스 — 상위 파스(노PI 우선) 대상별 피해 분배 실측.

tmp_mine_mm_target.py 재사용판(스펙 필터 BM, 노PI 우선 top3).
보스: 살라다르·아베르지안·선봉대·바엘고어. 보스당 3로그 = 12 table 쿼리(소량).
출력: data/bm_target_split.json (커밋 금지)
"""
import csv, json, sys, time
from pathlib import Path
from collections import defaultdict
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from wcl_v2 import WCLV2

ROOT = Path(__file__).parent
DATA = ROOT / "data"
PER_BOSS = 3
BOSSES = ["Fallen-King Salhadaar", "Imperator Averzian",
          "Lightblinded Vanguard", "Vaelgor & Ezzorak"]

Q_TABLE = """query($code:String!,$s:Float!,$e:Float!,$sid:Int!){reportData{report(code:$code){
  table(dataType:DamageDone,startTime:$s,endTime:$e,sourceID:$sid)
}}}"""


def load_candidates():
    rows = list(csv.DictReader(open(DATA/"rankings_zone46_mythic_dps_top100_pi.csv", encoding="utf-8")))
    bm = [r for r in rows if r["class"]=="Hunter" and r["spec"]=="Beast Mastery"
          and r["encounter_name"] in BOSSES]
    pf = json.load(open(DATA/"v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA/"v2_cache_report_meta.json", encoding="utf-8"))
    out = []
    for r in bm:
        rid, fid, ch = r["report_id"], int(r["fight_id"]), r["character"]
        p = pf.get(f"{rid}:{fid}:{ch}")
        if not isinstance(p, dict): continue
        sid = p.get("sourceID"); m = meta.get(rid)
        if sid is None or not m: continue
        f = next((x for x in (m.get("fights") or []) if x.get("id")==fid), None)
        if not f: continue
        out.append({"boss": r["encounter_name"], "rank": int(r["rank"]),
                    "pi": r["pi_received"], "char": ch, "rid": rid, "fid": fid,
                    "sid": sid, "t0": f["startTime"], "t1": f["endTime"]})
    return out


def target_split(cli, r):
    d = cli.query(Q_TABLE, {"code": r["rid"], "s": float(r["t0"]),
                            "e": float(r["t1"]), "sid": int(r["sid"])})
    tbl = d["reportData"]["report"]["table"]
    inner = tbl.get("data", tbl) if isinstance(tbl, dict) else tbl
    entries = inner.get("entries") or []
    by_type = defaultdict(int)
    by_name = defaultdict(int)
    total = 0
    for e in entries:
        for t in (e.get("targets") or []):
            tn = t.get("name") or "?"; tt = t.get("type") or "?"; amt = t.get("total") or 0
            by_type[tt] += amt; by_name[tn] += amt; total += amt
    return {"total": total, "by_type": dict(by_type),
            "by_name": dict(sorted(by_name.items(), key=lambda x:-x[1])[:12])}


def main():
    cli = WCLV2()
    allc = load_candidates()
    results = []
    for boss in BOSSES:
        # 노PI 우선 top3, 부족하면 PI 로그로 채움
        nopi = sorted([c for c in allc if c["boss"]==boss and c["pi"]=="False"],
                      key=lambda c: c["rank"])
        rest = sorted([c for c in allc if c["boss"]==boss and c["pi"]!="False"],
                      key=lambda c: c["rank"])
        picks = (nopi + rest)[:PER_BOSS]
        for r in picks:
            try:
                sp = target_split(cli, r)
            except Exception as ex:
                print(f"  실패 {boss[:14]} {r['char'][:10]}: {str(ex)[:70]}", flush=True)
                time.sleep(20); continue
            tot = sp["total"] or 1
            bt = sp["by_type"]
            boss_pct = round(100 * bt.get("Boss", 0) / tot, 1)
            add_pct = round(100 * sum(v for k, v in bt.items()
                                      if k not in ("Boss", "Player")) / tot, 1)
            results.append({"boss": boss, "char": r["char"], "rank": r["rank"],
                            "pi": r["pi"], "dur_s": round((r["t1"]-r["t0"])/1000, 1),
                            "total": tot, "boss_pct": boss_pct, "add_pct": add_pct,
                            "by_type": bt, "by_name": sp["by_name"]})
            print(f"{boss[:16]:<16} {r['char'][:11]:<11} r{r['rank']:>3} PI={r['pi']:<5} "
                  f"{r['dur_s'] if 'dur_s' in r else round((r['t1']-r['t0'])/1000):>4}s "
                  f"보스 {boss_pct:>5}% 쫄 {add_pct:>5}%", flush=True)
            time.sleep(0.1)
    json.dump(results, open(DATA/"bm_target_split.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n저장: data/bm_target_split.json ({len(results)}건)", flush=True)
    print("rate:", cli.points_left())


if __name__ == "__main__":
    main()
