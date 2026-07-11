# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, ".")
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from collections import Counter
from app import local_replay

local_replay._frames_cache.clear()
rows = local_replay.list_replays()["rows"]
for row in rows[:2]:
    f = local_replay.replay_frames(row["id"])
    hit = [e for e in f["boss_events"] if e["kind"] == "hit" and e.get("dest_id")]
    c = Counter(e["spell"] for e in hit)
    dur = f["meta"]["duration_s"]
    print(f"{row['encounter']} (길이 {dur:.0f}s) boss_events {len(f['boss_events'])}, hit {len(hit)}")
    for sp, n in c.most_common(4):
        ts = sorted(e["t"] for e in hit if e["spell"] == sp)
        waves = [[ts[0]]]
        for a in ts[1:]:
            if a - waves[-1][-1] <= 3: waves[-1].append(a)
            else: waves.append([a])
        last = max(ts)
        sizes = [len(w) for w in waves][:12]
        print(f"   {sp}: {n}개, 웨이브 {len(waves)}개 크기{sizes}, 마지막 {last:.0f}s ({last/dur*100:.0f}% 지점)")
