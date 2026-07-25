# 7/19 22:46 르우라 #18풀 — P3 첫 사망(수정특임 법사?) 원인 채굴
# 후보: 불화(반대 징표 뽀뽀 페널티 1249584/85) vs 어둠의 별자리(1266388/1266344)
from collections import defaultdict
from pathlib import Path

from app.local_replay import (_csv_row, _LOG_LINE_RE, _parse_log_ts, _clean_name,
                              _encounter_offsets)

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")
enc = [e for e in _encounter_offsets(LOG) if e.get("encounter_id") == 3183][-1]
start_off, end_off, start_dt = enc["start_off"], enc.get("end_off") or 0, enc["_start_dt"]
print(f"풀 시작 {start_dt}, 길이 {enc.get('duration_s')}s")

WATCH = {1249609: "암흑의 룬", 1249582: "공명", 1249584: "불화", 1249585: "불화b",
         1266388: "어둠의 별자리", 1266344: "어둠의 별자리dmg", 1263514: "한밤"}

deaths = []            # (t, guid, name)
dmg = defaultdict(list)  # guid → (t, spell, amount_raw, over_raw, kind)
auras = []             # (t, event, sid, guid, name, stacks)
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
        if not row:
            continue
        ev = row[0]
        if ev == "UNIT_DIED" and len(row) > 6 and str(row[5]).startswith("Player-"):
            deaths.append((t, str(row[5]), _clean_name(row[6])))
        elif ev in ("SPELL_DAMAGE", "SPELL_PERIODIC_DAMAGE", "RANGE_DAMAGE") and len(row) > 30 \
                and str(row[5]).startswith("Player-"):
            g = str(row[5]); names[g] = _clean_name(row[6])
            dmg[g].append((t, _clean_name(row[10]), row[29], row[30], ev))
        elif ev == "SWING_DAMAGE" and len(row) > 27 and str(row[5]).startswith("Player-"):
            g = str(row[5]); names[g] = _clean_name(row[6])
            dmg[g].append((t, f"평타({_clean_name(row[2])})", row[26], row[27], ev))
        elif ev.startswith("SPELL_AURA_") and len(row) > 9 and str(row[5]).startswith("Player-"):
            try:
                sid = int(row[9])
            except (TypeError, ValueError):
                continue
            if sid in WATCH:
                st = row[13] if len(row) > 13 else ""
                auras.append((t, ev.replace("SPELL_AURA_", ""), sid,
                              str(row[5]), _clean_name(row[6]), st))

deaths.sort()
print("\n=== 전체 사망 (시간순) ===")
for t, g, nm in deaths:
    print(f"  {t:7.1f}s ({int(t//60)}:{t%60:04.1f})  {nm}")

p3_deaths = [d for d in deaths if d[0] >= 300]
if not p3_deaths:
    print("\nP3(300s+) 사망 없음"); raise SystemExit
t0, g0, nm0 = p3_deaths[0]
print(f"\n=== P3 첫 사망: {nm0} @{t0:.1f}s ===")

print(f"\n[죽기 전 마지막 피해 12건 — {nm0}]")
for t, sp, amt, over, kind in [d for d in dmg[g0] if d[0] <= t0 + 0.1][-12:]:
    print(f"  {t:7.2f}s  {sp:24s} amount={amt:>10} over={over:>9} {kind}")

print(f"\n[{nm0} 의 감시 오라 타임라인 (전 구간)]")
for t, ev, sid, g, nm, st in auras:
    if g == g0:
        print(f"  {t:7.2f}s  {WATCH[sid]:10s} {ev:14s} stacks={st}")

print("\n[전 공대 불화(1249584/85) 발생 전체]")
hit = False
for t, ev, sid, g, nm, st in auras:
    if sid in (1249584, 1249585):
        print(f"  {t:7.2f}s  {nm:14s} {ev}")
        hit = True
if not hit:
    print("  (없음)")

print("\n[전 공대 어둠의 별자리(1266388/1266344) 오라 전체]")
hit = False
for t, ev, sid, g, nm, st in auras:
    if sid in (1266388, 1266344):
        print(f"  {t:7.2f}s  {nm:14s} {WATCH[sid]} {ev}")
        hit = True
if not hit:
    print("  (없음)")

print("\n[별자리 '피해' 이벤트 검색 — 이름에 별자리 포함된 데미지]")
hit = False
for g, lst in dmg.items():
    for t, sp, amt, over, kind in lst:
        if "별자리" in sp:
            print(f"  {t:7.2f}s  {names.get(g, g):14s} {sp} amount={amt} over={over}")
            hit = True
if not hit:
    print("  (없음)")
