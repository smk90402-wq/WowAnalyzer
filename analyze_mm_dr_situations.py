"""사격냥 어둠 순찰자 — 상황별 딜사이클 실측 (오프닝 / 쫄딜 / 평시 / 막판).

구간 정의:
 - 오프닝: 전투 시작 ~25초
 - 쫄딜: 비보스 NPC에게 피해를 입힌 시점 ±4초 윈도우 (데미지 이벤트 타임라인 기반)
 - 막판: 전투 마지막 15% (처형 구간 프록시 — 보스 체력 직접 측정 아님, 추정 라벨)
 - 평시: 나머지

표본: 키마이루스 DR 10 + 아베르지안 DR 8 + 보라시우스 윈드러너형 8 + 키마이루스 파수꾼 8(대조).
데미지 이벤트(타임스탬프+대상)는 WCL events API 신규 페치, 캐스트는 tmp_mm_events.json 재사용.
출력: data/tmp_mm_situations.json + 콘솔.
"""
from __future__ import annotations
import sys, time, json, bisect
from pathlib import Path
from collections import Counter, defaultdict
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import pandas as pd
from wcl_v2 import WCLV2

DATA = Path(__file__).parent / "data"
WINDRUNNER = 103952
BOSS_NAME = {"Chimaerus, the Undreamt God": "Chimaerus", "Imperator Averzian": "Averzian",
             "Vorasius": "Vorasius"}

Q_DMG = """query($code:String!,$s:Float!,$e:Float!,$sid:Int!){reportData{report(code:$code){
  events(dataType:DamageDone,startTime:$s,endTime:$e,sourceID:$sid,limit:10000){data nextPageTimestamp}
}}}"""
Q_ACTORS = """query($code:String!){reportData{report(code:$code){
  masterData{actors{id name type}}
}}}"""

_actors: dict[str, dict] = {}


def actors_of(cli, rid):
    if rid not in _actors:
        d = cli.query(Q_ACTORS, {"code": rid})
        arr = ((((d or {}).get("reportData") or {}).get("report") or {}).get("masterData") or {}).get("actors") or []
        _actors[rid] = {a["id"]: (a.get("name"), a.get("type")) for a in arr}
    return _actors[rid]


def fetch_damage_timeline(cli, rid, win, sid):
    s, e = win
    out = []
    start = s
    for _ in range(6):
        d = cli.query(Q_DMG, {"code": rid, "s": float(start), "e": float(e), "sid": int(sid)})
        evd = ((((d or {}).get("reportData") or {}).get("report") or {}).get("events") or {})
        for x in evd.get("data") or []:
            if x.get("targetID") is not None:
                out.append((x["timestamp"], x["targetID"]))
        nxt = evd.get("nextPageTimestamp")
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
    ev = json.load(open(DATA / "tmp_mm_events.json", encoding="utf-8"))
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    name = lambda sid_: (db.get(str(sid_)) or {}).get("name_ko") or f"#{sid_}"

    # 표본 선정
    samples = []
    def pick(boss, build, n, windrunner=None):
        g = d[(d.boss == boss) & (d.build == build)].sort_values("rank")
        out = []
        for _, r in g.iterrows():
            p = pf.get(f"{r.rid}:{int(r.fid)}:{r.char}")
            if not isinstance(p, dict) or p.get("sourceID") is None:
                continue
            if windrunner is not None and ((WINDRUNNER in set(p.get("nodes") or [])) != windrunner):
                continue
            if not ev.get(f"{r.rid}:{int(r.fid)}:{p['sourceID']}"):
                continue
            out.append((r, p["sourceID"]))
            if len(out) >= n:
                break
        samples.extend([(boss, build, r, sid) for r, sid in out])
    pick("Chimaerus, the Undreamt God", "DR", 10)
    pick("Imperator Averzian", "DR", 8)
    pick("Vorasius", "DR", 8, windrunner=True)
    pick("Chimaerus, the Undreamt God", "SEN", 8)

    # 구간별 캐스트 집계: {그룹: {구간: Counter}}, 구간별 누적시간(분)
    agg = defaultdict(lambda: defaultdict(Counter))
    dur = defaultdict(lambda: defaultdict(float))
    for boss, build, r, sid in samples:
        m = meta.get(r.rid) or {}
        f = next((x for x in (m.get("fights") or []) if x.get("id") == int(r.fid)), None)
        if not f:
            continue
        t0, t1 = f["startTime"], f["endTime"]
        try:
            dmg = fetch_damage_timeline(cli, r.rid, (t0, t1), sid)
            amap = actors_of(cli, r.rid)
        except Exception as ex:
            print(f"  실패 {r.char}: {str(ex)[:50]}", flush=True)
            time.sleep(30)
            continue
        bossnm = BOSS_NAME[boss]
        # 비보스 피해 시각 목록 (정렬)
        add_hits = sorted(t for t, tid in dmg
                          if bossnm not in ((amap.get(tid) or ("?",))[0] or "?"))
        e = ev.get(f"{r.rid}:{int(r.fid)}:{sid}") or {}
        casts = [c for c in (e.get("casts") or []) if len(c) >= 3 and c[2] == "cast"]
        grp = f"{BOSS_NAME[boss]}-{build}" + ("(윈드러너)" if build == "DR" and boss == "Vorasius" else "")

        def segment(t):
            if t - t0 <= 25000:
                return "오프닝"
            i = bisect.bisect_left(add_hits, t)
            near = (i < len(add_hits) and add_hits[i] - t <= 4000) or (i > 0 and t - add_hits[i-1] <= 4000)
            if near:
                return "쫄딜"
            if t >= t1 - (t1 - t0) * 0.15:
                return "막판"
            return "평시"

        # 구간 시간 계산: 1초 그리드 스캔
        for tick in range(int(t0), int(t1), 1000):
            dur[grp][segment(tick)] += 1 / 60
        for c in casts:
            agg[grp][segment(c[0])][c[1]] += 1
        print(f"  {grp} {r.char[:10]:<10} 쫄히트 {len(add_hits)}", flush=True)
        time.sleep(0.05)

    out = {}
    for grp, segs in agg.items():
        out[grp] = {}
        print(f"\n===== {grp} — 구간별 분당 시전 =====")
        for seg in ("오프닝", "쫄딜", "평시", "막판"):
            cnt = segs.get(seg) or Counter()
            mins = dur[grp].get(seg, 0)
            if mins < 0.5:
                continue
            top = [(name(s), round(c / mins, 1)) for s, c in cnt.most_common(8)]
            out[grp][seg] = {"mins": round(mins, 1), "casts_per_min": top}
            print(f"[{seg}] ({mins:.1f}분) " + " · ".join(f"{n} {v}" for n, v in top))
    json.dump(out, open(DATA / "tmp_mm_situations.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n저장: tmp_mm_situations.json")


if __name__ == "__main__":
    main()
