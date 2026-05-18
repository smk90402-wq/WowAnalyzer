"""V2 GraphQL 기반 통합 데이터 페처 + 디스크 캐시.

V1 enrich_* 스크립트들을 대체한다. 한 fight 의 talents/gear/events 를
모두 V2 GraphQL 한 두 콜로 가져온다.

캐시 (cross-session, JSON):
  - data/v2_cache_report_meta.json  : {rid: {fights:[...], actors:{char:sourceID}}}
  - data/v2_cache_player_fight.json : {"rid:fid:char": {talents:[...], gear:[...]}}
  - data/v2_cache_events.json       : {"rid:fid:sid": {casts:[...], buffs:[...]}}

사용법 (예):
    from wcl_v2_data import V2Data
    d = V2Data()
    meta = d.report_meta(rid)               # fights + actors
    pdata = d.player_fight(rid, fid, char)  # talents + gear
    events = d.events(rid, fid, char)        # casts + buffs
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from wcl_v2 import WCLV2

log = logging.getLogger("wcl_v2_data")

DATA = Path(__file__).parent / "data"
CACHE_META = DATA / "v2_cache_report_meta.json"
CACHE_PFIGHT = DATA / "v2_cache_player_fight.json"
CACHE_EVENTS = DATA / "v2_cache_events.json"
CACHE_DAMAGE = DATA / "v2_cache_damage.json"


# ── GraphQL 쿼리들 ──────────────────────────────────────────────────────────

# report 메타: fight 시간 + 친구목록 (sourceID 포함)
Q_REPORT_META = """
query($code: String!) {
  reportData {
    report(code: $code) {
      fights(killType: Kills) {
        id startTime endTime encounterID difficulty
      }
      masterData(translate: true) {
        actors(type: "Player") {
          id name server type subType
        }
      }
    }
  }
}
"""

# 한 fight 의 playerDetails (talents + gear). includeCombatantInfo 필수 (기본 false)
Q_PLAYER_DETAILS = """
query($code: String!, $fightIDs: [Int]!) {
  reportData {
    report(code: $code) {
      playerDetails(fightIDs: $fightIDs, includeCombatantInfo: true)
    }
  }
}
"""

# casts events (paginated via nextPageTimestamp)
Q_EVENTS_CASTS = """
query($code: String!, $start: Float!, $end: Float!, $sid: Int!) {
  reportData {
    report(code: $code) {
      events(
        dataType: Casts
        startTime: $start
        endTime: $end
        sourceID: $sid
        hostilityType: Friendlies
      ) { data nextPageTimestamp }
    }
  }
}
"""

Q_EVENTS_BUFFS = """
query($code: String!, $start: Float!, $end: Float!, $sid: Int!) {
  reportData {
    report(code: $code) {
      events(
        dataType: Buffs
        startTime: $start
        endTime: $end
        sourceID: $sid
        hostilityType: Friendlies
      ) { data nextPageTimestamp }
    }
  }
}
"""

# 데미지 합산 테이블 — events 보다 효율적, 스펠별 total/percentage
Q_DAMAGE_TABLE = """
query($code: String!, $start: Float!, $end: Float!, $sid: Int!) {
  reportData {
    report(code: $code) {
      table(
        dataType: DamageDone
        startTime: $start
        endTime: $end
        sourceID: $sid
        hostilityType: Friendlies
      )
    }
  }
}
"""


def _load_json(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


class V2Data:
    def __init__(self) -> None:
        self.cli = WCLV2()
        self.meta = _load_json(CACHE_META)
        self.pfight = _load_json(CACHE_PFIGHT)
        self.events = _load_json(CACHE_EVENTS)
        self.damage = _load_json(CACHE_DAMAGE)

    # ── 보관 ──────────────────────────────────────────────────────────────
    def flush(self) -> None:
        _save_json(CACHE_META, self.meta)
        _save_json(CACHE_PFIGHT, self.pfight)
        _save_json(CACHE_EVENTS, self.events)
        _save_json(CACHE_DAMAGE, self.damage)

    # ── 데미지 테이블 (스펠별 합산) ────────────────────────────────────────
    def damage_table(self, rid: str, fid: int, char: str) -> list | None:
        """[{guid, name, icon, total, ...}] for one (rid, fid, char). 캐시."""
        pf = self.player_fight(rid, fid, char)
        if not pf or not isinstance(pf, dict):
            return None
        sid = pf.get("sourceID")
        if not isinstance(sid, int):
            return None
        key = f"{rid}:{fid}:{sid}"
        if key in self.damage:
            return self.damage[key]
        meta = self.report_meta(rid)
        fights = (meta or {}).get("fights") or []
        f = next((x for x in fights if x.get("id") == int(fid)), None)
        if not f:
            self.damage[key] = None
            return None
        try:
            d = self.cli.query(Q_DAMAGE_TABLE, {
                "code": rid, "start": float(f["startTime"]),
                "end": float(f["endTime"]), "sid": int(sid),
            })
        except Exception as e:
            log.warning("damage table fail %s: %s", key, e)
            self.damage[key] = None
            return None
        tbl = (((d or {}).get("reportData") or {}).get("report") or {}).get("table") or {}
        # JSON scalar — entries 는 보통 tbl["data"]["entries"]
        inner = tbl.get("data") if isinstance(tbl, dict) and "data" in tbl else tbl
        entries = inner.get("entries") if isinstance(inner, dict) else None
        if not isinstance(entries, list):
            self.damage[key] = []
            return []
        compact = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            compact.append({
                "guid": e.get("guid"),
                "name": e.get("name") or "",
                "total": e.get("total") or 0,
                "icon": e.get("icon") or "",
            })
        self.damage[key] = compact
        return compact

    # ── report 메타 (fight + 친구) ─────────────────────────────────────────
    def report_meta(self, rid: str) -> dict | None:
        """{fights: [{id, startTime, endTime, encounterID, difficulty}],
            actors: {name: sourceID}}"""
        if rid in self.meta:
            return self.meta[rid]
        try:
            d = self.cli.query(Q_REPORT_META, {"code": rid})
        except Exception as e:
            log.warning("report_meta fail %s: %s", rid, e)
            self.meta[rid] = None
            return None
        rep = (((d or {}).get("reportData") or {}).get("report") or {})
        if not rep:
            self.meta[rid] = None
            return None
        fights = rep.get("fights") or []
        master = rep.get("masterData") or {}
        actors = master.get("actors") or []
        actors_map = {a.get("name"): a.get("id") for a in actors if a.get("name") and isinstance(a.get("id"), int)}
        out = {
            "fights": [{
                "id": f.get("id"),
                "startTime": f.get("startTime"),
                "endTime": f.get("endTime"),
                "encounterID": f.get("encounterID"),
                "difficulty": f.get("difficulty"),
            } for f in fights],
            "actors": actors_map,
        }
        self.meta[rid] = out
        return out

    # ── playerDetails (talents + gear) ─────────────────────────────────────
    def player_fight(self, rid: str, fid: int, char: str) -> dict | None:
        """{talents: [int], gear: [{id, slot, ilvl, ...}]}  for one (rid, fid, char)."""
        key = f"{rid}:{fid}:{char}"
        if key in self.pfight:
            return self.pfight[key]
        try:
            d = self.cli.query(Q_PLAYER_DETAILS, {
                "code": rid, "fightIDs": [int(fid)],
            })
        except Exception as e:
            log.warning("player_fight fail %s: %s", key, e)
            self.pfight[key] = None
            return None
        rep = (((d or {}).get("reportData") or {}).get("report") or {})
        pd_ = (rep.get("playerDetails") or {})
        # V2 playerDetails 는 JSON scalar — {data: {playerDetails: {dps:[...], tanks:[...], healers:[...]}}}
        actual = pd_.get("data", {}).get("playerDetails") if isinstance(pd_, dict) and "data" in pd_ else pd_
        # 캐릭터 찾기
        target = None
        if isinstance(actual, dict):
            for role in ("dps", "tanks", "healers"):
                for p in actual.get(role, []) or []:
                    if p.get("name") == char:
                        target = p; break
                if target: break
        if not target:
            self.pfight[key] = None
            return None
        ci = target.get("combatantInfo") or {}
        talent_tree = ci.get("talentTree") or []
        talent_ids = []
        node_ids = []
        talent_points: dict[str, int] = {}  # str(talent_id) → rank (points spent, 1 or 2)
        for t in talent_tree:
            if isinstance(t, dict):
                tid = t.get("id")
                if tid is not None:
                    talent_ids.append(tid)
                    rank = t.get("rank")
                    if isinstance(rank, int) and rank >= 1:
                        talent_points[str(tid)] = rank
                nid = t.get("nodeID")
                if nid is not None:
                    node_ids.append(nid)
        gear = ci.get("gear") or []
        compact_gear = []
        for g in gear:
            if isinstance(g, dict):
                compact_gear.append({
                    "slot": g.get("slot"),
                    "id": g.get("id"),
                    "name": g.get("name") or "",
                    "ilvl": g.get("itemLevel"),
                    "gems": [(x.get("id") if isinstance(x, dict) else None)
                             for x in (g.get("gems") or [])],
                    "ench": g.get("permanentEnchant"),
                    "bonus": list(g.get("bonusIDs") or []),
                })
        # 스탯: {name: rating} (min == max 보통, min 만 사용)
        stats_raw = ci.get("stats") or {}
        stats_compact: dict[str, int] = {}
        if isinstance(stats_raw, dict):
            for k, v in stats_raw.items():
                if isinstance(v, dict):
                    mn = v.get("min")
                    if isinstance(mn, (int, float)):
                        stats_compact[k] = int(mn)
                elif isinstance(v, (int, float)):
                    stats_compact[k] = int(v)
        out = {"talents": talent_ids, "talent_points": talent_points,
               "nodes": node_ids, "gear": compact_gear,
               "stats": stats_compact,
               "sourceID": target.get("id")}
        self.pfight[key] = out
        return out

    # ── events (casts / buffs) ─────────────────────────────────────────────
    def _fetch_events(self, query: str, rid: str, sid: int,
                      start: float, end: float) -> list:
        out = []
        cur = float(start)
        for _ in range(20):
            d = self.cli.query(query, {
                "code": rid, "start": cur, "end": float(end), "sid": int(sid),
            })
            evs_obj = (((d or {}).get("reportData") or {}).get("report") or {}).get("events") or {}
            events = evs_obj.get("data") or []
            out.extend(events)
            nxt = evs_obj.get("nextPageTimestamp")
            if not nxt or nxt <= cur:
                break
            cur = float(nxt)
        return out

    def events_for(self, rid: str, fid: int, char: str) -> dict | None:
        """{casts: [[ts, gid, type], ...], buffs: [[ts, gid, type, stack?], ...]}"""
        # sourceID 필요 → player_fight 호출
        pf = self.player_fight(rid, fid, char)
        if not pf or not isinstance(pf, dict):
            return None
        sid = pf.get("sourceID")
        if not isinstance(sid, int):
            return None

        key = f"{rid}:{fid}:{sid}"
        if key in self.events:
            return self.events[key]

        meta = self.report_meta(rid)
        fights = (meta or {}).get("fights") or []
        f = next((x for x in fights if x.get("id") == int(fid)), None)
        if not f:
            self.events[key] = None
            return None
        start, end = f["startTime"], f["endTime"]

        try:
            casts_raw = self._fetch_events(Q_EVENTS_CASTS, rid, sid, start, end)
            buffs_raw = self._fetch_events(Q_EVENTS_BUFFS, rid, sid, start, end)
        except Exception as e:
            log.warning("events fail %s: %s", key, e)
            self.events[key] = None
            return None

        # V2 events: {"timestamp": int, "type": str, "abilityGameID": int, ...}
        casts = [[e.get("timestamp"), e.get("abilityGameID") or 0, e.get("type") or "cast"]
                 for e in casts_raw if e.get("abilityGameID")]
        buffs = []
        for e in buffs_raw:
            gid = e.get("abilityGameID")
            if not gid:
                continue
            rec = [e.get("timestamp"), gid, e.get("type") or ""]
            if e.get("stack") is not None:
                rec.append(e.get("stack"))
            buffs.append(rec)

        out = {"casts": casts, "buffs": buffs}
        self.events[key] = out
        return out


if __name__ == "__main__":
    # python wcl_v2_data.py <report_code>  — 빠른 smoke test
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) < 2:
        print("usage: python wcl_v2_data.py <report_code>")
        sys.exit(1)
    rid = sys.argv[1]
    d = V2Data()
    meta = d.report_meta(rid)
    print(f"fights: {len(meta['fights']) if meta else 0}")
    print(f"actors: {len(meta['actors']) if meta else 0}")
    if meta and meta["fights"]:
        f = meta["fights"][0]
        # 첫 actor 한 명
        if meta["actors"]:
            char = next(iter(meta["actors"]))
            pf = d.player_fight(rid, f["id"], char)
            if pf:
                print(f"{char}: talents={len(pf['talents'])} gear={len(pf['gear'])}")
            ev = d.events_for(rid, f["id"], char)
            if ev:
                print(f"  events: casts={len(ev['casts'])} buffs={len(ev['buffs'])}")
    d.flush()
    print("rate:", d.cli.points_left())
