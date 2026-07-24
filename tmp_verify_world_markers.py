# 바닥징(WORLD_MARKER) 파서 검증 — 르우라 로그 전체 이벤트 + 풀18 구간 재구성
import time
from pathlib import Path

from app.local_replay import (_world_marker_events, _world_marker_windows,
                              _encounter_offsets)

LOG = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt")
t0 = time.time()
events = _world_marker_events(LOG)
print(f"스캔 {time.time()-t0:.1f}s, 이벤트 {len(events)}개")
for ts, kind, idx, x, y, zone in events:
    print(f"  {ts} {kind} idx={idx} ({x},{y}) zone={zone}")

encs = [e for e in _encounter_offsets(LOG) if e.get("encounter_id") == 3183]
enc = encs[-1]
wins = _world_marker_windows(LOG, enc["_start_dt"], enc.get("duration_s") or 500,
                             int(enc.get("instance_id") or 0))
print(f"\n풀{len(encs)}(마지막) start={enc['_start_dt']} dur={enc.get('duration_s')} inst={enc.get('instance_id')}")
for w in wins:
    print(f"  idx={w['i']} ({w['x']},{w['y']}) t={w['s']}~{w['e']}")

# 미러 로그(072326_003721)로 REMOVED 처리도 확인
LOG2 = Path(r"C:\Users\MKSEORTV\Desktop\WowAnalyzer\data\cctv_r2\logs\WoWCombatLog-072326_003721.txt")
if LOG2.exists():
    t0 = time.time()
    ev2 = _world_marker_events(LOG2)
    placed = sum(1 for e in ev2 if e[1] == "placed")
    removed = sum(1 for e in ev2 if e[1] == "removed")
    print(f"\n미러 로그: 스캔 {time.time()-t0:.1f}s, placed={placed} removed={removed}")
