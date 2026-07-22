"""르우라(한밤의 도래, eid 3183) 신화 — TOP 부정 죽음의 기사(UDK) 쿨기/생존기/물약 실측.

파이프라인 (tmp_mine_bm_cd.py / analyze_manteri_vanguard.py 패턴):
  1) characterRankings(DeathKnight/Unholy, dps, diff5) → top 25 distinct report/fight (킬만)
  2) report별 fights 메타(phaseTransitions 포함) + 플레이어 actor 매칭
  3) fight별 combined 쿼리: 캐스트 events(raw, 타임스탬프) + Deaths + Casts table + DamageDone table
  4) 스펠 ID는 기억에 의존하지 않고 각 로그의 Casts table 이름으로 발견 → 이름→ID 집계
  5) 집계: 주요 쿨기 캐스트/판, /분, 첫 캐스트, 간격, 페이즈 분포, 생존기, 물약, 사망

원시 응답은 스크래치패드에 캐시 → 재실행 시 API 호출 없음.
출력: data/lura_top_udk_mining.json
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze")
from wcl_v2 import WCLV2

ROOT = Path(r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze")
DATA = ROOT / "data"
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\66e6c09f-1b73-4a06-9a39-f108d6bcda2a\scratchpad") / "udk_cache"
SCRATCH.mkdir(parents=True, exist_ok=True)
OUT = DATA / "lura_top_udk_mining.json"

ENCOUNTER_ID = 3183
DIFFICULTY = 5
ZONE_ID = 46
TOP_N = 25

# ── 이름 → 카테고리 규칙 (ID는 데이터에서 발견) ────────────────────────────
# Casts table 은 영문 정규 이름을 리턴 → 영문+한글 둘 다 매칭.
# 12.0.7 미드나잇 UDK 실측: Apocalypse/Gargoyle/Unholy Assault/Death's Advance
# 는 25/25 킬 로그에서 0회 — 킷에서 사라짐. 신규: Charge!/Death Charge/Graveyard.
MAJOR_NAME_RULES = [
    ("army", lambda n: "Army of the Dead" in n or "죽음의 군대" in n),
    ("abomination", lambda n: "Abomination" in n or "흉물" in n),
    ("dark_transformation", lambda n: "Dark Transformation" in n or "어둠의 변신" in n),
    ("apocalypse", lambda n: n in ("Apocalypse", "대재앙")),
    ("gargoyle", lambda n: "Gargoyle" in n or "가고일" in n),
    ("unholy_assault", lambda n: "Unholy Assault" in n
        or ("부정" in n and ("폭행" in n or "습격" in n))),
    ("amz", lambda n: "Anti-Magic Zone" in n or "대마법 지대" in n),
    ("erw", lambda n: "Empower Rune Weapon" in n or "룬 무기 강화" in n),
    ("vile_contagion", lambda n: "Vile Contagion" in n or "역겨운 전염" in n),
    ("charge_horsemen", lambda n: n in ("Charge!", "돌격!")),   # Rider 기병 소환류(관측 신규)
    ("graveyard", lambda n: n in ("Graveyard", "묘지")),        # 관측 신규(12/25판)
    ("raise_dead", lambda n: n in ("Raise Dead", "구울 되살리기")),
]
DEF_NAME_RULES = [
    ("ams", lambda n: "Anti-Magic Shell" in n or "대마법 보호막" in n),
    ("ibf", lambda n: "Icebound Fortitude" in n or "얼음같은 인내력" in n),
    ("lichborne", lambda n: n in ("Lichborne", "흡혈")),
    ("deaths_advance", lambda n: "Death's Advance" in n or "죽음의 진군" in n),
    ("death_charge", lambda n: "Death Charge" in n),            # Rider 이동기(진군 대체)
    ("death_pact", lambda n: "Death Pact" in n or "죽음의 협정" in n),
    ("wraith_walk", lambda n: "Wraith Walk" in n or "사자의 산책" in n),
]
def is_consumable(n: str) -> bool:
    return ("물약" in n) or ("비약" in n) or ("치유의 돌" in n) \
        or ("Potion" in n) or ("Healthstone" in n) or ("Elixir" in n)

LUST_KEYS = ("영웅심", "피의 욕망", "시간 왜곡", "시간왜곡", "고동치는 북",
             "Heroism", "Bloodlust", "Time Warp", "Fury of the Aspects",
             "Primal Rage", "Drums of", "Timeless Drums")

Q_ZONE = """
query($id: Int!) { worldData { zone(id: $id) { partitions { id name default } } } }
"""

Q_RANKS = """
query($eid: Int!, $page: Int!, $partition: Int!) {
  worldData {
    encounter(id: $eid) {
      characterRankings(
        metric: dps difficulty: 5
        className: "DeathKnight" specName: "Unholy"
        page: $page partition: $partition
      )
    }
  }
}
"""

Q_REPORT_META = """
query($code: String!, $fids: [Int]!) {
  reportData {
    report(code: $code) {
      title
      fights(fightIDs: $fids) {
        id startTime endTime kill lastPhase bossPercentage friendlyPlayers
        phaseTransitions { id startTime }
      }
      masterData(translate: true) { actors(type: "Player") { id name server } }
    }
  }
}
"""

Q_FIGHT = """
query($code: String!, $start: Float!, $end: Float!, $sid: Int!) {
  reportData {
    report(code: $code) {
      casts: events(dataType: Casts, startTime: $start, endTime: $end,
                    sourceID: $sid, hostilityType: Friendlies, limit: 10000)
        { data nextPageTimestamp }
      deaths: events(dataType: Deaths, startTime: $start, endTime: $end,
                     hostilityType: Friendlies) { data nextPageTimestamp }
      ctable: table(dataType: Casts, startTime: $start, endTime: $end,
                    sourceID: $sid, hostilityType: Friendlies)
      dtable: table(dataType: DamageDone, startTime: $start, endTime: $end,
                    sourceID: $sid, hostilityType: Friendlies)
    }
  }
}
"""

Q_ABILITIES = """
query($code: String!) {
  reportData { report(code: $code) {
    masterData(translate: true) { abilities { gameID name } }
  } }
}
"""

Q_PHASE_NAMES = """
query($code: String!) {
  reportData { report(code: $code) {
    phases { encounterID phases { id name isIntermission } }
  } }
}
"""

Q_LUST_PROBE = """
query($code: String!, $start: Float!, $end: Float!) {
  reportData {
    report(code: $code) {
      btable: table(dataType: Buffs, startTime: $start, endTime: $end,
                    hostilityType: Friendlies)
    }
  }
}
"""

_cli: WCLV2 | None = None
def cli() -> WCLV2:
    global _cli
    if _cli is None:
        _cli = WCLV2()
    return _cli


def cached(key: str, fn):
    p = SCRATCH / f"{key}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    val = fn()
    p.write_text(json.dumps(val, ensure_ascii=False), encoding="utf-8")
    time.sleep(0.3)
    return val


def med(vals, nd=1):
    return round(float(statistics.median(vals)), nd) if vals else None


def pct_of(vals, q, nd=1):
    if not vals:
        return None
    v = sorted(vals)
    idx = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return round(float(v[idx]), nd)


def table_entries(t):
    if not isinstance(t, dict):
        return []
    inner = t.get("data", t)
    return (inner or {}).get("entries") or []


def spell_db_names() -> dict[int, str]:
    try:
        raw = json.loads((DATA / "spell_db.json").read_text(encoding="utf-8"))
        return {int(k): str(v.get("name_ko") or v.get("name_en") or k)
                for k, v in raw.items() if isinstance(v, dict)}
    except Exception:
        return {}


def main() -> None:
    c = cli()
    db_names = spell_db_names()

    # ── 1) rankings ────────────────────────────────────────────────────────
    zone = cached("zone", lambda: c.query(Q_ZONE, {"id": ZONE_ID}))
    parts = zone["worldData"]["zone"]["partitions"] or []
    part = next((p for p in parts if p.get("default")), {"id": 1, "name": "?"})
    partition = int(part["id"])
    print(f"partition={partition} ({part.get('name')})", flush=True)

    ranks_raw = cached("ranks_p1", lambda: c.query(
        Q_RANKS, {"eid": ENCOUNTER_ID, "page": 1, "partition": partition}))
    rows = (((ranks_raw.get("worldData") or {}).get("encounter") or {})
            .get("characterRankings") or {}).get("rankings") or []
    print(f"characterRankings page1 rows: {len(rows)}", flush=True)

    picks, seen = [], set()
    for i, r in enumerate(rows, 1):
        rep = r.get("report") or {}
        code, fid = rep.get("code"), rep.get("fightID")
        if not code or fid is None or (code, fid) in seen:
            continue
        seen.add((code, fid))
        srv = r.get("server") or {}
        picks.append({
            "rank": i, "character": r.get("name"),
            "server": srv.get("name"), "region": (srv.get("region") or ""),
            "dps": round(float(r.get("amount") or 0), 1),
            "duration_ms": r.get("duration"),
            "code": code, "fight_id": int(fid),
        })
        if len(picks) >= TOP_N:
            break
    print(f"distinct report/fight picks: {len(picks)}", flush=True)

    # ── 2) report meta (code별 그룹) ───────────────────────────────────────
    by_code: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        by_code[p["code"]].append(p)
    metas = {}
    for code, plist in by_code.items():
        fids = sorted({p["fight_id"] for p in plist})
        metas[code] = cached(f"meta_{code}", lambda code=code, fids=fids: c.query(
            Q_REPORT_META, {"code": code, "fids": fids}))["reportData"]["report"]

    # ── 3) fight별 데이터 ──────────────────────────────────────────────────
    fights_out = []
    skipped = []
    for p in picks:
        meta = metas[p["code"]]
        fight = next((f for f in meta.get("fights") or []
                      if f.get("id") == p["fight_id"]), None)
        if not fight:
            skipped.append({**p, "why": "fight not in report meta"})
            continue
        actors = (meta.get("masterData") or {}).get("actors") or []
        fp = set(fight.get("friendlyPlayers") or [])
        cand = [a for a in actors if a.get("name") == p["character"]
                and (not fp or a.get("id") in fp)]
        if not cand:
            cand = [a for a in actors if a.get("name") == p["character"]]
        if not cand:
            skipped.append({**p, "why": "actor not found"})
            continue
        sid = int(cand[0]["id"])
        t0, t1 = float(fight["startTime"]), float(fight["endTime"])
        raw = cached(f"fight_{p['code']}_{p['fight_id']}",
                     lambda p=p, t0=t0, t1=t1, sid=sid: c.query(Q_FIGHT, {
                         "code": p["code"], "start": t0, "end": t1, "sid": sid}))
        rep = raw["reportData"]["report"]
        if (rep.get("casts") or {}).get("nextPageTimestamp"):
            print(f"  WARN casts paginated: {p['code']}#{p['fight_id']}", flush=True)
        fights_out.append({
            "pick": p, "fight": fight, "sid": sid,
            "casts": (rep.get("casts") or {}).get("data") or [],
            "deaths": (rep.get("deaths") or {}).get("data") or [],
            "ctable": table_entries(rep.get("ctable")),
            "dtable": table_entries(rep.get("dtable")),
        })
    print(f"fights fetched: {len(fights_out)}  skipped: {len(skipped)}", flush=True)

    # ── 4) 이름→ID 발견 (Casts table 전수 집계) ────────────────────────────
    name_by_id: dict[int, str] = {}
    cast_total = Counter()
    cast_fights = Counter()
    for fo in fights_out:
        seen_ids = set()
        for e in fo["ctable"]:
            gid = int(e.get("guid") or 0)
            nm = str(e.get("name") or gid)
            name_by_id.setdefault(gid, nm)
            cast_total[gid] += int(e.get("total") or 0)
            seen_ids.add(gid)
        for gid in seen_ids:
            cast_fights[gid] += 1

    nf = len(fights_out)
    print(f"\n== 발견된 캐스트 능력 (판 {nf}) ==", flush=True)
    for gid, tot in cast_total.most_common(60):
        print(f"  {gid:>8} {name_by_id.get(gid, '?'):<24} 총{tot:>6}  출현 {cast_fights[gid]}/{nf}", flush=True)

    def discover(rules):
        found = {}
        for key, test in rules:
            ids = sorted(gid for gid, nm in name_by_id.items() if test(nm))
            if ids:
                found[key] = {"ids": ids,
                              "names": [name_by_id[i] for i in ids],
                              "names_ko": [db_names.get(i) for i in ids],
                              "fights_present": max(cast_fights[i] for i in ids),
                              "total_casts": sum(cast_total[i] for i in ids)}
        return found

    major = discover(MAJOR_NAME_RULES)
    defs = discover(DEF_NAME_RULES)
    consum_ids = {gid: nm for gid, nm in name_by_id.items() if is_consumable(nm)}
    print("\n== 주요 쿨기 매핑 ==", flush=True)
    for k, v in major.items():
        print(f"  {k}: {v}", flush=True)
    print("== 생존기 매핑 ==", flush=True)
    for k, v in defs.items():
        print(f"  {k}: {v}", flush=True)
    print(f"== 소모품 == {consum_ids}", flush=True)

    # 미분류 상위 캐스트 확인용 (매핑 누락 감시)
    mapped = set()
    for v in list(major.values()) + list(defs.values()):
        mapped.update(v["ids"])
    mapped.update(consum_ids)

    # ── 5) fight별 파싱 ───────────────────────────────────────────────────
    def rel(ts, t0):
        return round((ts - t0) / 1000, 3)

    per_fight = []
    for fo in fights_out:
        p, fight, sid = fo["pick"], fo["fight"], fo["sid"]
        t0, t1 = float(fight["startTime"]), float(fight["endTime"])
        dur = round((t1 - t0) / 1000, 3)
        casts = [(int(e["timestamp"]), int(e.get("abilityGameID") or 0))
                 for e in fo["casts"] if e.get("type") == "cast"]
        casts.sort()

        def times_of(ids):
            s = set(ids)
            return [rel(ts, t0) for ts, gid in casts if gid in s]

        major_t = {k: times_of(v["ids"]) for k, v in major.items()}
        def_t = {k: times_of(v["ids"]) for k, v in defs.items()}
        consum_t = defaultdict(list)
        for ts, gid in casts:
            if gid in consum_ids:
                consum_t[consum_ids[gid]].append(rel(ts, t0))

        # 사망 (본인만)
        my_deaths = []
        for d in fo["deaths"]:
            if int(d.get("targetID") or 0) != sid:
                continue
            aid = int(d.get("killingAbilityGameID") or 0)
            my_deaths.append({
                "t_s": rel(float(d["timestamp"]), t0),
                "ability_id": aid,
                "ability": db_names.get(aid, name_by_id.get(aid, str(aid))),
            })

        # 딜링 능력 캐스트 (DamageDone ∩ Casts — 이름 기준 매칭:
        # 죽음의 고리 캐스트 47541 ↔ 피해 47632 처럼 ID가 갈리는 스펠 대응)
        dmg_by_name: dict[str, int] = {}
        for e in fo["dtable"]:
            nm = str(e.get("name") or "")
            dmg_by_name[nm] = dmg_by_name.get(nm, 0) + int(e.get("total") or 0)
        rot_all = {}
        for e in fo["ctable"]:
            gid = int(e.get("guid") or 0)
            nm = str(e.get("name") or "")
            if dmg_by_name.get(nm, 0) > 0:
                n = int(e.get("total") or 0)
                rot_all[str(gid)] = {"name": nm, "casts": n,
                                     "cpm": round(n / (dur / 60), 2),
                                     "damage": dmg_by_name[nm]}
        rot = sorted(
            ({"id": int(gid), **r} for gid, r in rot_all.items()),
            key=lambda r: -r["casts"])[:6]

        phases = [{"phase": int(pt.get("id") or 0),
                   "t_s": rel(float(pt.get("startTime") or t0), t0)}
                  for pt in fight.get("phaseTransitions") or []]

        per_fight.append({
            "report": p["code"], "fight_id": p["fight_id"],
            "url": f"https://www.warcraftlogs.com/reports/{p['code']}#fight={p['fight_id']}",
            "character": p["character"], "server": p["server"],
            "region": p["region"], "rank": p["rank"], "dps": p["dps"],
            "kill": bool(fight.get("kill")),
            "boss_pct_left": float(fight.get("bossPercentage") or 0),
            "last_phase": int(fight.get("lastPhase") or 0),
            "duration_s": dur,
            "phase_transitions": phases,
            "major_cd_times_s": major_t,
            "defensive_times_s": def_t,
            "consumable_times_s": dict(consum_t),
            "deaths": my_deaths,
            "top6_rotational": rot,
            "rot_all": rot_all,
            "total_casts": len(casts),
            "cpm": round(len(casts) / (dur / 60), 2),
        })

    kills = [f for f in per_fight if f["kill"]]
    print(f"\nkills: {len(kills)}/{len(per_fight)}", flush=True)

    # 사망 원인 이름 해석 (스펠DB에 없으면 해당 report masterData 조회)
    unresolved: dict[str, set[int]] = defaultdict(set)
    for f in per_fight:
        for d in f["deaths"]:
            if d["ability_id"] and d["ability"] == str(d["ability_id"]):
                unresolved[f["report"]].add(d["ability_id"])
    for code in unresolved:
        md = cached(f"abilities_{code}", lambda code=code: c.query(
            Q_ABILITIES, {"code": code}))
        amap = {int(r["gameID"]): str(r["name"])
                for r in (((md["reportData"]["report"] or {})
                           .get("masterData") or {}).get("abilities") or [])
                if r.get("gameID")}
        for f in per_fight:
            if f["report"] != code:
                continue
            for d in f["deaths"]:
                if d["ability_id"] in amap:
                    d["ability"] = f"{amap[d['ability_id']]} ({d['ability_id']})"

    # ── 5.5) 페이즈 이름 (report 1개에서 조회) ─────────────────────────────
    phase_names = {}
    if picks:
        pn = cached("phase_names", lambda: c.query(
            Q_PHASE_NAMES, {"code": picks[0]["code"]}))
        for enc in ((pn["reportData"]["report"] or {}).get("phases") or []):
            if enc.get("encounterID") == ENCOUNTER_ID:
                phase_names = {
                    f"P{ph['id']}": {"name": ph.get("name"),
                                     "intermission": bool(ph.get("isIntermission"))}
                    for ph in enc.get("phases") or []}
    print(f"phase names: {phase_names}", flush=True)

    # ── 6) 블러드 탐지 (킬 1판 raid-wide Buffs table 프로브) ───────────────
    lust_hits = []
    if fights_out:
        fo = fights_out[0]
        t0 = float(fo["fight"]["startTime"]); t1 = float(fo["fight"]["endTime"])
        lb = cached("lust_probe", lambda: c.query(Q_LUST_PROBE, {
            "code": fo["pick"]["code"], "start": t0, "end": t1}))
        for e in table_entries((lb["reportData"]["report"] or {}).get("btable")):
            nm = str(e.get("name") or "")
            if any(k in nm for k in LUST_KEYS):
                lust_hits.append({"id": e.get("guid"), "name": nm,
                                  "totalUses": e.get("totalUses")})
    print(f"lust probe hits: {lust_hits}", flush=True)

    # ── 7) 집계 ────────────────────────────────────────────────────────────
    src = kills if len(kills) >= 15 else per_fight
    tag = "kills_only" if len(kills) >= 15 else "kills+best_wipes"
    durs = [f["duration_s"] for f in src]

    def agg_cd(key, group):
        counts, firsts, gaps, cpms = [], [], [], []
        phase_hist = Counter()
        used = 0
        for f in src:
            ts = f[group].get(key) or []
            counts.append(len(ts))
            if ts:
                used += 1
                firsts.append(ts[0])
                gaps.extend(round(b - a, 1) for a, b in zip(ts, ts[1:]))
                cpms.append(len(ts) / (f["duration_s"] / 60))
                # 페이즈 분포
                trans = sorted(f["phase_transitions"], key=lambda x: x["t_s"])
                for t in ts:
                    ph = 0
                    for tr in trans:
                        if t >= tr["t_s"]:
                            ph = tr["phase"]
                    phase_hist[f"P{ph}"] += 1
        if not any(counts):
            return None
        return {
            "fights_used_pct": round(100 * used / len(src)),
            "casts_per_fight_med": med(counts, 1),
            "casts_per_fight_p25_p75": [pct_of(counts, .25), pct_of(counts, .75)],
            "casts_per_min_med": med(cpms, 2),
            "first_cast_med_s": med(firsts, 1),
            "first_cast_p25_p75": [pct_of(firsts, .25), pct_of(firsts, .75)],
            "gap_med_s": med(gaps, 1),
            "gap_p25_p75": [pct_of(gaps, .25), pct_of(gaps, .75)],
            "total_casts": sum(counts),
            "phase_hist": dict(phase_hist),
        }

    agg_major = {k: agg_cd(k, "major_cd_times_s") for k in major}
    agg_def = {k: agg_cd(k, "defensive_times_s") for k in defs}

    # 물약/돌
    pot_counts, pot_first, pot_second, hs_counts = [], [], [], []
    pot_kinds = Counter()
    for f in src:
        pots, hs = [], 0
        for nm, ts in f["consumable_times_s"].items():
            if "치유의 돌" in nm or "Healthstone" in nm:
                hs += len(ts)
            elif "생명력" in nm or "Health Potion" in nm:  # 힐물약은 별도 분류
                pot_kinds[nm + " (힐)"] += len(ts)
            else:
                pots.extend(ts)
                pot_kinds[nm] += len(ts)
        pots.sort()
        pot_counts.append(len(pots))
        hs_counts.append(hs)
        if pots:
            pot_first.append(pots[0])
        if len(pots) >= 2:
            pot_second.append(pots[1])

    # 로테이션 상위 (전 판, 딜링 캐스트 전수 → 총 캐스트 기준 상위 8)
    rot_tot = Counter()
    rot_cpm = defaultdict(list)
    rot_name = {}
    for f in src:
        for gid_s, r in f["rot_all"].items():
            gid = int(gid_s)
            rot_tot[gid] += r["casts"]
            rot_cpm[gid].append(r["cpm"])
            rot_name[gid] = r["name"]
    rot_agg = [{"id": gid, "name": rot_name[gid], "total_casts": tot,
                "cpm_med": med(rot_cpm[gid], 2),
                "fights_present": len(rot_cpm[gid])}
               for gid, tot in rot_tot.most_common(8)]

    death_fights = sum(1 for f in src if f["deaths"])
    all_deaths = [d for f in src for d in f["deaths"]]

    # Charge!↔Army 결합도 (돌격!이 독립 쿨기인지 검증)
    chg_total, chg_near_army = 0, 0
    for f in src:
        army_ts = f["major_cd_times_s"].get("army") or []
        for t in f["major_cd_times_s"].get("charge_horsemen") or []:
            chg_total += 1
            if any(abs(t - a) <= 3 for a in army_ts):
                chg_near_army += 1
    charge_army_coupling_pct = (
        round(100 * chg_near_army / chg_total, 1) if chg_total else None)

    # 페이즈 전환 통계
    phase_starts = defaultdict(list)
    for f in src:
        for tr in f["phase_transitions"]:
            phase_starts[f"P{tr['phase']}"].append(tr["t_s"])
    phase_agg = {k: {"n": len(v), "start_med_s": med(v, 1)}
                 for k, v in sorted(phase_starts.items())}

    aggregates = {
        "sample": tag, "n_fights": len(src),
        "duration_med_s": med(durs, 1),
        "duration_p25_p75": [pct_of(durs, .25), pct_of(durs, .75)],
        "phase_names": phase_names,
        "phase_starts": phase_agg,
        "major_cds": agg_major,
        "defensives": agg_def,
        "potions": {
            "per_fight_med": med(pot_counts, 1),
            "fights_with_pot_pct": round(100 * sum(1 for x in pot_counts if x) / len(src)),
            "fights_with_2pots_pct": round(100 * sum(1 for x in pot_counts if x >= 2) / len(src)),
            "first_pot_med_s": med(pot_first, 1),
            "second_pot_med_s": med(pot_second, 1),
            "kinds": dict(pot_kinds),
        },
        "healthstone": {
            "total_uses": sum(hs_counts),
            "fights_used_pct": round(100 * sum(1 for x in hs_counts if x) / len(src)),
        },
        "deaths": {
            "fights_with_death": death_fights,
            "death_rate_pct": round(100 * death_fights / len(src), 1),
            "total_deaths": len(all_deaths),
            "causes": dict(Counter(d["ability"] for d in all_deaths)),
        },
        "rotational_top": rot_agg,
        "total_cpm_med": med([f["cpm"] for f in src], 2),
        "charge_army_coupling_pct": charge_army_coupling_pct,
        "bloodlust": {
            "probe_fight": f"{fights_out[0]['pick']['code']}#{fights_out[0]['pick']['fight_id']}" if fights_out else None,
            "hits": lust_hits,
            "note": "raid-wide Buffs table 1판 프로브. 미드나잇엔 블러드 계열 부재(기존 BM 채굴 0/362킬과 일치)" if not lust_hits else "블러드 감지됨",
        },
    }

    # ── 8) 핸드체크 (1위 판 상세 출력 → 집계 대조) ─────────────────────────
    hc = per_fight[0]
    print("\n== 핸드체크: rank1 판 ==", flush=True)
    print(f"  {hc['character']}@{hc['server']} {hc['report']}#{hc['fight_id']} "
          f"dur={hc['duration_s']}s kill={hc['kill']} dps={hc['dps']}", flush=True)
    print(f"  phases: {hc['phase_transitions']}", flush=True)
    for k, ts in hc["major_cd_times_s"].items():
        if ts:
            print(f"  CD {k}: n={len(ts)} times={[round(t,1) for t in ts]}", flush=True)
    for k, ts in hc["defensive_times_s"].items():
        if ts:
            print(f"  DEF {k}: n={len(ts)} times={[round(t,1) for t in ts]}", flush=True)
    print(f"  consumables: {hc['consumable_times_s']}", flush=True)
    print(f"  deaths: {hc['deaths']}", flush=True)
    print(f"  top6 rot: {[(r['name'], r['casts']) for r in hc['top6_rotational']]}", flush=True)

    out = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "encounter_id": ENCOUNTER_ID, "encounter": "한밤의 도래 (L'ura)",
            "difficulty": "Mythic", "zone": ZONE_ID, "partition": partition,
            "class_spec": "DeathKnight/Unholy (부정 죽음의 기사)",
            "metric": "dps", "source": "characterRankings top page1",
            "sample": tag, "n_fights": len(per_fight),
            "n_kills": len(kills),
            "skipped": skipped,
            "ability_id_map": {
                "major": major, "defensive": defs,
                "consumable": {str(k): v for k, v in consum_ids.items()},
            },
            "notes": [
                "스펠 ID는 25개 킬 로그의 Casts table 이름 매칭으로 발견 (기억 의존 없음).",
                "어둠의 변신 ID가 1233448 로 변경됨 (구 63560 아님) — 12.0.7 실측.",
                "대재앙/가고일/부정 폭행/룬 무기 강화/죽음의 진군/흉물 되살리기: 25/25 킬에서 캐스트 0회 — 미드나잇 UDK 킷에서 부재.",
                "신규 관측: 돌격!(1259633, Rider 기병), 죽음의 진격(444347, 이동기), 무덤(383269), 사령의 고리(1242174 Necrotic Coil), 문드러진 낫(458128), 부패(1247378 Putrefy).",
                "돌격!은 사자의 군대와 3초 내 결합 — 독립 쿨기가 아니라 군대 시전에 따라오는 기병 소환.",
                "블러드/영웅심: raid-wide Buffs 프로브 0건 — 미드나잇 블러드 부재 (기존 BM 채굴 0/362킬과 일치).",
                "characterRankings dps 랭킹은 킬 전용 → 전 표본 킬.",
            ],
        },
        "aggregates": aggregates,
        "hand_check": {
            "which": "fights[0] = rank1",
            "report": per_fight[0]["report"], "fight_id": per_fight[0]["fight_id"],
            "url": per_fight[0]["url"],
            "expect": {
                "army_times_s": per_fight[0]["major_cd_times_s"].get("army"),
                "dark_transformation_n": len(
                    per_fight[0]["major_cd_times_s"].get("dark_transformation") or []),
                "ams_times_s": per_fight[0]["defensive_times_s"].get("ams"),
                "potions": per_fight[0]["consumable_times_s"],
                "deaths": per_fight[0]["deaths"],
            },
        },
        "fights": per_fight,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {OUT}", flush=True)

    # 요약 콘솔
    print("\n== 집계 요약 ==", flush=True)
    print(f"  표본 {tag} n={len(src)}  킬시간 med {aggregates['duration_med_s']}s", flush=True)
    for k, a in agg_major.items():
        if a:
            print(f"  {k:<20} 판당 {a['casts_per_fight_med']} (사용 {a['fights_used_pct']}%) "
                  f"첫 {a['first_cast_med_s']}s 간격 {a['gap_med_s']}s 페이즈 {a['phase_hist']}", flush=True)
    for k, a in agg_def.items():
        if a:
            print(f"  DEF {k:<16} 판당 {a['casts_per_fight_med']} (사용 {a['fights_used_pct']}%) "
                  f"첫 {a['first_cast_med_s']}s", flush=True)
    print(f"  물약 {aggregates['potions']}", flush=True)
    print(f"  사망률 {aggregates['deaths']['death_rate_pct']}% "
          f"({aggregates['deaths']['fights_with_death']}/{len(src)}판)", flush=True)
    rate = c.points_left()
    if rate:
        print(f"  rate: {rate['pointsSpentThisHour']:.1f}/{rate['limitPerHour']}", flush=True)


if __name__ == "__main__":
    main()
