# 룬 창(웨이브1 39~62s, 웨이브2 101~124s)에서 룬 15명에게 걸리는 오라 전수
# → 15명을 ~5모양(엑스/동글/다이아/역삼/티)으로 가르는 오라 id 후보 탐색
from collections import Counter, defaultdict
from pathlib import Path

from app.local_replay import (_csv_row, _LOG_LINE_RE, _parse_log_ts, _clean_name,
                              _encounter_offsets)

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")
enc = [e for e in _encounter_offsets(LOG) if e.get("encounter_id") == 3183][-1]
start_off, end_off, start_dt = enc["start_off"], enc.get("end_off") or 0, enc["_start_dt"]

WINDOWS = [(39, 62), (101, 124), (350, 362)]
IGNORE = {1249609}   # 암흑의 룬 자체

by_sid = defaultdict(lambda: defaultdict(set))   # window → sid → players
names = {}
sid_names = {}
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
        win = next((i for i, (a, b) in enumerate(WINDOWS) if a <= t <= b), None)
        if win is None:
            continue
        row = _csv_row(m.group(2))
        if not row or len(row) < 13 or row[0] not in ("SPELL_AURA_APPLIED", "SPELL_AURA_APPLIED_DOSE"):
            continue
        dest = str(row[5])
        if not dest.startswith("Player-"):
            continue
        try:
            sid = int(row[9])
        except (ValueError, TypeError):
            continue
        if sid in IGNORE:
            continue
        # 보스/환경 소스만 (플레이어 소스 버프 잡음 제거)
        src = str(row[1])
        if src.startswith(("Player-", "Pet-")):
            continue
        names[dest] = _clean_name(row[6]).split("-")[0]
        sid_names[sid] = _clean_name(row[10])
        by_sid[win][sid].add(dest)

for win, (a, b) in enumerate(WINDOWS):
    print(f"=== 창 {a}~{b}s — 보스/환경 소스 오라별 대상 수 ===")
    for sid, players in sorted(by_sid[win].items(), key=lambda kv: -len(kv[1])):
        n = len(players)
        if 1 <= n <= 16:
            nm = [names[p] for p in sorted(players)]
            print(f"  sid={sid} {sid_names.get(sid, '?')!r} {n}명: {nm[:6]}{'...' if n > 6 else ''}")
    print()
