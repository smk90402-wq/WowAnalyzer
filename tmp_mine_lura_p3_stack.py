# P3(어둠의 용해 이후) 보호막 밖 중첩 디버프 규명
# - t>=320 구간의 SPELL_AURA_APPLIED_DOSE (중첩) 전수 + 최대 중첩
# - '자정/한밤/어둠' 이름 이벤트 + 주기 피해
# - 중첩 디버프 보유 중 사망 상관
from collections import Counter, defaultdict
from pathlib import Path

from app.local_replay import (_csv_row, _LOG_LINE_RE, _parse_log_ts, _clean_name,
                              _encounter_offsets)

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")
encs = [e for e in _encounter_offsets(LOG) if e.get("encounter_id") == 3183]

dose = Counter()            # (sid, name) -> n
dose_max = Counter()        # (sid, name) -> max stacks
name_watch = Counter()
stack_deaths = []           # (풀, 사망t, 이름, sid, 마지막 중첩)

for idx, enc in enumerate(encs, 1):
    if (enc.get("duration_s") or 0) < 320:
        continue
    start_off = enc["start_off"]
    end_off = enc.get("end_off") or 0
    start_dt = enc["_start_dt"]
    cur_stacks = defaultdict(dict)   # sid -> guid -> stacks
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
            if t < 318:
                continue
            row = _csv_row(m.group(2))
            if not row:
                continue
            ev = row[0]
            if ev == "UNIT_DIED" and len(row) > 6 and str(row[5]).startswith("Player-"):
                if str(row[-1]).strip() == "1":
                    continue
                g = str(row[5])
                for sid, per in cur_stacks.items():
                    if per.get(g):
                        stack_deaths.append((idx, t, _clean_name(row[6]), sid, per[g]))
                continue
            if not ev.startswith("SPELL") or len(row) < 11:
                continue
            name = _clean_name(row[10])
            try:
                sid = int(row[9])
            except (ValueError, TypeError):
                continue
            if any(w in name for w in ("자정", "한밤", "어둠", "황혼")):
                aura = row[12] if len(row) > 12 and ev.startswith("SPELL_AURA") else ""
                name_watch[(sid, name, ev, aura)] += 1
            if ev == "SPELL_AURA_APPLIED_DOSE" and len(row) > 13 and str(row[5]).startswith("Player-"):
                try:
                    stacks = int(row[13])
                except (ValueError, TypeError):
                    stacks = 0
                dose[(sid, name)] += 1
                dose_max[(sid, name)] = max(dose_max[(sid, name)], stacks)
                cur_stacks[sid][str(row[5])] = stacks
            elif ev == "SPELL_AURA_REMOVED" and str(row[5]).startswith("Player-"):
                cur_stacks.get(sid, {}).pop(str(row[5]), None)

out = []
out.append("=== P3(318s+) 중첩(DOSE) 디버프 전수 ===")
for (sid, name), n in dose.most_common(15):
    out.append(f"{n:5d}회  최대×{dose_max[(sid, name)]:2d}  sid={sid} {name!r}")
out.append("")
out.append("=== 자정/한밤/어둠/황혼 이름 이벤트 (P3 구간) ===")
for key, n in name_watch.most_common(25):
    out.append(f"{n:6d}  sid={key[0]} {key[1]!r} {key[2]} {key[3]}")
out.append("")
out.append(f"=== 중첩 디버프 보유 중 사망 {len(stack_deaths)}건 ===")
for p, t, nm, sid, st in stack_deaths[:25]:
    out.append(f"풀{p} t={t} {nm[:12]} sid={sid} ×{st}")

text = "\n".join(out)
Path("tmp_lura_p3_stack_out.txt").write_text(text, encoding="utf-8")
print(text[:4000])
