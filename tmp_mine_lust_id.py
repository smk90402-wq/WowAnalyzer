# 12.0 블러드 버프 id 역추적 — 만터리 킬 2개에서 370~400s 구간 applybuff 나열
import json
from wcl_v2 import WCLV2
from wcl_v2_data import V2Data

v2 = V2Data()
SDB = json.loads(open('data/spell_db.json', encoding='utf-8').read())


def name(gid):
    row = SDB.get(str(gid))
    return (row.get('name_ko') or row.get('name_en')) if isinstance(row, dict) else str(gid)


for code, fid in (("8bcN17hKrMtmTGDB", 15), ("BtADGd3RkJy6gb4f", 10)):
    pf = v2.player_fight(code, fid, "만터리")
    ev = v2.events.get(f"{code}:{fid}:{pf.get('sourceID')}")
    meta = v2.report_meta(code)
    f = next(x for x in meta["fights"] if x["id"] == fid)
    start = f["startTime"]
    print(f"== {code} fight {fid} ==")
    for rec in ev.get("buffs") or []:
        t = (rec[0] - start) / 1000
        if rec[2] == "applybuff" and 360 <= t <= 400:
            print(f"  {t:6.1f}s applybuff {rec[1]} {name(rec[1])}")
    print()
