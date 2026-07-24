# 르우라 위상·징표 채굴 (풀18 = 최장 P3 진행)
# (1) P1 룬 위상: 1249582/1249585/1249609/1249584 오라 — 누가/얼마나/레드·블루 구분 가능한지
# (2) P3 위상 마커: 330s+ 구간에서 공대를 두 그룹으로 가르는 오라 후보
# (3) 징표: destRaidFlags & 0xFF 비트 → 플레이어별 징표 구간
from collections import Counter, defaultdict
from pathlib import Path

from app.local_replay import (_csv_row, _LOG_LINE_RE, _parse_log_ts, _clean_name,
                              _encounter_offsets, _flags_int)

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")
encs = [e for e in _encounter_offsets(LOG) if e.get("encounter_id") == 3183]
enc = encs[-1]   # 풀18 (22:46, 362s — P3 330~362)
start_off, end_off, start_dt = enc["start_off"], enc.get("end_off") or 0, enc["_start_dt"]

RUNE_IDS = {1249582, 1249584, 1249585, 1249609}
MARK_KR = {1: "별", 2: "동글", 3: "다이아", 4: "세모", 5: "달", 6: "네모", 7: "엑스", 8: "해골"}

rune_events = []            # (t, ev, sid, name, dest, destname)
p3_auras = defaultdict(set) # (sid, name) -> P3 구간에 걸린 플레이어 집합
p3_windows = defaultdict(list)
mark_seen = defaultdict(Counter)   # 플레이어 -> 징표 -> 관측 수
mark_timeline = defaultdict(list)  # 플레이어 -> [(t, mark)] 변화 시점만
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
        t = round((ts - start_dt).total_seconds(), 2)
        row = _csv_row(m.group(2))
        if not row or len(row) < 9:
            continue
        ev = row[0]
        dest = str(row[5]) if len(row) > 5 else ""
        # 징표: destRaidFlags = row[8]
        if dest.startswith("Player-"):
            names.setdefault(dest, _clean_name(row[6]))
            rf = _flags_int(row[8]) & 0xFF
            if rf:
                # 비트 → 징표 번호 (1~8)
                mark = rf.bit_length()   # 0x1->1(별) ... 0x80->8(해골)
                mark_seen[dest][mark] += 1
                tl = mark_timeline[dest]
                if not tl or tl[-1][1] != mark:
                    tl.append((t, mark))
        if not ev.startswith("SPELL") or len(row) < 13:
            continue
        try:
            sid = int(row[9])
        except (ValueError, TypeError):
            continue
        if sid in RUNE_IDS and ev in ("SPELL_AURA_APPLIED", "SPELL_AURA_REMOVED") and dest.startswith("Player-"):
            rune_events.append((t, ev, sid, _clean_name(row[10]), dest))
        # P3 오라 후보: 330s 이후 APPLIED, DEBUFF/BUFF 무관
        if (t >= 330 and ev == "SPELL_AURA_APPLIED" and dest.startswith("Player-")
                and len(row) > 12 and row[12] in ("BUFF", "DEBUFF")):
            p3_auras[(sid, _clean_name(row[10]), row[12])].add(dest)
            p3_windows[(sid, _clean_name(row[10]))].append(t)

print("=== (1) P1 룬 오라 이벤트 (t<231) ===")
rune_by = defaultdict(list)
for t, ev, sid, name, dest in rune_events:
    if t < 231:
        rune_by[(sid, name)].append((t, ev, names.get(dest, dest)[:8]))
for (sid, name), evs in sorted(rune_by.items()):
    applied = [e for e in evs if e[1] == "SPELL_AURA_APPLIED"]
    print(f"  sid={sid} {name!r}: APPLIED {len(applied)}건")
    for t, _, nm in applied[:8]:
        print(f"      {t:6.1f}s {nm}")

print()
print("=== (2) P3(330s+) 오라 — 걸린 인원수별 (2~18명, 위상 후보) ===")
for (sid, name, kind), players in sorted(p3_auras.items(), key=lambda kv: -len(kv[1])):
    n = len(players)
    if 2 <= n <= 18:
        ts = sorted(p3_windows[(sid, name)])
        print(f"  sid={sid} {name!r} [{kind}] {n}명 (t {ts[0]:.0f}~{ts[-1]:.0f}, {len(ts)}회)")

print()
print("=== (3) 징표 관측 (플레이어별) ===")
for dest, cnt in sorted(mark_seen.items(), key=lambda kv: -sum(kv[1].values())):
    tl = mark_timeline[dest][:6]
    print(f"  {names.get(dest, dest)[:14]:14s} {dict((MARK_KR[k], v) for k, v in cnt.items())} "
          f"타임라인={[(t, MARK_KR[m]) for t, m in tl]}")
