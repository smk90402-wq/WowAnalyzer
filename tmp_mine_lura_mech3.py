# 3차: (1) 폭발 반경 실측 (row[12]=infoGUID 수정)
#       (2) 비플레이어 소스 BUFF 전수 → 수정 소지 오라 후보 (희소 오라)
#       (3) '여명/핵/채취/활력' 이름 이벤트 전수
import math
from collections import Counter, defaultdict
from pathlib import Path

from app.local_replay import _csv_row, _LOG_LINE_RE, _parse_log_ts, _clean_name

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")
START, END = 1043843322, 1161583641

star_dmg = []
crit_dmg = []
star_debuff_off = []
crystal_casts = []
npc_buffs = Counter()          # (sid, name, src8) -> n  (플레이어 대상, 비플레이어 소스 BUFF)
npc_buff_players = defaultdict(set)
name_watch = Counter()

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
        t = round((ts - start_dt).total_seconds(), 2)
        row = _csv_row(m.group(2))
        if not row or len(row) < 11 or not row[0].startswith(("SPELL", "RANGE")):
            continue
        ev = row[0]
        try:
            sid = int(row[9])
        except (ValueError, TypeError):
            continue
        name = _clean_name(row[10])
        dest = str(row[5]) if len(row) > 5 else ""
        src = str(row[1])
        if ev == "SPELL_CAST_SUCCESS" and sid == 1253050:
            crystal_casts.append((t, src))
        if any(w in name for w in ("여명", "핵", "채취", "활력", "월식")):
            name_watch[(sid, name, ev, src[:8], dest[:8])] += 1
        if ev == "SPELL_AURA_REMOVED" and sid in (1279512, 1285510) and dest.startswith("Player-"):
            star_debuff_off.append((t, dest, sid))
        if (ev == "SPELL_AURA_APPLIED" and len(row) > 12 and row[12] == "BUFF"
                and dest.startswith("Player-") and not src.startswith(("Player-", "Pet-"))):
            npc_buffs[(sid, name, src[:8])] += 1
            npc_buff_players[(sid, name)].add(dest)
        if ev == "SPELL_DAMAGE" and len(row) > 27 and str(row[12]).startswith("Player-"):
            try:
                x, y = float(row[26]), float(row[27])
            except (ValueError, TypeError):
                continue
            if sid == 1281473:
                star_dmg.append((t, str(row[12]), x, y))
            elif sid == 1281178:
                crit_dmg.append((t, str(row[12]), x, y))

out = []
out.append("=== 비플레이어 소스 BUFF (플레이어 대상, 희소한 것 위주) ===")
for (sid, name, src), n in sorted(npc_buffs.items(), key=lambda kv: kv[1]):
    players = len(npc_buff_players[(sid, name)])
    if n <= 40:
        out.append(f"{n:5d}회 {players:2d}명  sid={sid} {name!r} src={src}")

out.append("")
out.append(f"=== 이름 워치(여명/핵/채취/활력/월식) — 수정시전 {len(crystal_casts)}회 ===")
for key, n in name_watch.most_common(30):
    out.append(f"{n:6d}  sid={key[0]} {key[1]!r} {key[2]} src={key[3]} dst={key[4]}")

out.append("")
out.append("=== 별빛파열 폭발 (해제 ±0.4s, 중심=해제자) ===")
for ot, oguid, osid in star_debuff_off:
    hits = [(t2, d, x, y) for (t2, d, x, y) in star_dmg if abs(t2 - ot) <= 0.4]
    if not hits:
        continue
    center = next(((x, y) for (t2, d, x, y) in hits if d == oguid), None)
    dists = sorted(round(math.hypot(x - center[0], y - center[1]), 1)
                   for (t2, d, x, y) in hits) if center else []
    out.append(f"t={ot} sid={osid} hits={len(hits)} 거리={dists if dists else '중심 미피격'}")

out.append("")
out.append("=== 임계점 폭발 클러스터 (0.25s) ===")
crit_dmg.sort()
i = 0
solo = 0
while i < len(crit_dmg):
    j = i
    while j < len(crit_dmg) and crit_dmg[j][0] - crit_dmg[i][0] <= 0.25:
        j += 1
    group = crit_dmg[i:j]
    if len(group) >= 2:
        pair = sorted(round(math.hypot(a[2] - b[2], a[3] - b[3]), 1)
                      for ai, a in enumerate(group) for b in group[ai + 1:])
        out.append(f"t={group[0][0]} n={len(group)} 쌍거리={pair[:8]}")
    else:
        solo += 1
    i = j
out.append(f"단독 폭발 {solo}건 (겹침 없음)")

text = "\n".join(out)
Path("tmp_lura_mech3_out.txt").write_text(text, encoding="utf-8")
print(text[:5500])
