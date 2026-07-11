# -*- coding: utf-8 -*-
"""고통 흑마 procprio용 이벤트 추출 — v2_cache_events.json(1.4GB) raw_decode 증분 스캔.

오늘자 rankings_zone46_mythic_dps_top100.csv 의 Warlock/Affliction 킬을
(report,fight,sourceID)로 매칭해 casts/buffs 전체를 스크래치패드 aff_pp_events.json 으로,
킬 메타(보스/등수/전투창/특성 노드 기반 빌드 마커)를 aff_pp_meta.json 으로 떨굼.

빌드 마커 (data/aff_talent_splits.json 확정):
  단일빌드  = 109865 자비우스의 계략 / 109852 치명적인 메아리 (상호 with_rate ≈100%)
  씨앗광빌드 = 109854 씨앗 뿌리기 / 109853 최초 감염자 / 109866 파괴의 씨앗
  (두 계열은 swap_relations 상 상호배타 — 둘 다면 '혼합', 둘 다 아니면 '기타')

패턴: tmp_mine_aff_extract.py / tmp_mine_aff_cd.py stream_filter 를 따름. 읽기 전용.
"""
from __future__ import annotations
import json, sys, csv
from pathlib import Path
from collections import Counter

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(__file__).parent / "data"
SCRATCH = Path(r"C:\Users\MKSEORTV\AppData\Local\Temp\claude"
               r"\C--Users-MKSEORTV-Desktop-WowAnalyzer"
               r"\30b0abb8-5226-4b13-9c1c-14e4a1562211\scratchpad")
SCRATCH.mkdir(parents=True, exist_ok=True)
OUT = SCRATCH / "aff_pp_events.json"
META_OUT = SCRATCH / "aff_pp_meta.json"

BOSS_KO = {3176: "아베르지안", 3177: "보라시우스", 3178: "바엘고어",
           3179: "살라다르", 3180: "선봉대", 3181: "우주의 왕관",
           3182: "벨로렌", 3183: "한밤의 도래(르우라)", 3306: "카이메루스"}

ST_MARKERS = {109865, 109852}          # 자비우스의 계략 / 치명적인 메아리
SEED_MARKERS = {109854, 109853, 109866}  # 씨앗 뿌리기 / 최초 감염자 / 파괴의 씨앗
SI_NODE = 109857                        # 조각의 불안정성


def build_of(nodes: set[int]) -> str:
    st = bool(nodes & ST_MARKERS)
    seed = bool(nodes & SEED_MARKERS)
    if st and not seed: return "단일"
    if seed and not st:
        # 씨앗 마커 + 조각의 불안정성 병행 = 카이메루스 위주 소수 변형(순수 씨앗광과 분리)
        return "씨앗_조각불안정_변형" if SI_NODE in nodes else "씨앗광"
    if st and seed: return "혼합"
    return "기타"


AFF_ID_NODES = {72034, 72047, 109862}  # 암흑시선 소환 / 일몰 / 불안정한 고통 — 고통 전문화 unanimous 노드


def load_wanted():
    """오늘자 CSV의 (report,fight,char) 키가 pf 캐시(7-05 백필분)와 어긋나 있어(교집합 0),
    pf 캐시 자체에서 고통 전문화 노드(AFF_ID_NODES >=2)로 고통 킬을 식별.
    보스/전투창은 report_meta의 encounterID/startTime/endTime, 등수는 오늘자 CSV에
    (캐릭터,보스) 매칭될 때만 부여(없으면 None)."""
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    rank_by = {}
    for r in rows:
        if r["class"] == "Warlock" and r["spec"] == "Affliction":
            rank_by.setdefault((r["character"], int(r["encounter_id"])), int(r["rank"]))
    wanted = {}
    for k, p in pf.items():
        if not isinstance(p, dict): continue
        nodes = set(int(x) for x in (p.get("nodes") or []))
        if len(nodes & AFF_ID_NODES) < 2: continue
        rid, fid_s, ch = k.split(":", 2)
        fid = int(fid_s)
        sid = p.get("sourceID")
        m = meta.get(rid)
        if sid is None or not m: continue
        f = next((x for x in (m.get("fights") or []) if x.get("id") == fid), None)
        if not f: continue
        key = f"{rid}:{fid}:{sid}"
        if key in wanted: continue
        eid = int(f.get("encounterID") or 0)
        wanted[key] = {
            "boss": BOSS_KO.get(eid, str(eid)),
            "rank": rank_by.get((ch, eid)), "char": ch,
            "t0": f["startTime"], "t1": f["endTime"],
            "build": build_of(nodes),
            "grip_node": 109858 in nodes,   # 재앙의 손아귀
        }
    return wanted


def main():
    wanted = load_wanted()
    print(f"aff player-fights wanted: {len(wanted)}", flush=True)
    print("builds:", Counter(w["build"] for w in wanted.values()), flush=True)
    json.dump(wanted, open(META_OUT, "w", encoding="utf-8"), ensure_ascii=False)

    if OUT.exists():
        out = json.load(open(OUT, encoding="utf-8"))
        print(f"기존 캐시 재사용: {len(out)}킬", flush=True)
        return

    s = open(DATA / "v2_cache_events.json", encoding="utf-8").read()
    print(f"events 캐시 {len(s)/1e6:.0f}MB 스캔...", flush=True)
    dec = json.JSONDecoder()
    out, i, n, seen = {}, 1, len(s), 0
    while i < n:
        while i < n and s[i] in " \t\r\n,": i += 1
        if i >= n or s[i] == "}": break
        key, j = dec.raw_decode(s, i); i = j
        while s[i] in " \t\r\n:": i += 1
        val, j = dec.raw_decode(s, i); i = j
        seen += 1
        if seen % 2000 == 0: print(f"  스캔 {seen}, 적중 {len(out)}", flush=True)
        if key in wanted:
            out[key] = {"casts": val.get("casts") or [], "buffs": val.get("buffs") or []}
    del s
    json.dump(out, open(OUT, "w", encoding="utf-8"))
    print(f"추출 {len(out)}/{len(wanted)} → {OUT}", flush=True)
    hit_builds = Counter(wanted[k]["build"] for k in out)
    print("적중 빌드 분포:", hit_builds, flush=True)


if __name__ == "__main__":
    main()
