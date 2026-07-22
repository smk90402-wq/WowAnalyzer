# 정찰: (1) 로컬 로그 COMBATANT_INFO로 두 캐릭터 스펙 확정
#        (2) WCL 한밤의 도래(3183) 부정죽기/증강 랭킹 가용성 (신화/영웅)
import json
from pathlib import Path

from app.local_replay import (_csv_row, _LOG_LINE_RE, _parse_log_ts,
                              _encounter_offsets, _combatant_spec, _clean_name)

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")
encs = [e for e in _encounter_offsets(LOG) if e.get("encounter_id") == 3183]
enc = encs[-1]

# (1) 스펙: COMBATANT_INFO 는 전투 시작 직후 몰려 있음 — 앞 400줄만
specs = {}
names = {}
with LOG.open("rb") as fh:
    fh.seek(enc["start_off"])
    for i, raw in enumerate(fh):
        if i > 3000:
            break
        line = raw.decode("utf-8-sig", errors="replace").rstrip("\r\n")
        m = _LOG_LINE_RE.match(line)
        if not m:
            continue
        row = _csv_row(m.group(2))
        if not row:
            continue
        if row[0] == "COMBATANT_INFO":
            got = _combatant_spec(row)
            if got:
                specs[got[0]] = got[1]
        elif len(row) > 2 and str(row[1]).startswith("Player-"):
            names.setdefault(str(row[1]), _clean_name(row[2]))

SPEC_KR = {250: "혈기", 251: "냉기", 252: "부정", 1467: "황폐", 1468: "보존", 1473: "증강"}
print("=== 스펙 확정 ===")
for guid, sid in specs.items():
    nm = names.get(guid, guid)
    if any(k in nm for k in ("이디", "하늘연달", "령월", "용단참")):
        print(f"  {nm[:24]:24s} specID={sid} ({SPEC_KR.get(sid, '?')})")

# (2) WCL 랭킹 프로브
from wcl_v2 import WCLV2

Q_TOP = """
query($encounterId: Int!, $difficulty: Int!, $cls: String!, $spec: String!, $partition: Int!) {
  worldData {
    encounter(id: $encounterId) {
      characterRankings(metric: dps, difficulty: $difficulty,
        className: $cls, specName: $spec, page: 1, partition: $partition)
    }
  }
}
"""
Q_ZONE = 'query($id: Int!) { worldData { zone(id: $id) { partitions { id name default } } } }'

cli = WCLV2()
zone = cli.query(Q_ZONE, {"id": 46})["worldData"]["zone"]
part = next((p for p in zone.get("partitions") or [] if p.get("default")), {"id": 3})
print(f"파티션: {part}")
for cls, spec in (("DeathKnight", "Unholy"), ("Evoker", "Augmentation")):
    for diff in (5, 4):
        data = cli.query(Q_TOP, {"encounterId": 3183, "difficulty": diff,
                                 "cls": cls, "spec": spec, "partition": int(part["id"])})
        cr = (((data.get("worldData") or {}).get("encounter") or {})
              .get("characterRankings") or {})
        rows = cr.get("rankings") or []
        n_with_report = sum(1 for r in rows if (r.get("report") or {}).get("code"))
        top1 = rows[0] if rows else {}
        print(f"{cls}/{spec} 난이도{diff}: {len(rows)}건 (report 있는 것 {n_with_report}) "
              f"1위 dps={round(float(top1.get('amount') or 0)):,} dur={round(float(top1.get('duration') or 0)/1000)}s")
