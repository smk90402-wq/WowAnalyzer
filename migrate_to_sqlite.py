"""대용량 JSON 캐시를 SQLite (data/cache.db) 로 마이그레이션.

대상:
  - cache_casts.json   (8MB+)
  - cache_buffs.json   (~6MB)
  - cache_talents.json (31MB!)
  - cache_gear.json
  - cache_source_ids.json
  - cache_fights.json

spell_db.json (~3MB, key-value lookup) 은 JSON 유지 — 자주 안 변하고 작음.

기존 JSON 파일은 백업 폴더로 이동 (data/_json_backup/).
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
BACKUP = DATA / "_json_backup"

SCHEMA = """
CREATE TABLE IF NOT EXISTS casts (
    rid TEXT NOT NULL,
    fid INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    spell_id INTEGER NOT NULL,
    type TEXT
);
CREATE INDEX IF NOT EXISTS idx_casts_rfs ON casts(rid, fid, source_id);
CREATE INDEX IF NOT EXISTS idx_casts_spell ON casts(spell_id);

CREATE TABLE IF NOT EXISTS buffs (
    rid TEXT NOT NULL,
    fid INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    spell_id INTEGER NOT NULL,
    type TEXT,
    stack INTEGER
);
CREATE INDEX IF NOT EXISTS idx_buffs_rfs ON buffs(rid, fid, source_id);

