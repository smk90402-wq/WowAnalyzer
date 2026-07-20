# 4차: 전체 르우라 풀 스캔
#  (1) 1284527 오라 창 vs 1253050 시전 상관 (수정 담당 마커 검증)
#  (2) 임계점 1281178 겹침 클러스터 전수 (반경 실측)
#  (3) 별빛파열 1281473 국지 겹침 (레이드 전체 폭발 제외)
import math
from collections import defaultdict
from pathlib import Path

from app.local_replay import (_csv_row, _LOG_LINE_RE, _parse_log_ts, _clean_name,
                              _encounter_offsets)

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")

encs = [e for e in _encounter_offsets(LOG) if e.get("encounter_id") == 3183]
print(f"르우라 풀 {len(encs)}개")

out = []
corr_done = False
all_crit_pairs = []
all_star_local = []

for idx, enc in enumerate(encs, 1):
    start_off = enc["start_off"]
    end_off = enc.get("end_off") or 0
    start_dt = enc["_start_dt"]
    crit = []
    star = []
    aura527 = []
    casts050 = []
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
            if not row or len(row) < 11 or not row[0].startswith("SPELL"):
                continue
            ev = row[0]
            try:
                sid = int(row[9])
            except (ValueError, TypeError):
                continue
            if sid == 1284527 and ev in ("SPELL_AURA_APPLIED", "SPELL_AURA_REMOVED"):
                aura527.append((t, ev, str(row[5])))
                names[str(row[5])] = _clean_name(row[6]) if len(row) > 6 else ""
            elif sid == 1253050 and ev == "SPELL_CAST_SUCCESS":
                casts050.append((t, str(row[1])))
                names[str(row[1])] = _clean_name(row[2]) if len(row) > 2 else ""
            elif (ev == "SPELL_DAMAGE" and sid in (1281178, 1281473)
                  and len(row) > 27 and str(row[12]).startswith("Player-")):
                try:
                    x, y = float(row[26]), float(row[27])
                except (ValueError, TypeError):
                    continue
                (crit if sid == 1281178 else star).append((t, str(row[12]), x, y))

    # (1) 상관 — 첫 풀에서만 상세 출력
    if not corr_done and aura527:
        corr_done = True
        out.append(f"--- 풀{idx} 1284527 오라 vs 1253050 시전 ---")
        for t, ev, g in aura527:
            near = [f"{ct}s" for ct, cg in casts050 if cg == g and abs(ct - t) <= 30]
            out.append(f"  {t:7.2f}s {ev[11:]:8s} {names.get(g, g)[:12]:12s} 시전근접={near}")

    # (2)(3) 클러스터
    def clusters(events, gap):
        events.sort()
        i = 0
        res = []
        while i < len(events):
            j = i
            while j < len(events) and events[j][0] - events[i][0] <= gap:
                j += 1
            res.append(events[i:j])
            i = j
        return res

    for group in clusters(crit, 0.25):
        if len(group) >= 2:
            pairs = sorted(round(math.hypot(a[2] - b[2], a[3] - b[3]), 1)
                           for ai, a in enumerate(group) for b in group[ai + 1:])
            all_crit_pairs.append((idx, group[0][0], len(group), pairs[:6]))
    for group in clusters(star, 0.3):
        if 2 <= len(group) <= 6:   # 레이드 전체 폭발(>=8) 제외
            pairs = sorted(round(math.hypot(a[2] - b[2], a[3] - b[3]), 1)
                           for ai, a in enumerate(group) for b in group[ai + 1:])
            all_star_local.append((idx, group[0][0], len(group), pairs[:6]))

out.append("")
out.append(f"=== 임계점 겹침 클러스터 (전체 {len(all_crit_pairs)}건) ===")
for pull, t, n, pairs in all_crit_pairs[:40]:
    out.append(f"풀{pull} t={t} n={n} 쌍거리={pairs}")
out.append("")
out.append(f"=== 별빛파열 국지 겹침 (전체 {len(all_star_local)}건) ===")
for pull, t, n, pairs in all_star_local[:40]:
    out.append(f"풀{pull} t={t} n={n} 쌍거리={pairs}")

text = "\n".join(out)
Path("tmp_lura_mech4_out.txt").write_text(text, encoding="utf-8")
print(text[:6000])
