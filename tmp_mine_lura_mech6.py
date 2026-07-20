# 6차: (1) 수정 보유 오라 1253031(Glimmering) 등 관련 id 실존 확인
#       (2) 별빛파열 1281473 낙하 시 최근접 타인 거리 → 반경 상한
import math
from collections import Counter
from pathlib import Path

from app.local_replay import (_csv_row, _LOG_LINE_RE, _parse_log_ts, _clean_name,
                              _encounter_offsets)

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")
WATCH_IDS = {1253031, 1266627, 1266628, 1266624, 1253022, 1279581, 1253104, 1282458, 1254398}

encs = [e for e in _encounter_offsets(LOG) if e.get("encounter_id") == 3183]
id_events = Counter()
hold_windows = []       # (풀, guid, name, start, end)
nearest_at_pop = []

for idx, enc in enumerate(encs, 1):
    if idx not in (6, 18, 20):   # 첫 오라 등장 풀 + 마지막 두 풀만 (속도)
        continue
    start_off = enc["start_off"]
    end_off = enc.get("end_off") or 0
    start_dt = enc["_start_dt"]
    pos_latest = {}
    hold_open = {}
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
            if not row or len(row) < 11 or not row[0].startswith(("SPELL", "RANGE")):
                continue
            ev = row[0]
            try:
                sid = int(row[9])
            except (ValueError, TypeError):
                continue
            # 고급 좌표 유지 (모든 데미지/힐 계열, infoGUID=row[12])
            if len(row) > 27 and str(row[12]).startswith("Player-"):
                try:
                    pos_latest[str(row[12])] = (t, float(row[26]), float(row[27]))
                except (ValueError, TypeError):
                    pass
            if sid in WATCH_IDS:
                aura = row[12] if len(row) > 12 and ev.startswith("SPELL_AURA") else ""
                id_events[(sid, _clean_name(row[10]), ev, str(row[1])[:8], str(row[5])[:8], aura)] += 1
                if sid == 1253031 and ev in ("SPELL_AURA_APPLIED", "SPELL_AURA_REMOVED"):
                    g = str(row[5])
                    if ev == "SPELL_AURA_APPLIED":
                        hold_open[g] = (t, _clean_name(row[6]))
                    elif g in hold_open:
                        st, nm = hold_open.pop(g)
                        hold_windows.append((idx, nm, st, t, round(t - st, 1)))
            if ev == "SPELL_DAMAGE" and sid == 1281473 and str(row[12]).startswith("Player-"):
                try:
                    x, y = float(row[26]), float(row[27])
                except (ValueError, TypeError):
                    continue
                popper = str(row[12])
                dists = [round(math.hypot(x - px, y - py), 1)
                         for g, (pt, px, py) in pos_latest.items()
                         if g != popper and t - pt <= 3.0]
                if dists:
                    nearest_at_pop.append((idx, t, min(dists)))
    for g, (st, nm) in hold_open.items():
        hold_windows.append((idx, nm, st, None, None))

out = []
out.append("=== 관련 id 이벤트 ===")
for key, n in id_events.most_common(40):
    out.append(f"{n:5d}  sid={key[0]} {key[1]!r} {key[2]} src={key[3]} dst={key[4]} {key[5]}")
out.append("")
out.append(f"=== 1253031 보유 구간 ({len(hold_windows)}건) ===")
for pull, nm, st, en, dur in hold_windows[:40]:
    out.append(f"풀{pull} {nm[:14]:14s} {st:7.1f} ~ {en if en is not None else '끝까지'} ({dur}s)")
out.append("")
near = sorted(d for (_, _, d) in nearest_at_pop)
out.append(f"=== 별빛파열 낙하 시 최근접 타인 거리 (n={len(near)}) ===")
out.append(f"min5={near[:5]} med={near[len(near)//2] if near else None}")

text = "\n".join(out)
Path("tmp_lura_mech6_out.txt").write_text(text, encoding="utf-8")
print(text[:5000])
