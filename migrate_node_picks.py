"""v2_cache_player_fight.json 의 'nodes' 필드를 SQLite picks_nodes 테이블로.

WCL combatantInfo.talentTree[].nodeID == Blizzard talent-tree node.id 가 매칭됨.
기존 talents 테이블 (talent_id 만 저장) 으론 트리 매칭 불가 → 별도 테이블 필요.

스키마:
  picks_nodes (rid, fid, char_name, node_id)  -- 한 캐릭이 찍은 노드 ID 들
"""
from __future__ import annotations
import json, sqlite3, sys, time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path(__file__).parent / "data"
DB = DATA / "cache.db"
SRC = DATA / "v2_cache_player_fight.json"


def main() -> None:
    if not SRC.exists():
        sys.exit(f"{SRC} 없음")
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS picks_nodes (
        rid TEXT NOT NULL,
        fid INTEGER NOT NULL,
        char_name TEXT NOT NULL,
        node_id INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_picks_nodes_rfc ON picks_nodes(rid, fid, char_name);
    CREATE INDEX IF NOT EXISTS idx_picks_nodes_node ON picks_nodes(node_id);
    """)

    t0 = time.time()
    print(f"loading {SRC.name}...")
    data = json.loads(SRC.read_text(encoding="utf-8"))
    print(f"  loaded {len(data):,} entries in {time.time()-t0:.1f}s")

    rows = []
    skipped_no_nodes = 0
    for key, v in data.items():
        if not isinstance(v, dict):
            continue
        parts = key.split(":")
        if len(parts) < 3:
            continue
        rid = parts[0]
        try:
            fid = int(parts[1])
        except (TypeError, ValueError):
            continue
        char = ":".join(parts[2:])
        nodes = v.get("nodes") or []
        if not nodes:
            skipped_no_nodes += 1
            continue
        for nid in nodes:
            try:
                rows.append((rid, fid, char, int(nid)))
            except (TypeError, ValueError):
                continue

    cur.execute("DELETE FROM picks_nodes")
    t0 = time.time()
    cur.executemany("INSERT INTO picks_nodes (rid, fid, char_name, node_id) VALUES (?,?,?,?)", rows)
    con.commit()
    print(f"  inserted {len(rows):,} node-picks in {time.time()-t0:.1f}s")
    print(f"  skipped (no nodes field): {skipped_no_nodes}")
    cur.execute("VACUUM")
    con.commit()
    con.close()


if __name__ == "__main__":
    main()
