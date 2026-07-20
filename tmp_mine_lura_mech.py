# 르우라 기믹 채굴: 수정 오라 id, 임계점/별빛파열 지속·데미지 구조 (풀18 구간)
import sys
from collections import Counter, defaultdict
from pathlib import Path

from app.local_replay import _csv_row, _LOG_LINE_RE, _parse_log_ts, _clean_name

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")
START, END = 1043843322, 1161583641

WATCH_NAMES = ("수정", "별빛", "임계점", "월식")
AURA_IDS = {1281184, 1285510}

name_events = Counter()          # (sid, name, event, src7, dst7, auratype) -> n
aura_open = {}
aura_windows = defaultdict(list)  # sid -> [duration]
crit_src = Counter()             # 1281178 소스 guid 종류
crit_sample = []
star_sample = []
raw_samples = {}

start_dt = None
with LOG.open("rb") as fh:
    fh.seek(START)
    pos = START
    for raw in fh:
        line_off = pos
        pos += len(raw)
        if line_off >= END:
            break
        m = _LOG_LINE_RE.match(raw.decode("utf-8-sig", errors="replace").rstrip("\r\n"))
        if not m:
            continue
        ts = _parse_log_ts(m.group(1))
        if not ts:
            continue
        if start_dt is None:
            start_dt = ts
        t = (ts - start_dt).total_seconds()
        row = _csv_row(m.group(2))
        if not row or len(row) < 11 or not row[0].startswith(("SPELL", "RANGE")):
            continue
        ev = row[0]
        try:
            sid = int(row[9])
        except (ValueError, TypeError):
            continue
        name = _clean_name(row[10])
        if any(w in name for w in WATCH_NAMES):
            aura_type = row[12] if len(row) > 12 and ev.startswith("SPELL_AURA") else ""
            key = (sid, name, ev, str(row[1])[:8], str(row[5])[:8] if len(row) > 5 else "", aura_type)
            name_events[key] += 1
            if sid not in raw_samples and ev in ("SPELL_DAMAGE", "SPELL_AURA_APPLIED"):
                raw_samples[sid] = (ev, m.group(2)[:400])
        if ev in ("SPELL_AURA_APPLIED", "SPELL_AURA_REMOVED") and sid in AURA_IDS:
            dest = str(row[5])
            k = (sid, dest)
            if ev == "SPELL_AURA_APPLIED":
                aura_open[k] = t
            elif k in aura_open:
                aura_windows[sid].append(round(t - aura_open.pop(k), 2))
        if ev == "SPELL_DAMAGE" and sid == 1281178:
            crit_src[str(row[1])[:14]] += 1
            if len(crit_sample) < 3:
                crit_sample.append((round(t, 1), m.group(2)[:420]))
        if ev == "SPELL_DAMAGE" and sid == 1285510 and len(star_sample) < 3:
            star_sample.append((round(t, 1), m.group(2)[:420]))

out = []
out.append("=== 이름 매칭 이벤트 (상위 60) ===")
for key, n in name_events.most_common(60):
    out.append(f"{n:6d}  sid={key[0]} {key[1]!r} {key[2]} src={key[3]} dst={key[4]} {key[5]}")
out.append("")
out.append("=== 오라 지속시간 ===")
for sid, durs in aura_windows.items():
    durs.sort()
    out.append(f"sid={sid} n={len(durs)} min={durs[0]} med={durs[len(durs)//2]} max={durs[-1]}")
out.append("")
out.append("=== 1281178(임계점 데미지) 소스 분포 ===")
for src, n in crit_src.most_common(10):
    out.append(f"{n:6d}  {src}")
out.append("")
out.append("=== 1281178 원시 샘플 ===")
for t, line in crit_sample:
    out.append(f"[{t}s] {line}")
out.append("=== 1285510 데미지 원시 샘플 ===")
for t, line in star_sample:
    out.append(f"[{t}s] {line}")
out.append("=== id별 첫 원시 샘플 ===")
for sid, (ev, line) in sorted(raw_samples.items()):
    out.append(f"sid={sid} {ev}: {line[:300]}")

Path("tmp_lura_mech_out.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out[:80]))
