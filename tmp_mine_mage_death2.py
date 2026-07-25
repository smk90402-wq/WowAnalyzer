# 후속: Waterself(수정특임 법사) 결정타 + 불화 피해가 공대 전체를 때렸는지 확인
from collections import defaultdict
from pathlib import Path

from app.local_replay import (_csv_row, _LOG_LINE_RE, _parse_log_ts, _clean_name,
                              _encounter_offsets)

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")
enc = [e for e in _encounter_offsets(LOG) if e.get("encounter_id") == 3183][-1]
start_off, end_off, start_dt = enc["start_off"], enc.get("end_off") or 0, enc["_start_dt"]

TARGET = "Waterself"
last_hits = []
discord_victims = defaultdict(int)   # name → 불화 피해 횟수 (354.5~356.5)
target_auras = []

with LOG.open("rb") as fh:
    fh.seek(start_off)
    pos = start_off
    for raw in fh:
        line_off = pos
        pos += len(raw)
        if end_off and line_off >= end_off:
            break
        line = raw.decode("utf-8-sig", errors="replace")
        # 빠른 프리필터 — 관심 문자열 없는 줄 스킵
        if TARGET not in line and "불화" not in line:
            continue
        m = _LOG_LINE_RE.match(line.rstrip("\r\n"))
        if not m:
            continue
        ts = _parse_log_ts(m.group(1))
        if not ts:
            continue
        t = round((ts - start_dt).total_seconds(), 2)
        row = _csv_row(m.group(2))
        if not row or len(row) < 7:
            continue
        ev = row[0]
        dest = _clean_name(row[6]) if len(row) > 6 else ""
        if ev in ("SPELL_DAMAGE", "SPELL_PERIODIC_DAMAGE") and len(row) > 10:
            sp = _clean_name(row[10])
            if sp == "불화" and 354.5 <= t <= 356.5 and str(row[5]).startswith("Player-"):
                discord_victims[dest.split("-")[0]] += 1
            if dest.startswith(TARGET) and 348 <= t <= 356:
                last_hits.append((t, sp, ev))
        elif ev.startswith("SPELL_AURA_") and dest.startswith(TARGET) and len(row) > 10:
            sp = _clean_name(row[10])
            if sp in ("한밤", "불화", "암흑의 룬", "공명", "일렁이는 빛") and 330 <= t <= 356:
                st = row[13] if len(row) > 13 else ""
                target_auras.append((t, ev.replace("SPELL_AURA_", ""), sp, st))
        elif ev == "UNIT_DIED" and dest.startswith(TARGET):
            last_hits.append((t, "★UNIT_DIED", ev))

print(f"[Waterself 최후 구간 348~356s 피해/사망]")
for t, sp, ev in last_hits:
    print(f"  {t:7.2f}s  {sp:20s} {ev}")

print(f"\n[Waterself P3 오라 330~356s]")
for t, ev, sp, st in target_auras:
    print(f"  {t:7.2f}s  {sp:10s} {ev:14s} {st}")

print(f"\n[불화 피해 대상 (354.5~356.5s) — {len(discord_victims)}명]")
for nm, n in sorted(discord_victims.items(), key=lambda kv: -kv[1]):
    print(f"  {nm:12s} ×{n}")
