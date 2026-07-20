# 르우라 P3 별자리(Dark Constellation) 피격/사망 상관 채굴
# - '별자리' 이름 이벤트 전수 (id, 타입, 페이즈 시각)
# - 피격 후 5초 내 사망한 플레이어 목록 (직접 결정타인지: 사망 직전 마지막 큰 피해)
import math
from collections import Counter, defaultdict
from pathlib import Path

from app.local_replay import (_csv_row, _LOG_LINE_RE, _parse_log_ts, _clean_name,
                              _encounter_offsets)

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")
encs = [e for e in _encounter_offsets(LOG) if e.get("encounter_id") == 3183]

name_events = Counter()
hits = []            # (풀, t, dest_guid, 이름, 데미지, x, y)
deaths_after = []    # (풀, 피격t, 사망t, 이름, 피해량)
last_big_hit = {}    # guid -> (t, spell, amount)  사망 결정타 추적
death_blows = Counter()

for idx, enc in enumerate(encs, 1):
    start_off = enc["start_off"]
    end_off = enc.get("end_off") or 0
    start_dt = enc["_start_dt"]
    pull_hits = {}   # guid -> [(t, dmg, x, y)]
    pull_deaths = []
    last_hit_any = {}
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
            if not row:
                continue
            ev = row[0]
            if ev == "UNIT_DIED" and len(row) > 6 and str(row[5]).startswith("Player-"):
                if str(row[-1]).strip() == "1":
                    continue
                g = str(row[5])
                pull_deaths.append((t, g, _clean_name(row[6])))
                blow = last_hit_any.get(g)
                if blow and t - blow[0] <= 2.0:
                    death_blows[blow[1]] += 1
                continue
            if not ev.startswith(("SPELL", "RANGE")) or len(row) < 11:
                continue
            name = _clean_name(row[10])
            # 사망 결정타 추적: 플레이어가 받은 모든 피해
            if (ev in ("SPELL_DAMAGE", "SPELL_PERIODIC_DAMAGE", "RANGE_DAMAGE")
                    and len(row) > 31 and str(row[5]).startswith("Player-")):
                try:
                    amt = int(row[31])
                except (ValueError, TypeError):
                    amt = 0
                if amt > 0:
                    last_hit_any[str(row[5])] = (t, name, amt)
            if "별자리" not in name:
                continue
            aura = row[12] if len(row) > 12 and ev.startswith("SPELL_AURA") else ""
            try:
                sid = int(row[9])
            except (ValueError, TypeError):
                sid = 0
            name_events[(sid, name, ev, str(row[1])[:8], str(row[5])[:8], aura)] += 1
            if ev == "SPELL_DAMAGE" and str(row[5]).startswith("Player-"):
                g = str(row[5])
                amt = 0
                x = y = None
                if len(row) > 31:
                    try:
                        amt = int(row[31])
                    except (ValueError, TypeError):
                        pass
                if len(row) > 27 and str(row[12]) == g:
                    try:
                        x, y = float(row[26]), float(row[27])
                    except (ValueError, TypeError):
                        pass
                pull_hits.setdefault(g, []).append((t, amt))
                hits.append((idx, t, g, _clean_name(row[6]), amt, x, y))
    # 피격 → 5초 내 사망
    for dt_, g, nm in pull_deaths:
        for ht, amt in pull_hits.get(g, []):
            if 0 <= dt_ - ht <= 5.0:
                deaths_after.append((idx, ht, dt_, nm, amt))
                break

out = []
out.append("=== '별자리' 이벤트 전수 ===")
for key, n in name_events.most_common(30):
    out.append(f"{n:6d}  sid={key[0]} {key[1]!r} {key[2]} src={key[3]} dst={key[4]} {key[5]}")
out.append("")
out.append(f"=== 별자리 SPELL_DAMAGE 피격 {len(hits)}건 (풀/시각 분포) ===")
by_pull = Counter(h[0] for h in hits)
out.append("풀별: " + ", ".join(f"풀{p}×{n}" for p, n in sorted(by_pull.items())))
for h in hits[:20]:
    out.append(f"풀{h[0]} t={h[1]} {h[3][:12]} 피해={h[4]:,} pos=({h[5]},{h[6]})")
out.append("")
out.append(f"=== 별자리 피격 후 5초 내 사망 {len(deaths_after)}건 ===")
for p, ht, dt_, nm, amt in deaths_after[:20]:
    out.append(f"풀{p} 피격 {ht}s → 사망 {dt_}s ({nm[:12]}, 피해 {amt:,})")
out.append("")
out.append("=== 전체 사망 결정타(2초 내 마지막 피해) 순위 ===")
for name, n in death_blows.most_common(15):
    out.append(f"{n:4d}  {name}")

text = "\n".join(out)
Path("tmp_lura_constellation_out.txt").write_text(text, encoding="utf-8")
print(text[:4500])
