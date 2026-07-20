# 한밤(1263514) 이벤트의 소스/풀 분포 확인 — boss_raw 수집 조건에 걸리는지
from collections import Counter
from pathlib import Path

from app.local_replay import (_csv_row, _LOG_LINE_RE, _parse_log_ts, _clean_name,
                              _encounter_offsets, _flags_int, _HOSTILE_FLAG)

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")
encs = [e for e in _encounter_offsets(LOG) if e.get("encounter_id") == 3183]

rows_seen = Counter()
samples = []
for idx, enc in enumerate(encs, 1):
    if (enc.get("duration_s") or 0) < 320:
        continue
    start_off = enc["start_off"]
    end_off = enc.get("end_off") or 0
    with LOG.open("rb") as fh:
        fh.seek(start_off)
        pos = start_off
        for raw in fh:
            line_off = pos
            pos += len(raw)
            if end_off and line_off >= end_off:
                break
            line = raw.decode("utf-8-sig", errors="replace")
            if ",1263514," not in line:
                continue
            m = _LOG_LINE_RE.match(line.rstrip("\r\n"))
            if not m:
                continue
            row = _csv_row(m.group(2))
            if not row or len(row) < 11:
                continue
            src = str(row[1])
            hostile = bool(_flags_int(row[3]) & _HOSTILE_FLAG)
            aura = row[12] if len(row) > 12 and row[0].startswith("SPELL_AURA") else ""
            rows_seen[(idx, row[0], src[:10], hostile, aura)] += 1
            if len(samples) < 3 and row[0] == "SPELL_AURA_APPLIED":
                samples.append(m.group(2)[:260])

print("풀 / 이벤트 / 소스 / 적대? / 오라타입:")
for key, n in rows_seen.most_common(20):
    print(f"{n:5d}  풀{key[0]} {key[1]} src={key[2]} hostile={key[3]} {key[4]}")
print()
for s in samples:
    print("샘플:", s)
