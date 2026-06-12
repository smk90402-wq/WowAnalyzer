"""검은 화살 사용창을 실제 보스 체력 기준으로 재계산 (시간 프록시 → 실측 HP).

WCL API 디스코드 발굴(emallson): events에 includeResources:true 주면 대상 HP가 실림.
보스 HP% 타임라인 → 80% 돌파/20% 돌파 시점 → 구간별 검은 화살 시전 빈도:
  자유A(HP≥80%) / 프록의존(20~80%) / 처형(≤20%)
기존 분석의 '오프닝 25초·막판 15% 시간' 프록시 검증 겸 대체.
출력: data/tmp_mm_hp_windows.json
"""
from __future__ import annotations
import sys, time, json, bisect
from pathlib import Path
from collections import defaultdict
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import pandas as pd
from wcl_v2 import WCLV2

DATA = Path(__file__).parent / "data"
BA = 466930
BOSS_NAME = {"Chimaerus, the Undreamt God": "Chimaerus", "Imperator Averzian": "Averzian", "Vorasius": "Vorasius"}

Q_DMG = """query($code:String!,$s:Float!,$e:Float!,$sid:Int!){reportData{report(code:$code){
  events(dataType:DamageDone,startTime:$s,endTime:$e,sourceID:$sid,limit:10000,includeResources:true){data nextPageTimestamp}
}}}"""
Q_ACTORS = """query($code:String!){reportData{report(code:$code){
  masterData{actors{id name}}
}}}"""
_actors: dict[str, dict] = {}


def actors_of(cli, rid):
    if rid not in _actors:
        d = cli.query(Q_ACTORS, {"code": rid})
        arr = ((((d or {}).get("reportData") or {}).get("report") or {}).get("masterData") or {}).get("actors") or []
        _actors[rid] = {a["id"]: a.get("name") or "?" for a in arr}
    return _actors[rid]


def hp_timeline(cli, rid, win, sid, bossnm):
    """플레이어의 보스 대상 피해 이벤트에서 (t, 보스HP%) 추출."""
    s, e = win
    out = []
    start = s
    amap = actors_of(cli, rid)
    for _ in range(6):
        d = cli.query(Q_DMG, {"code": rid, "s": float(start), "e": float(e), "sid": int(sid)})
        evd = ((((d or {}).get("reportData") or {}).get("report") or {}).get("events") or {})
        for x in evd.get("data") or []:
            if x.get("hitPoints") is None or not x.get("maxHitPoints"):
                continue
            if bossnm not in (amap.get(x.get("targetID")) or ""):
                continue
            out.append((x["timestamp"], x["hitPoints"] / x["maxHitPoints"] * 100))
        nxt = evd.get("nextPageTimestamp")
        if not nxt:
            break
        start = nxt
        time.sleep(0.03)
    return sorted(out)


def main():
    cli = WCLV2()
    d = pd.read_csv(DATA / "tmp_mm_builds.csv")
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    ev = json.load(open(DATA / "tmp_mm_events.json", encoding="utf-8"))

    samples = []
    for boss, n in [("Chimaerus, the Undreamt God", 10), ("Imperator Averzian", 8), ("Vorasius", 8)]:
        g = d[(d.boss == boss) & (d.build == "DR")].sort_values("rank")
        cnt = 0
        for _, r in g.iterrows():
            p = pf.get(f"{r.rid}:{int(r.fid)}:{r.char}")
            if not isinstance(p, dict) or p.get("sourceID") is None:
                continue
            if not ev.get(f"{r.rid}:{int(r.fid)}:{p['sourceID']}"):
                continue
            samples.append((boss, r, p["sourceID"]))
            cnt += 1
            if cnt >= n:
                break

    seg_casts = defaultdict(lambda: defaultdict(int))   # 보스 → 구간 → BA시전수
    seg_mins = defaultdict(lambda: defaultdict(float))
    t80s, t20s = [], []
    for boss, r, sid in samples:
        m = meta.get(r.rid) or {}
        f = next((x for x in (m.get("fights") or []) if x.get("id") == int(r.fid)), None)
        if not f:
            continue
        t0, t1 = f["startTime"], f["endTime"]
        try:
            tl = hp_timeline(cli, r.rid, (t0, t1), sid, BOSS_NAME[boss])
        except Exception as ex:
            print(f"  실패 {r.char}: {str(ex)[:50]}", flush=True)
            time.sleep(30)
            continue
        if len(tl) < 50:
            continue
        t80 = next((t for t, hp in tl if hp < 80), None)
        t20 = next((t for t, hp in tl if hp < 20), None)
        if t80:
            t80s.append((t80 - t0) / 1000)
        if t20:
            t20s.append((t1 - t20) / 1000)
        def seg(t):
            if t80 is None or t < t80: return "HP80이상"
            if t20 is None or t < t20: return "20~80(프록의존)"
            return "처형(20미만)"
        for tick in range(int(t0), int(t1), 1000):
            seg_mins[boss][seg(tick)] += 1 / 60
        e = ev.get(f"{r.rid}:{int(r.fid)}:{sid}") or {}
        for c in (e.get("casts") or []):
            if len(c) >= 3 and c[2] == "cast" and c[1] == BA:
                seg_casts[boss][seg(c[0])] += 1
        print(f"  {BOSS_NAME[boss]} {r.char[:10]:<10} 80%돌파 {((t80-t0)/1000 if t80 else -1):.0f}s · 20%돌파 잔여 {((t1-t20)/1000 if t20 else -1):.0f}s", flush=True)
        time.sleep(0.05)

    out = {}
    print(f"\n80% 돌파 시점 중앙 {pd.Series(t80s).median():.0f}초 (기존 프록시 25초) · 20% 돌파 후 잔여 중앙 {pd.Series(t20s).median():.0f}초 (기존 프록시 = 전투의 15%)")
    print(f"\n{'보스':<12} {'구간':<14} {'분':>6} {'BA/분':>6}")
    for boss in seg_casts:
        out[BOSS_NAME[boss]] = {}
        for seg_name in ("HP80이상", "20~80(프록의존)", "처형(20미만)"):
            mins = seg_mins[boss].get(seg_name, 0)
            if mins < 0.5:
                continue
            rate = seg_casts[boss].get(seg_name, 0) / mins
            out[BOSS_NAME[boss]][seg_name] = {"mins": round(mins, 1), "ba_per_min": round(rate, 1)}
            print(f"{BOSS_NAME[boss]:<12} {seg_name:<14} {mins:>6.1f} {rate:>6.1f}")
    json.dump(out, open(DATA / "tmp_mm_hp_windows.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n저장: tmp_mm_hp_windows.json")


if __name__ == "__main__":
    main()