CREATE TABLE IF NOT EXISTS talents (
    rid TEXT NOT NULL,
    fid INTEGER NOT NULL,
    char_name TEXT NOT NULL,
    talent_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_talents_rfc ON talents(rid, fid, char_name);
CREATE INDEX IF NOT EXISTS idx_talents_tid ON talents(talent_id);

CREATE TABLE IF NOT EXISTS gear (
    rid TEXT NOT NULL,
    fid INTEGER NOT NULL,
    char_name TEXT NOT NULL,
    avg_ilvl REAL,
    gear_json TEXT,
    PRIMARY KEY (rid, fid, char_name)
);

CREATE TABLE IF NOT EXISTS source_ids (
    rid TEXT NOT NULL,
    char_name TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    PRIMARY KEY (rid, char_name)
);
CREATE INDEX IF NOT EXISTS idx_source_ids_sid ON source_ids(source_id);

CREATE TABLE IF NOT EXISTS fights (
    rid TEXT NOT NULL,
    fid INTEGER NOT NULL,
    start_ms INTEGER,
    end_ms INTEGER,
    PRIMARY KEY (rid, fid)
);

CREATE TABLE IF NOT EXISTS damage (
    rid TEXT NOT NULL,
    fid INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    spell_guid INTEGER NOT NULL,
    name TEXT,
    icon TEXT,
    total INTEGER
);
CREATE INDEX IF NOT EXISTS idx_damage_rfs ON damage(rid, fid, source_id);
"""


def load_json(p: Path):
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  load fail {p.name}: {e}")
        return None


def migrate(con: sqlite3.Connection) -> None:
    cur = con.cursor()
    cur.executescript(SCHEMA)
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")

    # 캐스트
    t0 = time.time()
    casts = load_json(DATA / "cache_casts.json") or {}
    rows = []
    for key, evs in casts.items():
        if not isinstance(evs, list):
            continue
        parts = key.split(":")
        if len(parts) != 3:
            continue
        try:
            rid, fid, sid = parts[0], int(parts[1]), int(parts[2])
        except (TypeError, ValueError):
            continue
        for e in evs:
            if not isinstance(e, list) or len(e) < 2:
                continue
            try:
                ts = int(e[0]); spell_id = int(e[1])
            except (TypeError, ValueError):
                continue
            tp = e[2] if len(e) > 2 else "cast"
            rows.append((rid, fid, sid, ts, spell_id, tp))
    cur.execute("DELETE FROM casts")
    cur.executemany("INSERT INTO casts (rid, fid, source_id, ts, spell_id, type) VALUES (?,?,?,?,?,?)", rows)
    con.commit()
    print(f"  casts: {len(rows):,} rows ({time.time()-t0:.1f}s)")

    # 버프
    t0 = time.time()
    buffs = load_json(DATA / "cache_buffs.json") or {}
    rows = []
    for key, evs in buffs.items():
        if not isinstance(evs, list):
            continue
        parts = key.split(":")
        if len(parts) != 3:
            continue
        try:
            rid, fid, sid = parts[0], int(parts[1]), int(parts[2])
        except (TypeError, ValueError):
            continue
        for e in evs:
            if not isinstance(e, list) or len(e) < 2:
                continue
            try:
                ts = int(e[0]); spell_id = int(e[1])
            except (TypeError, ValueError):
                continue
            tp = e[2] if len(e) > 2 else ""
            stack = e[3] if len(e) > 3 else None
            rows.append((rid, fid, sid, ts, spell_id, tp, stack))
    cur.execute("DELETE FROM buffs")
    cur.executemany("INSERT INTO buffs (rid, fid, source_id, ts, spell_id, type, stack) VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    print(f"  buffs: {len(rows):,} rows ({time.time()-t0:.1f}s)")

    # 특성
    t0 = time.time()
    talents = load_json(DATA / "cache_talents.json") or {}
    rows = []
    for key, players in talents.items():
        if not isinstance(players, dict):
            continue
        parts = key.split(":")
        if len(parts) != 2:
            continue
        try:
            rid, fid = parts[0], int(parts[1])
        except (TypeError, ValueError):
            continue
        for char, talent_list in players.items():
            if not isinstance(talent_list, list):
                continue
            for tid in talent_list:
                try:
                    rows.append((rid, fid, char, int(tid)))
                except (TypeError, ValueError):
                    continue
    cur.execute("DELETE FROM talents")
    cur.executemany("INSERT INTO talents (rid, fid, char_name, talent_id) VALUES (?,?,?,?)", rows)
    con.commit()
    print(f"  talents: {len(rows):,} rows ({time.time()-t0:.1f}s)")

    # 장비
    t0 = time.time()
    gear = load_json(DATA / "cache_gear.json") or {}
    rows = []
    for key, players in gear.items():
        if not isinstance(players, dict):
            continue
        parts = key.split(":")
        if len(parts) != 2:
            continue
        try:
            rid, fid = parts[0], int(parts[1])
        except (TypeError, ValueError):
            continue
        for char, info in players.items():
            if not isinstance(info, dict):
                continue
            ilvl = info.get("ilvl")
            gear_list = info.get("gear") or []
            rows.append((rid, fid, char, ilvl, json.dumps(gear_list, ensure_ascii=False)))
    cur.execute("DELETE FROM gear")
    cur.executemany("INSERT OR REPLACE INTO gear (rid, fid, char_name, avg_ilvl, gear_json) VALUES (?,?,?,?,?)", rows)
    con.commit()
    print(f"  gear: {len(rows):,} rows ({time.time()-t0:.1f}s)")

    # source_ids
    t0 = time.time()
    srcids = load_json(DATA / "cache_source_ids.json") or {}
    rows = []
    for rid, charmap in srcids.items():
        if not isinstance(charmap, dict):
            continue
        for char, sid in charmap.items():
            if not isinstance(sid, int):
                continue
            rows.append((rid, char, sid))
    cur.execute("DELETE FROM source_ids")
    cur.executemany("INSERT OR REPLACE INTO source_ids (rid, char_name, source_id) VALUES (?,?,?)", rows)
    con.commit()
    print(f"  source_ids: {len(rows):,} ({time.time()-t0:.1f}s)")

    # fights
    t0 = time.time()
    fights = load_json(DATA / "cache_fights.json") or {}
    rows = []
    for rid, fmap in fights.items():
        if not isinstance(fmap, dict):
            continue
        for fid_s, window in fmap.items():
            if not isinstance(window, list) or len(window) != 2:
                continue
            try:
                rows.append((rid, int(fid_s), int(window[0]), int(window[1])))
            except (TypeError, ValueError):
                continue
    cur.execute("DELETE FROM fights")
    cur.executemany("INSERT OR REPLACE INTO fights (rid, fid, start_ms, end_ms) VALUES (?,?,?,?)", rows)
    con.commit()
    print(f"  fights: {len(rows):,} ({time.time()-t0:.1f}s)")

    # damage (v2_cache_damage.json)
    t0 = time.time()
    damage = load_json(DATA / "v2_cache_damage.json") or {}
    rows = []
    for key, entries in damage.items():
        if not isinstance(entries, list):
            continue
        parts = key.split(":")
        if len(parts) != 3:
            continue
        try:
            rid, fid, sid = parts[0], int(parts[1]), int(parts[2])
        except (TypeError, ValueError):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            gid = e.get("guid")
            if not isinstance(gid, int):
                continue
            rows.append((rid, fid, sid, gid, e.get("name") or "", e.get("icon") or "", int(e.get("total") or 0)))
    cur.execute("DELETE FROM damage")
    cur.executemany("INSERT INTO damage (rid, fid, source_id, spell_guid, name, icon, total) VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    print(f"  damage: {len(rows):,} ({time.time()-t0:.1f}s)")

    cur.execute("VACUUM")
    con.commit()

    db_size = DB.stat().st_size / 1024 / 1024
    print(f"\nDB 사이즈: {db_size:.1f} MB")


def main() -> None:
    print(f"=== SQLite migration → {DB} ===")
    con = sqlite3.connect(str(DB))
    migrate(con)
    con.close()
    print("\n완료. (옛 JSON 파일들은 그대로 유지 — gui.py 가 SQLite 쓰도록 전환 후 _json_backup 으로 이동 권장)")


if __name__ == "__main__":
    main()
