# 징표 타임라인 + 룬 웨이브 구조 (풀18)
from collections import Counter, defaultdict
from pathlib import Path

from app.local_replay import (_csv_row, _LOG_LINE_RE, _parse_log_ts, _clean_name,
                              _encounter_offsets, _flags_int)

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")
encs = [e for e in _encounter_offsets(LOG) if e.get("encounter_id") == 3183]
enc = encs[-1]
start_off, end_off, start_dt = enc["start_off"], enc.get("end_off") or 0, enc["_start_dt"]
MARK_KR = {1: "별", 2: "동글", 3: "다이아", 4: "세모", 5: "달", 6: "네모", 7: "엑스", 8: "해골"}

mark_timeline = defaultdict(list)
rune_waves = defaultdict(list)   # apply t 반올림 → [names]
names = {}
with LOG.open("rb") as fh:
    fh.seek(start_off)
    pos = start_off
    for raw in fh:
        line_off = pos
        pos += len(raw)
        if end_off and line_off >= end_off:
            break
        m = _LOG_LINE_RE.match(raw.decode("utf-8-sig", errors="replace").rstrip("\r\n"))
        if not m:
            continue
        ts = _parse_log_ts(m.group(1))
        if not ts:
            continue
        t = round((ts - start_dt).total_seconds(), 1)
        row = _csv_row(m.group(2))
        if not row or len(row) < 9:
            continue
        dest = str(row[5]) if len(row) > 5 else ""
        if dest.startswith("Player-"):
            names.setdefault(dest, _clean_name(row[6]).split("-")[0])
            rf = _flags_int(row[8]) & 0xFF
            mark = rf.bit_length() if rf else 0
            tl = mark_timeline[dest]
            if not tl or tl[-1][1] != mark:
                tl.append((t, mark))
        if (len(row) > 12 and row[0] == "SPELL_AURA_APPLIED" and dest.startswith("Player-")):
            try:
                sid = int(row[9])
            except (ValueError, TypeError):
                continue
            if sid == 1249609:
                rune_waves[round(t)].append(names.get(dest, dest))

print("=== 룬 웨이브 (시각: 인원) ===")
for t in sorted(rune_waves):
    print(f"  {t}s: {len(rune_waves[t])}명 {rune_waves[t]}")

print()
print("=== 징표 변화 타임라인 (0=징표 없음) ===")
for dest, tl in sorted(mark_timeline.items(), key=lambda kv: -len(kv[1])):
    marks = [(t, MARK_KR.get(mk, mk) if mk else '·') for t, mk in tl]
    if len(tl) > 1 or tl[0][1] != 0:
        print(f"  {names.get(dest, dest)[:12]:12s}: {marks[:14]}")
