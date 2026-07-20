# 2차 채굴: (1) 여명의 수정 시전자 주변 BUFF 오라 → 소지 오라 후보
#           (2) 별빛파열 1281473 폭발 클러스터 → 반경 실측
#           (3) 임계점 1281178 동시각 클러스터 → 겹침 여부/반경 단서
import math
from collections import Counter, defaultdict
from pathlib import Path

from app.local_replay import _csv_row, _LOG_LINE_RE, _parse_log_ts, _clean_name

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")
START, END = 1043843322, 1161583641

crystal_casts = []            # (t, guid)
buff_events = []              # (t, ev, sid, name, src, dest)  BUFF on Player
star_dmg = []                 # (t, dest, x, y)  1281473 피해 위치
star_debuff_off = []          # (t, dest) 1279512/1285510 REMOVED
crit_dmg = []                 # (t, dest, x, y)  1281178
pos_latest = {}               # guid -> (t, x, y)

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
        dest = str(row[5]) if len(row) > 5 else ""
        if ev == "SPELL_CAST_SUCCESS" and sid == 1253050:
            crystal_casts.append((t, str(row[1])))
        if (ev in ("SPELL_AURA_APPLIED", "SPELL_AURA_REMOVED") and len(row) > 12
                and row[12] == "BUFF" and dest.startswith("Player-")):
            buff_events.append((t, ev, sid, _clean_name(row[10]), str(row[1]), dest))
        if ev == "SPELL_AURA_REMOVED" and sid in (1279512, 1285510) and dest.startswith("Player-"):
            star_debuff_off.append((t, dest, sid))
        # 고급 좌표 (dest 플레이어 위치): SPELL_DAMAGE 계열 25~27번 필드
        if ev == "SPELL_DAMAGE" and len(row) > 27 and str(row[13]).startswith("Player-"):
            try:
                x, y = float(row[26]), float(row[27])
            except (ValueError, TypeError):
                continue
            pos_latest[str(row[13])] = (t, x, y)
            if sid == 1281473:
                star_dmg.append((t, str(row[13]), x, y))
            elif sid == 1281178:
                crit_dmg.append((t, str(row[13]), x, y))

out = []
# (1) 수정 시전 ±4초 내 그 시전자에게 붙거나 떨어진 BUFF
cand = Counter()
for ct, cguid in crystal_casts:
    for bt, bev, sid, name, src, dest in buff_events:
        if dest == cguid and abs(bt - ct) <= 4.0:
            cand[(sid, name, bev, "self" if src == dest else str(src)[:8])] += 1
out.append(f"=== 여명의 수정 시전 {len(crystal_casts)}회 — 시전자 ±4s BUFF 변화 상위 ===")
for key, n in cand.most_common(25):
    out.append(f"{n:5d}  sid={key[0]} {key[1]!r} {key[2]} src={key[3]}")

# (2) 별빛파열: 디버프 해제 시각 근처 폭발 클러스터 → 해제자 위치 vs 피해자 거리
out.append("")
out.append("=== 별빛파열 폭발 클러스터 (해제 ±0.3s 데미지) ===")
for ot, oguid, osid in star_debuff_off:
    hits = [(t2, d, x, y) for (t2, d, x, y) in star_dmg if abs(t2 - ot) <= 0.3]
    if not hits:
        continue
    center = next(((x, y) for (t2, d, x, y) in hits if d == oguid), None)
    if center is None:
        p = pos_latest.get(oguid)
        center = (p[1], p[2]) if p else None
    dists = []
    if center:
        for (t2, d, x, y) in hits:
            dists.append(round(math.hypot(x - center[0], y - center[1]), 1))
    out.append(f"t={ot} sid={osid} hits={len(hits)} 거리(중심={oguid[-8:]}): {sorted(dists)}")

# (3) 임계점: 동시각(0.2s) 클러스터 크기 + 위치 → 서로 거리
out.append("")
out.append("=== 임계점 폭발 클러스터 (0.2s 묶음, 서로거리) ===")
crit_dmg.sort()
i = 0
while i < len(crit_dmg):
    j = i
    while j < len(crit_dmg) and crit_dmg[j][0] - crit_dmg[i][0] <= 0.2:
        j += 1
    group = crit_dmg[i:j]
    if len(group) >= 2:
        pair = []
        for a in range(len(group)):
            for b in range(a + 1, len(group)):
                pair.append(round(math.hypot(group[a][2] - group[b][2], group[a][3] - group[b][3]), 1))
        out.append(f"t={group[0][0]} n={len(group)} 쌍거리={sorted(pair)[:8]}")
    i = j

text = "\n".join(out)
Path("tmp_lura_mech2_out.txt").write_text(text, encoding="utf-8")
print(text[:5000])
