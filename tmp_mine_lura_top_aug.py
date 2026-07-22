"""TOP 증강 기원사(Augmentation Evoker) — 르우라(한밤의 도래, 3183 신화) 실측.

- characterRankings(dps) top ~25 킬 → 판별 쿨기/방어기/물약/사망 실측
- 핵심 질문: 증강이 여명의 수정('일렁이는 빛' 1253031)을 P3에서 드는가?
  들면 영겁의 숨결 타이밍과 어떤 관계인가?
- 스펠 ID는 기억에 의존하지 않고 casts table 이름 + data/spell_db.json 으로 확정.

사용: python tmp_mine_lura_top_aug.py explore   → 처음 2판 상세 관측(ID/이벤트타입 확정)
      python tmp_mine_lura_top_aug.py           → 본 분석 → data/lura_top_aug_mining.json
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from wcl_v2 import WCLV2, WCLV2Error

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\66e6c09f-1b73-4a06-9a39-f108d6bcda2a\scratchpad") / "lura_aug_cache"
SCRATCH.mkdir(parents=True, exist_ok=True)

EID = 3183          # 한밤의 도래 (L'ura)
DIFF = 5            # Mythic
CRYSTAL_AURA = 1253031   # '일렁이는 빛' — 여명의 수정 보유 마커 (셀프 디버프)
N_PAIRS = 25
OUT = DATA / "lura_top_aug_mining.json"

# ── 이름 앵커 (ko, en 소문자) — ID는 데이터에서 발견 ─────────────────────
MAJORS = {
    "breath_of_eons": ("영겁의 숨결", "breath of eons"),
    "time_skip": ("시간 건너뛰기", "time skip"),
    "fire_breath": ("화염 숨결", "fire breath"),
    "upheaval": ("대격변", "upheaval"),
    "prescience": ("예지", "prescience"),
    "ebon_might": ("칠흑의 힘", "ebon might"),
    "eruption": ("분출", "eruption"),
}
DEFENSIVES = {
    "obsidian_scales": ("흑요석 비늘", "obsidian scales"),
    "renewing_blaze": ("소생의 불길", "renewing blaze"),
    "zephyr": ("산들바람", "zephyr"),
    "verdant_embrace": ("신록의 품", "verdant embrace"),
    "rewind": ("되감기", "rewind"),
    "emerald_blossom": ("에메랄드 꽃", "emerald blossom"),
    "cauterizing_flame": ("소작의 불꽃", "cauterizing flame"),
    "expunge": ("삭제", "expunge"),
}
KNOWN_COMBAT_POTS = {1236616, 1236998, 1236994}  # 빛의 잠재력/방종의 비약/무모함의 물약

# 르우라 보스 기술 이름 (마스터데이터 재조회 대신 기존 채굴 산출물에서 확인)
DEATH_ABILITY_NAMES = {
    1273033: "Void Swarm", 1282028: "The Darkwell", 1249797: "Shattered Sky",
    1263514: "Midnight", 1254076: "Heaven's Glaives", 1279581: "Starsplinter",
}


def load_spell_db() -> dict[int, dict]:
    try:
        db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
        return {int(k): v for k, v in db.items() if isinstance(v, dict)}
    except Exception:
        return {}


SPELL_DB = load_spell_db()


def names_of(gid: int, table_names: dict[int, str]) -> tuple[str, str]:
    """(ko, en_lower) 이름 후보. table 이름은 report 언어(대개 영어 번역)."""
    d = SPELL_DB.get(gid) or {}
    ko = d.get("name_ko") or ""
    en = (d.get("name_en") or "").lower()
    tname = table_names.get(gid, "")
    # table 이름이 한글이면 ko 쪽으로, 아니면 en 쪽으로도 활용
    if tname and any("가" <= ch <= "힣" for ch in tname):
        ko = ko or tname
    else:
        en = en or tname.lower()
    return ko, en


def classify(gid: int, table_names: dict[int, str]) -> str | None:
    ko, en = names_of(gid, table_names)
    for slug, (k, e) in {**MAJORS, **DEFENSIVES}.items():
        if ko == k or en == e:
            return slug
    return None


def is_potion(gid: int, table_names: dict[int, str]) -> str | None:
    """'combat' | 'healing' | None"""
    if gid in KNOWN_COMBAT_POTS:
        return "combat"
    ko, en = names_of(gid, table_names)
    if not (("물약" in ko) or ("비약" in ko) or ("potion" in en)
            or ("draught" in en) or ("elixir" in en)):
        return None
    if ("치유" in ko) or ("healing" in en) or ("health" in en):
        return "healing"
    return "combat"


def is_healthstone(gid: int, table_names: dict[int, str]) -> bool:
    ko, en = names_of(gid, table_names)
    return ("치유석" in ko) or ("healthstone" in en)


def mmss(t: float | None) -> str:
    if t is None:
        return "-"
    sign = "-" if t < 0 else ""
    t = abs(t)
    return f"{sign}{int(t) // 60}:{int(t) % 60:02d}"


def med(vals, nd=1):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), nd) if vals else None


# ── 쿼리 ──────────────────────────────────────────────────────────────────
Q_RANKS = """
query($eid: Int!, $diff: Int!, $page: Int!) {
  worldData { encounter(id: $eid) {
    characterRankings(metric: %s, difficulty: $diff,
                      className: "Evoker", specName: "Augmentation",
                      page: $page)
  } }
}
"""

Q_FIGHT = """
query($code: String!, $fid: Int!) {
  reportData { report(code: $code) {
    fights(fightIDs: [$fid]) {
      id startTime endTime encounterID difficulty kill lastPhase
      bossPercentage averageItemLevel
      phaseTransitions { id startTime }
    }
    masterData(translate: true) { actors(type: "Player") { id name subType } }
  } }
}
"""

Q_PHASES = """
query($code: String!) {
  reportData { report(code: $code) {
    phases { encounterID separatesWipes phases { id name isIntermission } }
  } }
}
"""


def q_events(code: str, sid: int, s: float, e: float) -> str:
    win = f"startTime:{s:.1f},endTime:{e:.1f}"
    return (
        "query{reportData{report(code:\"" + code + "\"){"
        f"casts:events(dataType:Casts,{win},sourceID:{sid},limit:10000)"
        "{data nextPageTimestamp}"
        f"crystald:events(dataType:Debuffs,{win},abilityID:{CRYSTAL_AURA},limit:10000)"
        "{data nextPageTimestamp}"
        f"crystalb:events(dataType:Buffs,{win},abilityID:{CRYSTAL_AURA},limit:10000)"
        "{data nextPageTimestamp}"
        f"deaths:events(dataType:Deaths,{win},targetID:{sid},limit:50){{data}}"
        f"casttable:table(dataType:Casts,{win},sourceID:{sid})"
        f"bufftable:table(dataType:Buffs,{win},sourceID:{sid},targetID:{sid})"
        "}}}"
    )


def cached_query(cli: WCLV2, key: str, fn):
    f = SCRATCH / f"{key}.json"
    if f.exists():
        return json.load(open(f, encoding="utf-8"))
    out = fn()
    json.dump(out, open(f, "w", encoding="utf-8"), ensure_ascii=False)
    time.sleep(0.3)
    return out


def get_rankings(cli: WCLV2):
    for metric in ("dps", "playerscore"):
        def fetch(metric=metric):
            rows = []
            for page in (1,):
                d = cli.query(Q_RANKS % metric, {"eid": EID, "diff": DIFF, "page": page})
                obj = (((d.get("worldData") or {}).get("encounter") or {})
                       .get("characterRankings") or {})
                rows.extend(obj.get("rankings") or [])
            return rows
        rows = cached_query(cli, f"rankings_{metric}", fetch)
        if rows:
            return rows, metric
    raise SystemExit("rankings 비어있음 (dps/playerscore 둘 다)")


# ── 파싱 ──────────────────────────────────────────────────────────────────
def aura_windows(events: list[dict], t0: float, dur: float) -> dict[int, list[list[float]]]:
    """targetID -> [[s,e],...] (초, 전투 상대시각)."""
    open_at: dict[int, float] = {}
    wins: dict[int, list[list[float]]] = defaultdict(list)
    for ev in sorted(events, key=lambda x: x.get("timestamp") or 0):
        typ = ev.get("type") or ""
        tgt = int(ev.get("targetID") or 0)
        t = (float(ev["timestamp"]) - t0) / 1000
        if typ in ("applydebuff", "applybuff"):
            if tgt not in open_at:
                open_at[tgt] = t
        elif typ in ("removedebuff", "removebuff"):
            s = open_at.pop(tgt, None)
            if s is None:
                s = 0.0  # 시작 전부터 보유(이론상 없음)
            wins[tgt].append([round(s, 1), round(t, 1)])
    for tgt, s in open_at.items():
        wins[tgt].append([round(s, 1), round(dur, 1)])
    return wins


def parse_pair(pair, q1, q2, p3_phase_id):
    rep = q1["reportData"]["report"]
    fight = (rep.get("fights") or [None])[0]
    if not fight:
        return None, "fight 없음"
    actors = {int(a["id"]): a for a in (rep.get("masterData") or {}).get("actors") or []}
    # 증강 플레이어 sourceID
    sid = None
    for aid, a in actors.items():
        if a.get("name") == pair["name"] and a.get("subType") == "Evoker":
            sid = aid
            break
    if sid is None:
        for aid, a in actors.items():
            if a.get("name") == pair["name"]:
                sid = aid
                break
    if sid is None:
        return None, f"actor '{pair['name']}' 못 찾음"

    t0, t1 = float(fight["startTime"]), float(fight["endTime"])
    dur = (t1 - t0) / 1000

    trans = [{"id": p["id"], "t": round((float(p["startTime"]) - t0) / 1000, 1)}
             for p in fight.get("phaseTransitions") or []]
    p3_start = next((p["t"] for p in trans if p["id"] == p3_phase_id), None)

    r = q2["reportData"]["report"]
    # 이름 매핑: casts table
    table_names: dict[int, str] = {}
    ct = (r.get("casttable") or {}).get("data") or {}
    table_totals: dict[int, int] = {}
    for row in ct.get("entries") or []:
        gid = int(row.get("guid") or 0)
        if gid:
            table_names[gid] = row.get("name") or ""
            table_totals[gid] = int(row.get("total") or 0)

    cast_rows = (r.get("casts") or {}).get("data") or []
    paged = bool((r.get("casts") or {}).get("nextPageTimestamp"))
    type_by_gid: dict[int, Counter] = defaultdict(Counter)
    for ev in cast_rows:
        type_by_gid[int(ev.get("abilityGameID") or 0)][ev.get("type") or "?"] += 1

    def cast_times(gid_set):
        """cast 우선, 없으면 empowerend 로 완료 시전 시각."""
        out = []
        for gid in gid_set:
            use_type = "cast" if type_by_gid[gid].get("cast") else (
                "empowerend" if type_by_gid[gid].get("empowerend") else "cast")
            for ev in cast_rows:
                if int(ev.get("abilityGameID") or 0) == gid and ev.get("type") == use_type:
                    out.append(round((float(ev["timestamp"]) - t0) / 1000, 1))
        return sorted(out)

    # gid 분류
    slug_gids: dict[str, set[int]] = defaultdict(set)
    pot_gids: dict[str, set[int]] = defaultdict(set)
    hs_gids: set[int] = set()
    for gid in set(list(type_by_gid) + list(table_names)):
        slug = classify(gid, table_names)
        if slug:
            slug_gids[slug].add(gid)
        p = is_potion(gid, table_names)
        if p:
            pot_gids[p].add(gid)
        if is_healthstone(gid, table_names):
            hs_gids.add(gid)

    times = {slug: cast_times(gids) for slug, gids in slug_gids.items()}
    pots_combat = [(t, table_names.get(g) or (SPELL_DB.get(g) or {}).get("name_ko") or str(g))
                   for g in pot_gids.get("combat", set())
                   for t in cast_times({g})]
    pots_heal = [(t, table_names.get(g) or (SPELL_DB.get(g) or {}).get("name_ko") or str(g))
                 for g in pot_gids.get("healing", set())
                 for t in cast_times({g})]
    hs_times = cast_times(hs_gids)

    # 칠흑의 힘 업타임 (bufftable: source=target=본인 → 셀프 버프)
    em_pct = None
    em_entries = []
    bt = (r.get("bufftable") or {}).get("data") or {}
    for a in bt.get("auras") or []:
        nm = (a.get("name") or "")
        ko, en = names_of(int(a.get("guid") or 0), {int(a.get("guid") or 0): nm})
        if ko == "칠흑의 힘" or en == "ebon might":
            em_entries.append({"guid": a.get("guid"), "name": nm,
                               "uptime_ms": a.get("totalUptime"),
                               "uses": a.get("totalUses")})
    if em_entries:
        best = max(em_entries, key=lambda x: x.get("uptime_ms") or 0)
        up = float(best.get("uptime_ms") or 0)
        if up <= (t1 - t0) * 1.02:
            em_pct = round(100 * up / (t1 - t0), 1)

    # 사망 — ★Deaths events 의 targetID 인자는 무시됨(전 공대 사망 반환) → 클라 측 필터★
    death_rows = (r.get("deaths") or {}).get("data") or []
    deaths = []
    for ev in death_rows:
        if int(ev.get("targetID") or 0) != sid:
            continue
        gid = int(ev.get("killingAbilityGameID") or 0)
        deaths.append({
            "t": round((float(ev["timestamp"]) - t0) / 1000, 1),
            "ability_id": gid,
            "ability": DEATH_ABILITY_NAMES.get(gid)
                       or (SPELL_DB.get(gid) or {}).get("name_ko") or str(gid),
        })
    raid_deaths_n = len(death_rows)

    # 수정(1253031) 창
    crystal_events = (((r.get("crystald") or {}).get("data")) or []) + \
                     (((r.get("crystalb") or {}).get("data")) or [])
    wins = aura_windows(crystal_events, t0, dur)
    aug_wins = wins.get(sid, [])
    carriers = sorted(wins)
    aug_p3_wins = [w for w in aug_wins if p3_start is not None and w[1] > p3_start]
    aug_early_wins = [w for w in aug_wins
                      if p3_start is None or w[0] < p3_start]

    # 페이즈별 캐리 여부 (phaseTransitions 창과 겹침)
    phase_windows = []
    for i, p in enumerate(trans):
        pend = trans[i + 1]["t"] if i + 1 < len(trans) else dur
        phase_windows.append((p["id"], p["t"], pend))
    carry_phases = sorted({pid for pid, ps, pe in phase_windows
                           if any(w[0] < pe and w[1] > ps for w in aug_wins)})

    breaths = times.get("breath_of_eons", [])
    # P3 캐리 창 vs 숨결 관계
    rel = []
    for s, e in aug_p3_wins:
        during = [round(b - s, 1) for b in breaths if s <= b <= e]
        before = [round(s - b, 1) for b in breaths if b < s]
        after = [round(b - e, 1) for b in breaths if b > e]
        rel.append({
            "window": [s, e],
            "breath_during_offsets": during,
            "last_breath_before_gap_s": min(before) if before else None,
            "first_breath_after_gap_s": min(after) if after else None,
        })

    # 검증: casts table total vs 이벤트 수 (주요기)
    # 임파워기(화염숨결/대격변)는 table total = cast + empowerend (관측 확인) — 그 관계로 검증
    verify = {}
    for slug in ("breath_of_eons", "fire_breath", "upheaval", "time_skip", "prescience"):
        gids = slug_gids.get(slug, set())
        ev_n = len(times.get(slug, []))
        tb_n = sum(table_totals.get(g, 0) for g in gids)
        exp_tb = sum(type_by_gid[g].get("cast", 0) + type_by_gid[g].get("empowerend", 0)
                     for g in gids)
        verify[slug] = {"events": ev_n, "table": tb_n, "ok": tb_n in (ev_n, exp_tb),
                        "gids": {g: table_names.get(g, "") for g in sorted(gids)},
                        "types": {g: dict(type_by_gid[g]) for g in sorted(gids)}}

    parsed = {
        "report": pair["code"], "fight_id": pair["fid"],
        "url": f"https://www.warcraftlogs.com/reports/{pair['code']}#fight={pair['fid']}",
        "player": pair["name"], "rank": pair["rank"], "dps": pair["amount"],
        "guild": pair.get("guild"), "server": pair.get("server"),
        "region": pair.get("region"), "source_id": sid,
        "duration_s": round(dur, 1), "kill": bool(fight.get("kill")),
        "last_phase": fight.get("lastPhase"),
        "avg_item_level": fight.get("averageItemLevel"),
        "phase_transitions": trans, "p3_start_s": p3_start,
        "casts": {
            "breath_of_eons": breaths,
            "fire_breath": times.get("fire_breath", []),
            "upheaval": times.get("upheaval", []),
            "time_skip": times.get("time_skip", []),
            "prescience_n": len(times.get("prescience", [])),
            "eruption_n": len(times.get("eruption", [])),
        },
        "breath_rel_p3": ([round(b - p3_start, 1) for b in breaths]
                          if p3_start is not None else None),
        "ebon_might_uptime_pct": em_pct,
        "ebon_might_entries": em_entries,
        "defensives": {s: times.get(s, []) for s in DEFENSIVES if times.get(s)},
        "potions_combat": [{"t": t, "name": n} for t, n in sorted(pots_combat)],
        "potions_healing": [{"t": t, "name": n} for t, n in sorted(pots_heal)],
        "healthstones": hs_times,
        "deaths": deaths,
        "raid_deaths_n": raid_deaths_n,
        "crystal": {
            "raid_carrier_n": len(carriers),
            "raid_window_n": sum(len(v) for v in wins.values()),
            "aug_windows": aug_wins,
            "aug_carries_ever": bool(aug_wins),
            "aug_carries_p3": bool(aug_p3_wins),
            "aug_carries_before_p3": bool(aug_early_wins),
            "aug_carry_phase_ids": carry_phases,
            "aug_p3_windows": aug_p3_wins,
            "breath_vs_p3_windows": rel,
        },
        "_verify": verify,
        "_casts_paged": paged,
        "_crystal_paged": bool((r.get("crystald") or {}).get("nextPageTimestamp")
                               or (r.get("crystalb") or {}).get("nextPageTimestamp")),
    }
    return parsed, None


def explore_print(parsed, q2):
    r = q2["reportData"]["report"]
    ct = (r.get("casttable") or {}).get("data") or {}
    print(f"\n===== EXPLORE {parsed['report']}#{parsed['fight_id']} {parsed['player']} "
          f"(dur {mmss(parsed['duration_s'])}, kill={parsed['kill']})")
    print("  phase_transitions:", parsed["phase_transitions"],
          "p3_start:", parsed["p3_start_s"])
    print("  casts table:")
    for row in sorted(ct.get("entries") or [], key=lambda x: -(x.get("total") or 0)):
        print(f"    {row.get('guid'):>9} {row.get('name'):<28} total={row.get('total')}")
    print("  event types per major:")
    for slug, v in parsed["_verify"].items():
        print(f"    {slug}: {v}")
    bt = (r.get("bufftable") or {}).get("data") or {}
    print("  bufftable auras (top uptime):")
    for a in sorted(bt.get("auras") or [], key=lambda x: -(x.get("totalUptime") or 0))[:12]:
        print(f"    {a.get('guid'):>9} {a.get('name'):<28} up={a.get('totalUptime')} uses={a.get('totalUses')}")
    print("  crystal debuff evs:", len(((r.get('crystald') or {}).get('data')) or []),
          " buff evs:", len(((r.get('crystalb') or {}).get('data')) or []))
    print("  aug windows:", parsed["crystal"]["aug_windows"],
          " raid carriers:", parsed["crystal"]["raid_carrier_n"])


def main():
    explore = "explore" in sys.argv
    cli = WCLV2()
    rate0 = cli.points_left()
    print(f"rate: {rate0['pointsSpentThisHour']:.0f}/{rate0['limitPerHour']}" if rate0 else "rate ?")

    ranks, metric = get_rankings(cli)
    print(f"rankings({metric}): {len(ranks)}행")
    pairs, seen = [], set()
    for i, row in enumerate(ranks, 1):
        rep = row.get("report") or {}
        code, fid = rep.get("code"), rep.get("fightID")
        if not code or fid is None:
            continue
        key = (code, fid)
        if key in seen:
            continue
        seen.add(key)
        srv = row.get("server") or {}
        pairs.append({
            "code": code, "fid": int(fid), "name": row.get("name"),
            "rank": i, "amount": round(float(row.get("amount") or 0), 1),
            "duration_ms": row.get("duration"),
            "guild": (row.get("guild") or {}).get("name") if isinstance(row.get("guild"), dict) else row.get("guild"),
            "server": srv.get("name") if isinstance(srv, dict) else srv,
            "region": (srv.get("region") if isinstance(srv, dict) else None),
        })
        if len(pairs) >= N_PAIRS:
            break
    print(f"distinct pairs: {len(pairs)}")
    if explore:
        pairs = pairs[:2]

    # phase 메타 (첫 report에서 1회)
    p3_phase_id, phase_meta = 3, None
    try:
        ph = cached_query(cli, f"phases_{pairs[0]['code']}",
                          lambda: cli.query(Q_PHASES, {"code": pairs[0]["code"]}))
        for encp in (ph["reportData"]["report"].get("phases") or []):
            if encp.get("encounterID") == EID:
                phase_meta = encp
                non_int = [p for p in encp.get("phases") or []
                           if not p.get("isIntermission")]
                if len(non_int) >= 3:
                    p3_phase_id = non_int[2]["id"]
    except Exception as e:
        print(f"phases 메타 실패(기본 id=3 사용): {str(e)[:150]}")
    print(f"phase_meta: {json.dumps(phase_meta, ensure_ascii=False)}")
    print(f"p3_phase_id = {p3_phase_id}")

    fights, errors = [], []
    for pr in pairs:
        try:
            q1 = cached_query(cli, f"q1_{pr['code']}_{pr['fid']}",
                              lambda: cli.query(Q_FIGHT, {"code": pr["code"], "fid": pr["fid"]}))
            rep = q1["reportData"]["report"]
            fight = (rep.get("fights") or [None])[0]
            if not fight:
                errors.append({**pr, "err": "fight 없음"})
                continue
            sid = None
            for a in (rep.get("masterData") or {}).get("actors") or []:
                if a.get("name") == pr["name"] and a.get("subType") == "Evoker":
                    sid = int(a["id"])
                    break
            if sid is None:
                errors.append({**pr, "err": "actor 못 찾음"})
                continue
            q2 = cached_query(
                cli, f"q2_{pr['code']}_{pr['fid']}_s{sid}",
                lambda: cli.query(q_events(pr["code"], sid,
                                           float(fight["startTime"]),
                                           float(fight["endTime"]))))
            parsed, err = parse_pair(pr, q1, q2, p3_phase_id)
            if err:
                errors.append({**pr, "err": err})
                continue
            fights.append(parsed)
            if explore:
                explore_print(parsed, q2)
            else:
                c = parsed["crystal"]
                print(f"  {parsed['report']}#{parsed['fight_id']} {parsed['player'][:12]:<12} "
                      f"dur {mmss(parsed['duration_s'])} p3@{mmss(parsed['p3_start_s'])} "
                      f"숨결{len(parsed['casts']['breath_of_eons'])} "
                      f"수정캐리 ever={c['aug_carries_ever']} p3={c['aug_carries_p3']}")
        except (WCLV2Error, Exception) as e:
            errors.append({**pr, "err": str(e)[:200]})
            print(f"  ! {pr['code']}#{pr['fid']} 실패: {str(e)[:150]}")
    if explore:
        return
    print(f"\n분석 성공 {len(fights)}/{len(pairs)} (실패 {len(errors)})")
    if not fights:
        raise SystemExit("성공한 판 없음")

    # ── 집계 ─────────────────────────────────────────────────────────────
    def pm(n, dur):
        return round(n / (dur / 60), 2) if dur else None

    kills = [f for f in fights if f["kill"]]
    aggs_src = fights  # rankings 는 킬만 반환하지만 태그는 유지
    breath_n = [len(f["casts"]["breath_of_eons"]) for f in aggs_src]
    agg = {
        "n_fights": len(aggs_src),
        "n_kills": len(kills),
        "duration_med_s": med([f["duration_s"] for f in aggs_src]),
        "breath_per_fight_med": med(breath_n, 0),
        "breath_pm_med": med([pm(len(f["casts"]["breath_of_eons"]), f["duration_s"]) for f in aggs_src], 2),
        "first_breath_med_s": med([f["casts"]["breath_of_eons"][0] for f in aggs_src if f["casts"]["breath_of_eons"]]),
        "fire_breath_pm_med": med([pm(len(f["casts"]["fire_breath"]), f["duration_s"]) for f in aggs_src], 2),
        "upheaval_pm_med": med([pm(len(f["casts"]["upheaval"]), f["duration_s"]) for f in aggs_src], 2),
        "time_skip_per_fight_med": med([len(f["casts"]["time_skip"]) for f in aggs_src], 0),
        "time_skip_talented_pct": round(100 * sum(1 for f in aggs_src if f["casts"]["time_skip"]) / len(aggs_src)),
        "prescience_pm_med": med([pm(f["casts"]["prescience_n"], f["duration_s"]) for f in aggs_src], 2),
        "prescience_per_fight_med": med([f["casts"]["prescience_n"] for f in aggs_src], 0),
        "ebon_might_uptime_med_pct": med([f["ebon_might_uptime_pct"] for f in aggs_src]),
        "combat_potion_per_fight_med": med([len(f["potions_combat"]) for f in aggs_src], 0),
        "combat_potion_used_pct": round(100 * sum(1 for f in aggs_src if f["potions_combat"]) / len(aggs_src)),
        "healing_potion_per_fight_med": med([len(f["potions_healing"]) for f in aggs_src], 0),
        "healing_potion_used_pct": round(100 * sum(1 for f in aggs_src if f["potions_healing"]) / len(aggs_src)),
        "healthstone_used_pct": round(100 * sum(1 for f in aggs_src if f["healthstones"]) / len(aggs_src)),
        "obsidian_scales_per_fight_med": med([len(f["defensives"].get("obsidian_scales", [])) for f in aggs_src], 0),
        "obsidian_scales_used_pct": round(100 * sum(1 for f in aggs_src if f["defensives"].get("obsidian_scales")) / len(aggs_src)),
        "renewing_blaze_per_fight_med": med([len(f["defensives"].get("renewing_blaze", [])) for f in aggs_src], 0),
        "renewing_blaze_used_pct": round(100 * sum(1 for f in aggs_src if f["defensives"].get("renewing_blaze")) / len(aggs_src)),
        "other_defensives_seen": sorted({s for f in aggs_src for s in f["defensives"]
                                         if s not in ("obsidian_scales", "renewing_blaze")}),
        "deaths_total": sum(len(f["deaths"]) for f in aggs_src),
        "death_rate_pct": round(100 * sum(1 for f in aggs_src if f["deaths"]) / len(aggs_src)),
        "raid_deaths_per_fight_med": med([f["raid_deaths_n"] for f in aggs_src], 0),
    }

    # 수정 캐리 요약
    with_p3 = [f for f in aggs_src if f["p3_start_s"] is not None]
    cry = {
        "n_with_p3": len(with_p3),
        "aug_carries_ever_n": sum(1 for f in aggs_src if f["crystal"]["aug_carries_ever"]),
        "aug_carries_p3_n": sum(1 for f in aggs_src if f["crystal"]["aug_carries_p3"]),
        "aug_carries_before_p3_n": sum(1 for f in aggs_src
                                       if f["crystal"]["aug_carries_ever"]
                                       and f["crystal"]["aug_carries_before_p3"]),
        "aug_carry_by_phase_id": dict(sorted(Counter(
            pid for f in aggs_src
            for pid in f["crystal"].get("aug_carry_phase_ids", [])).items())),
        "raid_carrier_n_med": med([f["crystal"]["raid_carrier_n"] for f in aggs_src], 0),
        "p3_carrier_details": [
            {"report": f["report"], "fight_id": f["fight_id"], "player": f["player"],
             "p3_start_s": f["p3_start_s"], "windows": f["crystal"]["aug_p3_windows"],
             "breath_times": f["casts"]["breath_of_eons"],
             "relation": f["crystal"]["breath_vs_p3_windows"]}
            for f in aggs_src if f["crystal"]["aug_carries_p3"]
        ],
    }

    # 숨결 vs P3 히스토그램 (30s 빈)
    offs = [o for f in with_p3 for o in (f["breath_rel_p3"] or [])]
    hist = Counter()
    for o in offs:
        hist[int(o // 30) * 30] += 1
    breath_p3 = {
        "p3_start_med_s": med([f["p3_start_s"] for f in with_p3]),
        "offsets_all": sorted(offs),
        "hist_30s_bins": {f"{k}s~{k+30}s": v for k, v in sorted(hist.items())},
        "breath_within_p3_first60s_pct": (
            round(100 * sum(1 for f in with_p3
                            if any(0 <= o <= 60 for o in (f["breath_rel_p3"] or [])))
                  / len(with_p3)) if with_p3 else None),
        "last_breath_before_p3_gap_med_s": med(
            [min((-o) for o in (f["breath_rel_p3"] or []) if o < 0)
             for f in with_p3 if any(o < 0 for o in (f["breath_rel_p3"] or []))]),
        "first_breath_after_p3_med_s": med(
            [min(o for o in (f["breath_rel_p3"] or []) if o >= 0)
             for f in with_p3 if any(o >= 0 for o in (f["breath_rel_p3"] or []))]),
    }

    # ── 핸드체크 (첫 판 상세 출력 + JSON 포함) ───────────────────────────
    hc = fights[0]
    print(f"\n===== 핸드체크: {hc['url']} {hc['player']} (rank {hc['rank']}, dur {mmss(hc['duration_s'])}, kill={hc['kill']})")
    print(f"  phase transitions: {[(p['id'], mmss(p['t'])) for p in hc['phase_transitions']]}  → P3 {mmss(hc['p3_start_s'])}")
    print(f"  영겁의 숨결 {len(hc['casts']['breath_of_eons'])}회: {[mmss(t) for t in hc['casts']['breath_of_eons']]}")
    print(f"    vs P3 오프셋: {hc['breath_rel_p3']}")
    print(f"  화염숨결 {len(hc['casts']['fire_breath'])}회 / 대격변 {len(hc['casts']['upheaval'])}회 / "
          f"시간건너뛰기 {len(hc['casts']['time_skip'])}회 / 예지 {hc['casts']['prescience_n']}회")
    print(f"  칠흑의 힘 업타임: {hc['ebon_might_uptime_pct']}% (entries {hc['ebon_might_entries']})")
    print(f"  방어기: { {k: [mmss(t) for t in v] for k, v in hc['defensives'].items()} }")
    print(f"  물약: {hc['potions_combat']} / 치유물약 {hc['potions_healing']} / 치유석 {hc['healthstones']}")
    print(f"  사망: {hc['deaths']}")
    print(f"  수정: 공대 캐리어 {hc['crystal']['raid_carrier_n']}명, 증강 창 {hc['crystal']['aug_windows']}, "
          f"P3캐리 {hc['crystal']['aug_carries_p3']}")
    print(f"  검증(events vs table): "
          f"{ {k: (v['events'], v['table']) for k, v in hc['_verify'].items()} }")

    # 검증 미스매치 전수
    mism = []
    for f in fights:
        for slug, v in f["_verify"].items():
            if not v.get("ok"):
                mism.append(f"{f['report']}#{f['fight_id']} {slug} ev={v['events']} tb={v['table']}")
    if mism:
        print("\n! events/table 카운트 미스매치:")
        for m in mism[:20]:
            print("   ", m)

    print("\n===== 집계 =====")
    for k, v in agg.items():
        print(f"  {k}: {v}")
    print("\n===== 수정 캐리 =====")
    for k, v in cry.items():
        if k != "p3_carrier_details":
            print(f"  {k}: {v}")
    for d in cry["p3_carrier_details"]:
        print(f"  P3 캐리: {d['report']}#{d['fight_id']} {d['player']} wins={d['windows']} rel={d['relation']}")
    print("\n===== 숨결 vs P3 =====")
    for k, v in breath_p3.items():
        if k != "offsets_all":
            print(f"  {k}: {v}")

    out = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "encounter_id": EID, "encounter_name": "한밤의 도래(L'ura)",
            "difficulty": "Mythic(5)",
            "spec": "Evoker/Augmentation",
            "rankings_metric_used": metric,
            "rankings_rows_seen": len(ranks),
            "n_pairs_requested": N_PAIRS,
            "n_fights_ok": len(fights),
            "all_kills": all(f["kill"] for f in fights),
            "crystal_aura_id": CRYSTAL_AURA,
            "crystal_aura_name": "일렁이는 빛(여명의 수정 보유 마커)",
            "p3_phase_id": p3_phase_id,
            "phase_metadata": phase_meta,
            "percentile_note": "characterRankings 상위권 자체가 랭킹이므로 percentile 대신 rank 순번 기록",
            "notes": [
                "phaseTransitions 기준 P3 = phase id 4 'Stage Three: Midnight Falls' (전 판 ~330s 고정 시작).",
                "Deaths events 의 targetID 인자는 서버에서 무시됨(전 공대 사망 반환) → 클라이언트 측 targetID 필터로 증강 사망만 추출.",
                "임파워기(화염숨결/대격변)는 casts table total = cast + empowerend 로 이중집계 → 완료 시전 수는 'cast' 이벤트 수 사용.",
                "칠흑의 힘 업타임은 table(dataType:Buffs, sourceID=targetID=본인) 의 395296(셀프) totalUptime.",
                "수정('일렁이는 빛' 1253031)은 Debuffs 로만 기록됨(Buffs 별칭 0건). 공대 캐리어는 매 킬 10명.",
                "P2(Dark Reactor) 캐리 창은 ~18s 보유/~3-5s 공백 반복 패턴, P3 진입(330s)시 강제 해제 후 ~332s 재부여.",
            ],
            "verify_mismatches": mism,
            "errors": errors,
        },
        "aggregates": agg,
        "crystal_summary": cry,
        "breath_vs_p3": breath_p3,
        "fights": [{k: v for k, v in f.items() if not k.startswith("_")} for f in fights],
        "hand_check_fight": {"report": hc["report"], "fight_id": hc["fight_id"],
                             "player": hc["player"], "url": hc["url"]},
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT}")
    rate1 = cli.points_left()
    if rate0 and rate1:
        print(f"pts used: {rate1['pointsSpentThisHour'] - rate0['pointsSpentThisHour']:.1f}")


if __name__ == "__main__":
    main()
