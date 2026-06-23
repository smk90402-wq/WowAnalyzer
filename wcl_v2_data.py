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

import errno
import json
import logging
import shutil
import sys
import time
from pathlib import Path

from wcl_v2 import WCLV2

log = logging.getLogger("wcl_v2_data")

DEFAULT_DATA = Path(__file__).parent / "data"


# ── GraphQL 쿼리들 ──────────────────────────────────────────────────────────

# report 메타: fight 시간 + 친구목록 (sourceID 포함)
# killType: Encounters → kill + wipe 둘 다 포함 (trash 제외). 영웅 wipe / 신화 학습각 다 표시.
Q_REPORT_META = """
query($code: String!) {
  reportData {
    report(code: $code) {
      fights(killType: Encounters) {
        id startTime endTime encounterID difficulty kill name friendlyPlayers
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
        targetID: $sid
        hostilityType: Friendlies
      ) { data nextPageTimestamp }
    }
  }
}
"""

# 외부 PI (사제의 마력 주입, spell 10060) — 비사제 캐릭이 받은 거 추적용
# 본인 source 가 아닌 이벤트 (다른 priest 가 본인을 target 으로) — targetID 필터.
Q_EVENTS_PI_TARGET = """
query($code: String!, $start: Float!, $end: Float!, $sid: Int!) {
  reportData {
    report(code: $code) {
      events(
        dataType: Buffs
        startTime: $start
        endTime: $end
        targetID: $sid
        abilityID: 10060
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
    payload = json.dumps(obj, ensure_ascii=False)
    last_exc: Exception | None = None
    minimum_free = max(len(payload) * 3, len(payload) + 512 * 1024 * 1024)
    for _ in range(10):
        tmp = p.with_name(f"{p.name}.{time.time_ns()}.tmp")
        try:
            free = shutil.disk_usage(p.parent).free
            if free < minimum_free:
                raise OSError(
                    errno.ENOSPC,
                    f"not enough free disk to save {p.name}: "
                    f"free={free:,}, required={minimum_free:,}",
                )
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(p)
            return
        except OSError as exc:
            last_exc = exc
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            if exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) == 112:
                raise
            time.sleep(2.0)
    if last_exc:
        raise last_exc


class V2Data:
    def __init__(self, data_dir: Path | None = None) -> None:
        """data_dir: 캐시 JSON 들의 위치. None 이면 wcl_v2_data.py 옆 'data/'.

        **중요:** frozen (PyInstaller) 빌드에서는 Path(__file__).parent 가
        _internal/ 로 resolve 되어 잘못된 경로를 본다. gui.py 가 동적으로
        찾은 DATA_DIR 을 항상 명시적으로 넘겨줄 것.
        """
        self.cli = WCLV2()
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA
        self._cache_meta = self.data_dir / "v2_cache_report_meta.json"
        self._cache_pfight = self.data_dir / "v2_cache_player_fight.json"
        self._cache_events = self.data_dir / "v2_cache_events.json"
        self._cache_damage = self.data_dir / "v2_cache_damage.json"
        self._cache_prepull = self.data_dir / "v2_cache_prepull_buffs.json"
        self._cache_pi = self.data_dir / "v2_cache_pi_received.json"
        self.meta = _load_json(self._cache_meta)
        self.pfight = _load_json(self._cache_pfight)
        self._events = None   # lazy: events 캐시는 거대(수백MB) → 처음 쓸 때만 로딩
        self.damage = _load_json(self._cache_damage)
        self.prepull = _load_json(self._cache_prepull)
        self.pi_received = _load_json(self._cache_pi)

    @property
    def events(self) -> dict:
        """events 캐시 lazy-load — gear/장비창 등 events 불필요한 경로는 안 건드림."""
        if self._events is None:
            self._events = _load_json(self._cache_events)
        return self._events

    # ── 보관 ──────────────────────────────────────────────────────────────
    def flush(self) -> None:
        _save_json(self._cache_meta, self.meta)
        _save_json(self._cache_pfight, self.pfight)
        if self._events is not None:
            _save_json(self._cache_events, self._events)
        _save_json(self._cache_damage, self.damage)
        _save_json(self._cache_prepull, self.prepull)
        _save_json(self._cache_pi, self.pi_received)

    # ── 외부 PI (사제 → 본인) — 비사제 캐릭만 의미 ────────────────────────
    def external_pi_buffs(self, rid: str, fid: int, char: str) -> list | None:
        """본인 (sid) 을 target 으로 받은 마력 주입(10060) buff events.

        Returns: [[ts, 10060, type], ...]  (cast event 와 동일 구조)
        """
        pf = self.player_fight(rid, fid, char)
        if not pf or not isinstance(pf, dict):
            return None
        sid = pf.get("sourceID")
        if not isinstance(sid, int):
            return None
        key = f"{rid}:{fid}:{sid}"
        if key in self.pi_received:
            return self.pi_received[key]
        meta = self.report_meta(rid)
        fights = (meta or {}).get("fights") or []
        f = next((x for x in fights if x.get("id") == int(fid)), None)
        if not f:
            self.pi_received[key] = None
            return None
        try:
            d = self.cli.query(Q_EVENTS_PI_TARGET, {
                "code": rid, "start": float(f["startTime"]),
                "end": float(f["endTime"]), "sid": int(sid),
            })
        except Exception as e:
            log.warning("external_pi fetch fail %s: %s", key, e)
            self.pi_received[key] = None
            return None
        evs_obj = (((d or {}).get("reportData") or {}).get("report") or {}).get("events") or {}
        events = evs_obj.get("data") or []
        out: list[list] = []
        for e in events:
            if not isinstance(e, dict):
                continue
            ts = e.get("timestamp")
            etype = e.get("type") or ""
            gid = e.get("abilityGameID") or 10060
            if ts is None or not etype.startswith(("apply", "remove", "refresh")):
                continue
            out.append([int(ts), int(gid), etype])
        self.pi_received[key] = out
        return out

    # ── pre-pull buffs (음식/영약/오일/숫돌) ──────────────────────────────
    def pre_pull_buffs(self, rid: str, fid: int, char: str,
                       window_sec: int = 600) -> list[dict] | None:
        """전투 시작 N초 전 ~ 전투 시작 5초 후 사이의 unique applybuff events.

        Returns: [{spell_id, ts}] (ts 가 fight.startTime 이전이면 pre-pull).
        결과는 v2_cache_prepull_buffs.json 에 캐시 (key = rid:fid:sid).
        """
        pf = self.player_fight(rid, fid, char)
        if not pf or not isinstance(pf, dict):
            return None
        sid = pf.get("sourceID")
        if not isinstance(sid, int):
            return None
        key = f"{rid}:{fid}:{sid}"
        if key in self.prepull:
            return self.prepull[key]
        meta = self.report_meta(rid)
        fights = (meta or {}).get("fights") or []
        f = next((x for x in fights if x.get("id") == int(fid)), None)
        if not f:
            self.prepull[key] = None
            return None
        start = float(f["startTime"])
        try:
            d = self.cli.query(Q_EVENTS_BUFFS, {
                "code": rid, "start": start - window_sec * 1000,
                "end": start + 5000, "sid": int(sid),
            })
        except Exception as e:
            log.warning("pre_pull_buffs fetch fail %s: %s", key, e)
            self.prepull[key] = None
            return None
        evs_obj = (((d or {}).get("reportData") or {}).get("report") or {}).get("events") or {}
        events = evs_obj.get("data") or []
        seen: set[int] = set()
        out: list[dict] = []
        for e in events:
            if not isinstance(e, dict):
                continue
            if not (e.get("type") or "").startswith("apply"):
                continue
            sp = e.get("abilityGameID")
            if not isinstance(sp, int) or sp in seen:
                continue
            seen.add(sp)
            ts = e.get("timestamp")
            out.append({"spell_id": sp, "ts": int(ts) if isinstance(ts, (int, float)) else None})
        self.prepull[key] = out
        return out

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
            cached = self.meta[rid]
            if cached is None:
                return None                        # 이전 페치 실패 — 재시도 안 함
            fl = cached.get("fights") if isinstance(cached, dict) else None
            # friendlyPlayers 보유(최신) or fights 없는 정상 캐시면 그대로, 아니면 재페치
            if not fl or all(isinstance(f, dict) and "friendlyPlayers" in f for f in fl):
                return cached
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
                "kill": f.get("kill"),
                "name": f.get("name"),
                "friendlyPlayers": f.get("friendlyPlayers") or [],
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
            cached = self.events[key]
            # 새 schema 체크: buff record 4번째 요소 = sourceID (int).
            # Old schema (length 3) 면 무효화 → 재페치 (외부 버프 필터링용).
            if isinstance(cached, dict):
                buffs = cached.get("buffs") or []
                if not buffs or (isinstance(buffs[0], list) and len(buffs[0]) >= 4):
                    return cached
                log.info("events cache %s old schema (no buff sourceID) — re-fetch", key)
                del self.events[key]
            elif cached is None:
                return cached

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

        # V2 events: {"timestamp": int, "type": str, "abilityGameID": int, "sourceID": int, ...}
        casts = [[e.get("timestamp"), e.get("abilityGameID") or 0, e.get("type") or "cast"]
                 for e in casts_raw if e.get("abilityGameID")]
        # buffs: [ts, gid, type, src, stack?]. src 는 buff caster (외부 버프 필터링용).
        buffs = []
        for e in buffs_raw:
            gid = e.get("abilityGameID")
            if not gid:
                continue
            src = e.get("sourceID")
            rec = [e.get("timestamp"), gid, e.get("type") or "",
                   int(src) if isinstance(src, int) else 0]
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
