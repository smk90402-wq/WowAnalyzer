# 5차: 임계점 이중피격 검증 — 같은 클러스터에서 같은 플레이어가 2회 맞았나
#       (겹침 쌍 거리 vs 이중피격 여부로 반경 하한/상한 도출)
import math
from collections import Counter
from pathlib import Path

from app.local_replay import (_csv_row, _LOG_LINE_RE, _parse_log_ts, _clean_name,
                              _encounter_offsets)

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")
encs = [e for e in _encounter_offsets(LOG) if e.get("encounter_id") == 3183]

out = []
double_hits = []   # (풀, t, dest, 두 히트 시간차)
near_pairs = []    # (풀, t, 거리, 둘다 이중피격?)

for idx, enc in enumerate(encs, 1):
    start_off = enc["start_off"]
    end_off = enc.get("end_off") or 0
    start_dt = enc["_start_dt"]
    crit = []
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
            if (not row or len(row) < 28 or row[0] != "SPELL_DAMAGE"):
                continue
            try:
                sid = int(row[9])
            except (ValueError, TypeError):
                continue
            if sid != 1281178 or not str(row[12]).startswith("Player-"):
                continue
            try:
                x, y = float(row[26]), float(row[27])
            except (ValueError, TypeError):
                continue
            crit.append((t, str(row[12]), _clean_name(row[6]), x, y))

    crit.sort()
    i = 0
    while i < len(crit):
        j = i
        while j < len(crit) and crit[j][0] - crit[i][0] <= 0.6:
            j += 1
        group = crit[i:j]
        i = j
        if len(group) < 2:
            continue
        cnt = Counter(g[1] for g in group)
        doubled = {g for g, n in cnt.items() if n >= 2}
        for g in doubled:
            hits = [c for c in group if c[1] == g]
            double_hits.append((idx, hits[0][0], hits[0][2], round(hits[-1][0] - hits[0][0], 2)))
        # 5yd 이내 쌍 → 이중피격 여부 기록
        for a in range(len(group)):
            for b in range(a + 1, len(group)):
                if group[a][1] == group[b][1]:
                    continue
                d = math.hypot(group[a][3] - group[b][3], group[a][4] - group[b][4])
                if d <= 6.5:
                    near_pairs.append((idx, group[a][0], round(d, 1),
                                       group[a][1] in doubled or group[b][1] in doubled,
                                       group[a][2][:8], group[b][2][:8]))

out.append(f"=== 이중피격 {len(double_hits)}건 ===")
for pull, t, name, dt in double_hits[:30]:
    out.append(f"풀{pull} t={t} {name} (시간차 {dt}s)")
out.append("")
out.append(f"=== 6.5yd 이내 쌍 {len(near_pairs)}건 (거리, 이중피격여부) ===")
for pull, t, d, dbl, n1, n2 in near_pairs[:40]:
    out.append(f"풀{pull} t={t} d={d}yd 이중피격={dbl} ({n1}/{n2})")

text = "\n".join(out)
Path("tmp_lura_mech5_out.txt").write_text(text, encoding="utf-8")
print(text[:4000])
