"""사격냥 어둠순찰자 — 대상별 딜 분배 실측.

가설(사용자): 머리 조준류 단일특화 때문에 DR은 쫄 안 치고 넴드만 친다.
검증: DR/파수꾼이 공존하는 보스에서 같은 보스 기준 빌드별 '보스 대상 딜 비중' 대조.
 + 보라시우스(DR 100%)는 대상 목록 자체로 단일 보스인지 확인.

방법: events(DamageDone, sourceID) → targetID 합산 → masterData actors 로 이름 매핑.
출력: data/tmp_mm_dr_targets.json + 콘솔 요약.
"""
from __future__ import annotations
import sys, time, json
from pathlib import Path
from collections import defaultdict
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import pandas as pd
from wcl_v2 import WCLV2

DATA = Path(__file__).parent / "data"
PER_GROUP = 8   # 보스×빌드당 표본

Q_DMG = """query($code:String!,$s:Float!,$e:Float!,$sid:Int!,$st:Float){reportData{report(code:$code){
  events(dataType:DamageDone,startTime:$s,endTime:$e,sourceID:$sid,startTime:$st,limit:10000){data nextPageTimestamp}
}}}"""
# startTime 중복 — 페이지네이션용 별도 변수 사용
Q_DMG = """query($code:String!,$s:Float!,$e:Float!,$sid:Int!){reportData{report(code:$code){
  events(dataType:DamageDone,startTime:$s,endTime:$e,sourceID:$sid,limit:10000){data nextPageTimestamp}
}}}"""

Q_ACTORS = """query($code:String!){reportData{report(code:$code){
  masterData{actors{id name type subType}}
}}}"""

_actor_cache: dict[str, dict] = {}


def actors_of(cli, rid):
    if rid not in _actor_cache:
        d = cli.query(Q_ACTORS, {"code": rid})
        arr = ((((d or {}).get("reportData") or {}).get("report") or {}).get("masterData") or {}).get("actors") or []
        _actor_cache[rid] = {a["id"]: (a.get("name"), a.get("type")) for a in arr}
    return _actor_cache[rid]


def damage_by_target(cli, rid, fid_window, sid):
    s, e = fid_window
    out: dict[int, int] = defaultdict(int)
    start = s
    for _ in range(6):   # 페이지 상한
        d = cli.query(Q_DMG, {"code": rid, "s": float(start), "e": float(e), "sid": int(sid)})
        ev = ((((d or {}).get("reportData") or {}).get("report") or {}).get("events") or {})
        for x in ev.get("data") or []:
            tid = x.get("targetID")
            amt = x.get("amount") or 0
            if tid is not None:
                out[tid] += amt
        nxt = ev.get("nextPageTimestamp")
        if not nxt:
            break
        start = nxt
        time.sleep(0.03)
    return out


def main():
    cli = WCLV2()
    d = pd.read_csv(DATA / "tmp_mm_builds.csv")
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))

    BOSSES = ["Vorasius", "Chimaerus, the Undreamt God", "Midnight Falls", "Fallen-King Salhadaar"]
    results = []
    for boss in BOSSES:
        for build in ("DR", "SEN"):
            g = d[(d.boss == boss) & (d.build == build)].sort_values("rank").head(PER_GROUP)
            for _, r in g.iterrows():
                p = pf.get(f'{r.rid}:{int(r.fid)}:{r.char}') or {}
                sid = p.get("sourceID")
                m = meta.get(r.rid) or {}
                f = next((x for x in (m.get("fights") or []) if x.get("id") == int(r.fid)), None)
                if sid is None or not f:
                    continue
                try:
                    dmg = damage_by_target(cli, r.rid, (f["startTime"], f["endTime"]), sid)
                    amap = actors_of(cli, r.rid)
                except Exception as ex:
                    print(f"  실패 {r.char}: {str(ex)[:50]}", flush=True)
                    time.sleep(30)
                    continue
                tot = sum(dmg.values()) or 1
                by_name: dict[str, float] = defaultdict(float)
                for tid, amt in dmg.items():
                    nm = (amap.get(tid) or ("?", "?"))[0]
                    by_name[nm] += amt
                top = sorted(by_name.items(), key=lambda x: -x[1])
                results.append({
                    "boss": boss, "build": build, "char": r.char, "rank": int(r["rank"]),
                    "total": tot,
                    "targets": [{"name": n, "pct": round(a / tot * 100, 1)} for n, a in top[:8]],
                })
                print(f"{boss[:18]:<18} {build} {r.char[:12]:<12} → " +
                      ", ".join(f'{t["name"]}({t["pct"]}%)' for t in results[-1]["targets"][:3]), flush=True)
                time.sleep(0.05)
    json.dump(results, open(DATA / "tmp_mm_dr_targets.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n저장: tmp_mm_dr_targets.json ({len(results)}명)")


if __name__ == "__main__":
    main()
