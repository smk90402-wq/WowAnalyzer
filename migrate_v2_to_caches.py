"""V2 캐시 → V1 형식 캐시로 머지.

기존 analyze/classify 스크립트와 GUI 가 V1 캐시 키 구조를 그대로 읽으니까,
V2 페치 결과를 같은 구조로 변환해서 머지한다.

V2 캐시 (입력):
  - data/v2_cache_report_meta.json   : {rid: {fights:[{id,startTime,endTime,...}], actors:{name:sourceID}}}
  - data/v2_cache_player_fight.json  : {"rid:fid:char": {talents:[], gear:[], sourceID:int}}
  - data/v2_cache_events.json        : {"rid:fid:sid": {casts:[[ts,gid,t],...], buffs:[[ts,gid,t],...]}}

V1 형식 캐시 (출력, 머지 — 기존 데이터 유지):
  - data/cache_fights.json           : {rid: {"fid": [start,end]}}
  - data/cache_source_ids.json       : {rid: {char_name: source_id}}
  - data/cache_talents.json          : {"rid:fid": {char_name: [talent_ids]}}
  - data/cache_gear.json             : {"rid:fid": {char_name: {ilvl, gear:[...]}}}
  - data/cache_casts.json            : {"rid:fid:sid": [[ts,gid,t], ...]}
  - data/cache_buffs.json            : {"rid:fid:sid": [[ts,gid,t,stack?], ...]}
"""
from __future__ import annotations
import json, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path(__file__).parent / "data"


def lj(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def sj(p: Path, obj) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    meta_v2   = lj(DATA / "v2_cache_report_meta.json")
    pf_v2     = lj(DATA / "v2_cache_player_fight.json")
    ev_v2     = lj(DATA / "v2_cache_events.json")

    fights    = lj(DATA / "cache_fights.json")
    srcids    = lj(DATA / "cache_source_ids.json")
    talents   = lj(DATA / "cache_talents.json")
    gear      = lj(DATA / "cache_gear.json")
    casts     = lj(DATA / "cache_casts.json")
    buffs     = lj(DATA / "cache_buffs.json")

    # 1) report_meta → cache_fights + cache_source_ids
    fights_added = srcids_added = 0
    for rid, m in meta_v2.items():
        if not isinstance(m, dict):
            continue
        # fights
        if rid not in fights:
            fights[rid] = {}
            fights_added += 1
        for f in m.get("fights", []) or []:
            fid = f.get("id")
            if fid is None:
                continue
            fights[rid][str(fid)] = [f.get("startTime"), f.get("endTime")]
        # source ids
        actors = m.get("actors") or {}
        if isinstance(actors, dict) and actors:
            if rid not in srcids:
                srcids[rid] = {}
                srcids_added += 1
            srcids[rid].update(actors)

    # 2) player_fight → cache_talents + cache_gear
    tal_added = gear_added = 0
    for key, v in pf_v2.items():
        if not isinstance(v, dict):
            continue
        parts = key.split(":")
        if len(parts) < 3:
            continue
        rid, fid_s, char = parts[0], parts[1], ":".join(parts[2:])
        rf = f"{rid}:{int(fid_s)}"
        # talents
        talent_ids = v.get("talents") or []
        if talent_ids:
            if rf not in talents or not isinstance(talents.get(rf), dict):
                talents[rf] = {}
            if char not in talents[rf]:
                tal_added += 1
            talents[rf][char] = sorted(set(int(x) for x in talent_ids if isinstance(x, int)))
        # gear (Korean 'ilvl' average)
        gear_list = v.get("gear") or []
        if gear_list:
            if rf not in gear or not isinstance(gear.get(rf), dict):
                gear[rf] = {}
            ilvls = [g.get("ilvl") for g in gear_list if isinstance(g, dict) and isinstance(g.get("ilvl"), int)]
            avg = round(sum(ilvls)/len(ilvls), 1) if ilvls else None
            if char not in gear[rf]:
                gear_added += 1
            gear[rf][char] = {"ilvl": avg, "gear": gear_list}

    # 3) events → cache_casts + cache_buffs
    cast_added = buff_added = 0
    for key, v in ev_v2.items():
        if not isinstance(v, dict):
            continue
        # key 는 "rid:fid:sid"
        if key not in casts and v.get("casts"):
            casts[key] = v["casts"]
            cast_added += 1
        if key not in buffs and v.get("buffs"):
            buffs[key] = v["buffs"]
            buff_added += 1

    sj(DATA / "cache_fights.json", fights)
    sj(DATA / "cache_source_ids.json", srcids)
    sj(DATA / "cache_talents.json", talents)
    sj(DATA / "cache_gear.json", gear)
    sj(DATA / "cache_casts.json", casts)
    sj(DATA / "cache_buffs.json", buffs)

    print("=== V2 → V1 캐시 머지 ===")
    print(f"  cache_fights:     +{fights_added} reports (total {len(fights)})")
    print(f"  cache_source_ids: +{srcids_added} reports (total {len(srcids)})")
    print(f"  cache_talents:    +{tal_added} chars (total fights {len(talents)})")
    print(f"  cache_gear:       +{gear_added} chars (total fights {len(gear)})")
    print(f"  cache_casts:      +{cast_added} (total {len(casts)})")
    print(f"  cache_buffs:      +{buff_added} (total {len(buffs)})")


if __name__ == "__main__":
    main()
