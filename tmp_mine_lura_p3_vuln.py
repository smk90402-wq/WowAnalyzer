"""르우라(한밤의 도래 3183 신화) P3 'Midnight Falls' 보스 취약(받는피해증가) 창 채굴.

질문: 상위권 2번째 전투물약이 ~364-370s(=Midnight+34~40s), 영겁의 숨결이 Midnight+29s 에
몰리는 이유가 보스에게 고정 타이밍으로 걸리는 받는피해증가 디버프(취약창) 때문인가?
아니면 쫄 사망/수정 납품 버프 등 다른 이유의 딜 스파이크인가?

방법 (top kill 5판, 서로 다른 report):
  1. 보스 액터 확정 (masterData NPC actors, 이름 'ura' 매칭; L'ura 동명 액터 2개면 둘 다 추적)
  2. 전투 전체 events(Debuffs + Buffs, hostilityType:Enemies) 페이지네이션 →
     클라 측 targetID==보스 필터 → (gid,source)별 창 → gid 별 합집합 창 → [330,480]s 겹침 보고
  3. 300~480s 15s 슬라이스 x12 별칭 table(DamageDone) — 전체/보스/제2보스 시리즈
  4. 스파이크 슬라이스 vs 아우라 창 정렬(±5s) 교차검증 + 집단 디버프 소거 시각(면역 창 추정)
  5. (1판만) 공대 Buffs table [340,400] vs [260,320] 비교 — 새로 등장하는 버프 탐색

사용: python tmp_mine_lura_p3_vuln.py           → data/lura_p3_vuln_mining.json
      python tmp_mine_lura_p3_vuln.py explore   → 첫 1판 상세 관측만
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

from wcl_v2 import WCLV2

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SCRATCH = Path(
    r"C:\Users\smk90\AppData\Local\Temp\claude"
    r"\C--Users-smk90-OneDrive-------LogAnalyze"
    r"\66e6c09f-1b73-4a06-9a39-f108d6bcda2a\scratchpad"
) / "lura_p3_vuln_cache"
SCRATCH.mkdir(parents=True, exist_ok=True)

SRC = DATA / "lura_top_aug_mining.json"
OUT = DATA / "lura_p3_vuln_mining.json"
N_REPORTS = 5
WIN_LO, WIN_HI = 330.0, 480.0        # P3 관심 구간 (전투 상대초)
SLICE_LO, SLICE_HI, SLICE_W = 300.0, 480.0, 15.0
POT2_BAND = (364.0, 370.0)           # 알려진 2물약 군집
BREATH_REL_MIDNIGHT = 29.0           # 알려진 숨결 타이밍 (Midnight+29s)

# 받는피해증가 계열 이름 키워드 (report 언어가 en/ko/zh 혼재 가능)
VULN_KEYWORDS = [
    "vulnerab", "damage taken", "amplif", "sunder", "expose",
    "취약", "받는 피해", "받는피해",
    "易伤", "易傷", "受到的伤害", "受到的傷害",
]
KNOWN_CLASS_DEBUFFS = {1490: "Chaos Brand(+3% 마법)", 113746: "Mystic Touch(+3% 물리)"}
BLOODLUST_IDS = (2825, 32182, 80353, 264667, 272678, 390386, 466904,
                 178207, 230935, 256740, 309658, 444257)


def load_spell_db() -> dict[int, dict]:
    try:
        db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
        return {int(k): v for k, v in db.items() if isinstance(v, dict)}
    except Exception:
        return {}


SPELL_DB = load_spell_db()


def mmss(t: float | None) -> str:
    if t is None:
        return "-"
    sign = "-" if t < 0 else ""
    t = abs(t)
    return f"{sign}{int(t) // 60}:{int(t) % 60:02d}"


def med(vals, nd=1):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), nd) if vals else None


def vuln_flag(gid: int, name: str) -> str | None:
    if gid in KNOWN_CLASS_DEBUFFS:
        return KNOWN_CLASS_DEBUFFS[gid]
    low = (name or "").lower()
    ko = (SPELL_DB.get(gid) or {}).get("name_ko") or ""
    en = ((SPELL_DB.get(gid) or {}).get("name_en") or "").lower()
    for kw in VULN_KEYWORDS:
        k = kw.lower()
        if k in low or k in en or kw in ko or kw in name:
            return f"이름 키워드 '{kw}'"
    return None


def cached(key: str, fn):
    f = SCRATCH / f"{key}.json"
    if f.exists():
        return json.load(open(f, encoding="utf-8"))
    out = fn()
    json.dump(out, open(f, "w", encoding="utf-8"), ensure_ascii=False)
    time.sleep(0.3)
    return out


Q_FIGHT = """
query($code: String!, $fid: Int!) {
  reportData { report(code: $code) {
    fights(fightIDs: [$fid]) {
      id startTime endTime kill lastPhase
      phaseTransitions { id startTime }
      enemyNPCs { id gameID }
    }
    masterData(translate: true) {
      actors(type: "NPC") { id name gameID }
      abilities { gameID name }
    }
  } }
}
"""


def fetch_enemy_auras(cli: WCLV2, code: str, fid: int, t0: float, t1: float,
                      data_type: str) -> list[dict]:
    """전투 전체 적 대상 aura 이벤트 (페이지네이션)."""
    rows: list[dict] = []
    cursor = t0
    for page in range(20):
        def fn(cursor=cursor):
            return cli.query(
                "query($code:String!,$s:Float!,$e:Float!){reportData{report(code:$code){"
                f"events(dataType:{data_type},hostilityType:Enemies,"
                "startTime:$s,endTime:$e,limit:10000){data nextPageTimestamp}"
                "}}}",
                {"code": code, "s": cursor, "e": t1},
            )
        d = cached(f"{data_type.lower()}_{code}_{fid}_p{page}", fn)
        ev = ((d["reportData"]["report"] or {}).get("events")) or {}
        rows.extend(ev.get("data") or [])
        nxt = ev.get("nextPageTimestamp")
        if not nxt:
            break
        cursor = float(nxt)
    else:
        raise RuntimeError(f"{code}#{fid} {data_type} 20페이지 초과")
    return rows


def slice_query(code: str, t0: float, boss_id: int | None,
                boss2_id: int | None) -> str:
    """300~480s 15s x12 — 전체 + 보스 + 제2보스 DamageDone 별칭 테이블."""
    fields = []
    n = int((SLICE_HI - SLICE_LO) / SLICE_W)
    for i in range(n):
        s = t0 + (SLICE_LO + i * SLICE_W) * 1000
        e = t0 + (SLICE_LO + (i + 1) * SLICE_W) * 1000
        win = f"startTime:{s:.1f},endTime:{e:.1f}"
        fields.append(f"a{i}:table(dataType:DamageDone,{win})")
        if boss_id is not None:
            fields.append(f"b{i}:table(dataType:DamageDone,{win},targetID:{boss_id})")
        if boss2_id is not None:
            fields.append(f"c{i}:table(dataType:DamageDone,{win},targetID:{boss2_id})")
    return ("query{reportData{report(code:\"" + code + "\"){"
            + " ".join(fields) + "}}}")


def lust_query(code: str, t0: float, t1: float) -> str:
    fields = []
    for sid in BLOODLUST_IDS:
        fields.append(
            f"s{sid}:events(dataType:Casts,startTime:{t0:.1f},endTime:{t1:.1f},"
            f"abilityID:{sid},hostilityType:Friendlies,limit:100){{data}}")
    return ("query{reportData{report(code:\"" + code + "\"){"
            + " ".join(fields) + "}}}")


def table_total(tbl: dict | None) -> float:
    data = ((tbl or {}).get("data")) or {}
    return sum(float(r.get("total") or 0) for r in data.get("entries") or [])


APPLY_T = {"applydebuff", "applybuff"}
STACK_T = {"applydebuffstack", "applybuffstack"}
REFRESH_T = {"refreshdebuff", "refreshbuff"}
REMOVE_T = {"removedebuff", "removebuff"}


def aura_windows_on(events: list[dict], target_id: int, t0: float, dur: float):
    """(gid,source)별 창 → gid 별 {union windows, sources, orphan_removes, max_stack}."""
    open_at: dict[tuple[int, int], dict] = {}
    raw: dict[int, list[dict]] = defaultdict(list)
    orphan: Counter = Counter()
    sources: dict[int, set[int]] = defaultdict(set)
    for ev in sorted(events, key=lambda x: x.get("timestamp") or 0):
        if int(ev.get("targetID") or 0) != target_id:
            continue
        gid = int(ev.get("abilityGameID") or 0)
        src = int(ev.get("sourceID") or 0)
        key = (gid, src)
        typ = ev.get("type") or ""
        t = (float(ev["timestamp"]) - t0) / 1000
        sources[gid].add(src)
        if typ in APPLY_T:
            if key not in open_at:
                open_at[key] = {"s": t, "max_stack": 1}
        elif typ in STACK_T:
            cur = open_at.setdefault(key, {"s": t, "max_stack": 1})
            cur["max_stack"] = max(cur["max_stack"], int(ev.get("stack") or 0) or 1)
        elif typ in REFRESH_T:
            open_at.setdefault(key, {"s": t, "max_stack": 1})
        elif typ in REMOVE_T:
            cur = open_at.pop(key, None)
            if cur is None:
                orphan[gid] += 1          # apply 없는 remove → 창 만들지 않음
                continue
            raw[gid].append({"s": round(cur["s"], 1), "e": round(t, 1),
                             "max_stack": cur["max_stack"]})
    for (gid, _src), cur in open_at.items():
        raw[gid].append({"s": round(cur["s"], 1), "e": round(dur, 1),
                         "max_stack": cur["max_stack"]})

    out = {}
    for gid, ws in raw.items():
        ws.sort(key=lambda w: (w["s"], w["e"]))
        merged: list[dict] = []
        for w in ws:
            if merged and w["s"] <= merged[-1]["e"] + 0.1:
                merged[-1]["e"] = max(merged[-1]["e"], w["e"])
                merged[-1]["max_stack"] = max(merged[-1]["max_stack"], w["max_stack"])
            else:
                merged.append(dict(w))
        out[gid] = {
            "windows": merged,
            "n_sources": len(sources[gid]),
            "source_ids": sorted(sources[gid]),
            "orphan_removes": orphan.get(gid, 0),
        }
    return out


def mass_remove_times(events: list[dict], target_id: int, t0: float,
                      min_kinds: int = 10) -> list[float]:
    """0.5s 안에 서로 다른 gid 가 min_kinds 종 이상 제거되는 시각 → 면역/소거 추정."""
    removes = sorted(
        ((float(ev["timestamp"]) - t0) / 1000, int(ev.get("abilityGameID") or 0))
        for ev in events
        if ev.get("type") in REMOVE_T and int(ev.get("targetID") or 0) == target_id)
    out, i = [], 0
    while i < len(removes):
        j = i
        kinds = set()
        while j < len(removes) and removes[j][0] - removes[i][0] <= 0.5:
            kinds.add(removes[j][1])
            j += 1
        if len(kinds) >= min_kinds:
            out.append(round(removes[i][0], 1))
            i = j
        else:
            i += 1
    return out


def clip_windows(ws: list[dict]) -> tuple[list[dict], float]:
    hit = [w for w in ws if w["e"] > WIN_LO and w["s"] < WIN_HI]
    up = round(sum(min(w["e"], WIN_HI) - max(w["s"], WIN_LO) for w in hit), 1)
    return hit, up


def overlap_report(win_map: dict, ability_names: dict[int, str],
                   npc_ids: set[int]) -> dict:
    out = {}
    for gid, info in win_map.items():
        hit, up = clip_windows(info["windows"])
        if not hit:
            continue
        name = ability_names.get(gid) or (SPELL_DB.get(gid) or {}).get("name_ko") \
               or (SPELL_DB.get(gid) or {}).get("name_en") or str(gid)
        out[gid] = {
            "name": name,
            "vuln_hint": vuln_flag(gid, name),
            "npc_or_env_sourced": any(s <= 0 or s in npc_ids
                                      for s in info["source_ids"]),
            "n_sources": info["n_sources"],
            "orphan_removes": info["orphan_removes"],
            "all_windows": info["windows"],
            "windows_in_330_480": hit,
            "uptime_in_330_480_s": up,
        }
    return out


def mine_fight(cli: WCLV2, code: str, fid: int, explore: bool) -> dict:
    q1 = cached(f"q1_{code}_{fid}",
                lambda: cli.query(Q_FIGHT, {"code": code, "fid": fid}))
    rep = q1["reportData"]["report"]
    fight = (rep.get("fights") or [None])[0]
    if not fight:
        raise RuntimeError("fight 없음")
    t0, t1 = float(fight["startTime"]), float(fight["endTime"])
    dur = (t1 - t0) / 1000
    trans = [{"id": p["id"], "t": round((float(p["startTime"]) - t0) / 1000, 1)}
             for p in fight.get("phaseTransitions") or []]
    p3 = next((p["t"] for p in trans if p["id"] == 4), None)
    p5 = next((p["t"] for p in trans if p["id"] == 5), None)

    master = rep.get("masterData") or {}
    npc_by_id = {int(a["id"]): a for a in master.get("actors") or []}
    ability_names = {int(a["gameID"]): a.get("name") or ""
                     for a in master.get("abilities") or []
                     if a.get("gameID") is not None}
    enemy_ids = [int(e["id"]) for e in fight.get("enemyNPCs") or []]

    debuff_rows = fetch_enemy_auras(cli, code, fid, t0, t1, "Debuffs")
    buff_rows = fetch_enemy_auras(cli, code, fid, t0, t1, "Buffs")
    hits_per_target = Counter(int(ev.get("targetID") or 0) for ev in debuff_rows)

    # ── 1) 보스 액터 (동명 L'ura 2개 가능 — 디버프 많은 쪽이 본체) ──────
    lura_ids = [aid for aid in enemy_ids
                if "르우라" in ((npc_by_id.get(aid) or {}).get("name") or "")
                or "ura" in ((npc_by_id.get(aid) or {}).get("name") or "").lower()
                or "乌拉" in ((npc_by_id.get(aid) or {}).get("name") or "")]
    lura_ids.sort(key=lambda a: -hits_per_target.get(a, 0))
    boss_id = lura_ids[0] if lura_ids else None
    boss2_id = lura_ids[1] if len(lura_ids) > 1 else None
    boss_how = "이름 매칭"
    if boss_id is None:
        cand = sorted(((hits_per_target.get(a, 0), a) for a in enemy_ids),
                      reverse=True)
        if cand:
            boss_id, boss_how = cand[0][1], f"디버프 최다 타깃 fallback ({cand[0][0]} evs)"
    boss = npc_by_id.get(boss_id) or {}
    boss2 = npc_by_id.get(boss2_id) or {}

    if explore:
        print("  NPC 액터(적):")
        for aid in enemy_ids:
            a = npc_by_id.get(aid) or {}
            evs = [(float(ev["timestamp"]) - t0) / 1000 for ev in debuff_rows
                   if int(ev.get("targetID") or 0) == aid]
            rng = f"{mmss(min(evs))}~{mmss(max(evs))}" if evs else "-"
            print(f"    id={aid} gameID={a.get('gameID')} name={a.get('name')!r} "
                  f"debuff_evs={len(evs)} range={rng}")

    # ── 2) 보스 디버프/버프 창 ──────────────────────────────────────────
    npc_ids = set(npc_by_id)
    dwin = aura_windows_on(debuff_rows, boss_id, t0, dur)
    bwin = aura_windows_on(buff_rows, boss_id, t0, dur)
    d_overlap = overlap_report(dwin, ability_names, npc_ids)
    b_overlap = overlap_report(bwin, ability_names, npc_ids)
    wipe_times = mass_remove_times(debuff_rows, boss_id, t0)

    d2_overlap = {}
    if boss2_id is not None:
        d2 = aura_windows_on(debuff_rows, boss2_id, t0, dur)
        d2_overlap = overlap_report(d2, ability_names, npc_ids)

    # ── 3) 딜 슬라이스 ─────────────────────────────────────────────────
    q3 = cached(f"slices2_{code}_{fid}",
                lambda: cli.query(slice_query(code, t0, boss_id, boss2_id)))
    r3 = q3["reportData"]["report"]
    n = int((SLICE_HI - SLICE_LO) / SLICE_W)
    slices = []
    for i in range(n):
        s = SLICE_LO + i * SLICE_W
        tot = table_total(r3.get(f"a{i}"))
        bos = table_total(r3.get(f"b{i}")) if boss_id is not None else 0.0
        bos2 = table_total(r3.get(f"c{i}")) if boss2_id is not None else 0.0
        slices.append({
            "t0": s, "t1": s + SLICE_W,
            "raid_dps": round(tot / SLICE_W),
            "boss_dps": round(bos / SLICE_W),
            "boss2_dps": round(bos2 / SLICE_W),
            "other_dps": round((tot - bos - bos2) / SLICE_W),
        })
    spike = max(slices, key=lambda x: x["raid_dps"])
    spike_boss = max(slices, key=lambda x: x["boss_dps"] + x["boss2_dps"])

    # ── 3b) 블러드러스트 시전 시각 ─────────────────────────────────────
    q4 = cached(f"lust_{code}_{fid}",
                lambda: cli.query(lust_query(code, t0, t1)))
    r4 = q4["reportData"]["report"]
    lust_casts = []
    for sid in BLOODLUST_IDS:
        for ev in ((r4.get(f"s{sid}") or {}).get("data")) or []:
            if ev.get("type") != "cast":
                continue
            lust_casts.append({
                "spell_id": sid,
                "name": ability_names.get(sid, str(sid)),
                "t": round((float(ev["timestamp"]) - t0) / 1000, 1),
            })
    lust_casts.sort(key=lambda x: x["t"])
    for lc in lust_casts:
        lc["rel_midnight_s"] = round(lc["t"] - p3, 1) if p3 is not None else None

    # ── 4) 정렬 교차검증 ───────────────────────────────────────────────
    aligned = []
    for gid, info in {**d_overlap, **{f"buff_{k}": v for k, v in b_overlap.items()}}.items():
        for w in info["windows_in_330_480"]:
            ov = min(w["e"], spike["t1"]) - max(w["s"], spike["t0"])
            if ov > 0 or abs(w["s"] - spike["t0"]) <= 5:
                aligned.append({
                    "ability_id": gid, "name": info["name"],
                    "window": [w["s"], w["e"]], "max_stack": w["max_stack"],
                    "overlap_with_spike_s": round(max(ov, 0), 1),
                    "start_minus_spike_start_s": round(w["s"] - spike["t0"], 1),
                    "vuln_hint": info["vuln_hint"],
                    "npc_or_env_sourced": info["npc_or_env_sourced"],
                })

    return {
        "report": code, "fight_id": fid,
        "url": f"https://www.warcraftlogs.com/reports/{code}#fight={fid}",
        "_start_ms": t0,
        "duration_s": round(dur, 1), "kill": bool(fight.get("kill")),
        "p3_start_s": p3, "p4_reintegration_start_s": p5,
        "boss_actor": {"id": boss_id, "name": boss.get("name"),
                       "gameID": boss.get("gameID"), "resolved_by": boss_how},
        "boss2_actor": ({"id": boss2_id, "name": boss2.get("name"),
                         "gameID": boss2.get("gameID")} if boss2_id else None),
        "debuff_events_total": len(debuff_rows),
        "debuff_events_on_boss": hits_per_target.get(boss_id, 0),
        "mass_debuff_wipe_times_s": wipe_times,
        "boss_debuffs_overlapping_330_480": {str(k): v for k, v in sorted(d_overlap.items())},
        "boss_buffs_overlapping_330_480": {str(k): v for k, v in sorted(b_overlap.items())},
        "boss2_debuffs_overlapping_330_480": {str(k): v for k, v in sorted(d2_overlap.items())},
        "bloodlust_casts": lust_casts,
        "dps_slices_300_480": slices,
        "spike_slice_raid": spike,
        "spike_slice_boss": spike_boss,
        "spike_rel_midnight_s": (round(spike["t0"] - p3, 1) if p3 is not None else None),
        "auras_aligned_with_spike": aligned,
    }


def main():
    explore = "explore" in sys.argv
    cli = WCLV2()
    rate0 = cli.points_left()
    if rate0:
        print(f"rate: {rate0['pointsSpentThisHour']:.0f}/{rate0['limitPerHour']}")

    src = json.load(open(SRC, encoding="utf-8"))
    pairs, seen = [], set()
    for f in src["fights"]:
        if f["report"] in seen:
            continue
        seen.add(f["report"])
        pairs.append((f["report"], int(f["fight_id"]), f.get("p3_start_s")))
        if len(pairs) >= N_REPORTS:
            break
    if explore:
        pairs = pairs[:1]
    print(f"대상 {len(pairs)}판: {[(c, i) for c, i, _ in pairs]}")

    fights, errors = [], []
    for code, fid, _ in pairs:
        try:
            print(f"\n== {code}#{fid}")
            pf = mine_fight(cli, code, fid, explore)
            fights.append(pf)
            print(f"  보스: {pf['boss_actor']}  보스2: {pf['boss2_actor']}")
            print(f"  P3(Midnight)={mmss(pf['p3_start_s'])}  dur={mmss(pf['duration_s'])}")
            print(f"  집단 디버프 소거 시각: {[mmss(t) for t in pf['mass_debuff_wipe_times_s']]}"
                  f"  (rel Midnight {[round(t - pf['p3_start_s'], 1) for t in pf['mass_debuff_wipe_times_s']] if pf['p3_start_s'] else '-'})")
            print("  슬라이스 DPS (raid / boss / boss2 / other):")
            for s in pf["dps_slices_300_480"]:
                bar = "#" * int(s["raid_dps"] / 200000)
                mark = " <== spike" if s is pf["spike_slice_raid"] else ""
                print(f"    {mmss(s['t0'])}-{mmss(s['t1'])}  {s['raid_dps']:>9,} / "
                      f"{s['boss_dps']:>9,} / {s['boss2_dps']:>9,} / {s['other_dps']:>9,}"
                      f"  {bar}{mark}")
            print(f"  spike(raid) @{mmss(pf['spike_slice_raid']['t0'])} "
                  f"(Midnight+{pf['spike_rel_midnight_s']}s)")
            print(f"  블러드러스트 시전: "
                  f"{[(lc['name'], lc['t'], lc['rel_midnight_s']) for lc in pf['bloodlust_casts']]}")
            npc_d = {g: i for g, i in pf["boss_debuffs_overlapping_330_480"].items()
                     if i["npc_or_env_sourced"]}
            vuln_d = {g: i for g, i in pf["boss_debuffs_overlapping_330_480"].items()
                      if i["vuln_hint"]}
            print(f"  [330,480] 보스 디버프 {len(pf['boss_debuffs_overlapping_330_480'])}종 "
                  f"(NPC/환경 소스 {len(npc_d)}종, 취약 키워드 {len(vuln_d)}종)")
            for g, i in {**vuln_d, **npc_d}.items():
                print(f"    D {g:>9} {i['name']:<30} up={i['uptime_in_330_480_s']:>6}s "
                      f"srcs={i['n_sources']} wins={[(w['s'], w['e'], w['max_stack']) for w in i['windows_in_330_480']][:6]} "
                      f"{'★' + str(i['vuln_hint']) if i['vuln_hint'] else ''}")
            print(f"  [330,480] 보스 버프 {len(pf['boss_buffs_overlapping_330_480'])}종:")
            for g, i in pf["boss_buffs_overlapping_330_480"].items():
                print(f"    B {g:>9} {i['name']:<30} up={i['uptime_in_330_480_s']:>6}s "
                      f"srcs={i['n_sources']} wins={[(w['s'], w['e'], w['max_stack']) for w in i['windows_in_330_480']][:6]} "
                      f"{'★' + str(i['vuln_hint']) if i['vuln_hint'] else ''}")
        except Exception as e:
            errors.append({"report": code, "fight_id": fid, "err": str(e)[:250]})
            print(f"  ! 실패: {str(e)[:200]}")

    if not fights:
        raise SystemExit("성공한 판 없음")

    # ── 5) 플레이어 버프 비교 (1판만, 저비용) ─────────────────────────────
    buff_check = None
    try:
        pf0 = fights[0]
        code, fid = pf0["report"], pf0["fight_id"]
        t0 = float(pf0["_start_ms"])
        wa = (t0 + 340_000, t0 + 400_000)   # Midnight+10~70 (물약/스파이크 구간 포함)
        wb = (t0 + 260_000, t0 + 320_000)   # P2 대조군
        qb = cached(f"buffcmp_{code}_{fid}", lambda: cli.query(
            "query{reportData{report(code:\"" + code + "\"){"
            f"wa:table(dataType:Buffs,startTime:{wa[0]:.1f},endTime:{wa[1]:.1f})"
            f"wb:table(dataType:Buffs,startTime:{wb[0]:.1f},endTime:{wb[1]:.1f})"
            "}}}"))
        rb = qb["reportData"]["report"]

        def auras_of(alias):
            data = ((rb.get(alias) or {}).get("data")) or {}
            return {int(a.get("guid") or 0): a for a in data.get("auras") or []}

        aa, bb = auras_of("wa"), auras_of("wb")
        only_a = []
        for gid, a in aa.items():
            if gid in bb:
                continue
            only_a.append({
                "ability_id": gid, "name": a.get("name") or "",
                "total_uses": a.get("totalUses"), "total_uptime_ms": a.get("totalUptime"),
            })
        only_a.sort(key=lambda x: -(x["total_uptime_ms"] or 0))
        buff_check = {
            "report": code, "fight_id": fid,
            "window_new_s": [340, 400], "window_base_s": [260, 320],
            "buffs_only_in_340_400": only_a[:40],
            "n_auras_340_400": len(aa), "n_auras_260_320": len(bb),
        }
        print(f"\n== 버프 비교({code}#{fid}) [340,400] 에만 있는 버프 상위:")
        for b in only_a[:15]:
            print(f"    {b['ability_id']:>9} {b['name']:<34} uses={b['total_uses']} "
                  f"up={b['total_uptime_ms']}ms")
    except Exception as e:
        print(f"버프 비교 실패: {str(e)[:200]}")
        buff_check = {"error": str(e)[:250]}

    if explore:
        return

    # ── 교차 요약 ─────────────────────────────────────────────────────────
    def recurring(kind_key):
        by_gid: dict[int, list[tuple[dict, dict]]] = defaultdict(list)
        for pf in fights:
            for gid_s, info in pf[kind_key].items():
                by_gid[int(gid_s)].append((pf, info))
        recur = []
        for gid, lst in sorted(by_gid.items()):
            if len(lst) < 3:
                continue
            first_rel = [round(info["windows_in_330_480"][0]["s"] - pf["p3_start_s"], 1)
                         for pf, info in lst if pf["p3_start_s"] is not None]
            durs = [round(w["e"] - w["s"], 1)
                    for _, info in lst for w in info["windows_in_330_480"]]
            stacks = [w["max_stack"] for _, info in lst
                      for w in info["windows_in_330_480"]]
            recur.append({
                "ability_id": gid,
                "name": lst[0][1]["name"],
                "fights_seen": len(lst),
                "vuln_hint": lst[0][1]["vuln_hint"],
                "npc_or_env_sourced_any": any(info["npc_or_env_sourced"] for _, info in lst),
                "first_window_rel_midnight_med_s": med(first_rel),
                "window_dur_med_s": med(durs),
                "max_stack_seen": max(stacks) if stacks else None,
                "uptime_330_480_med_s": med([info["uptime_in_330_480_s"] for _, info in lst]),
            })
        recur.sort(key=lambda x: -x["fights_seen"])
        return recur

    recur_d = recurring("boss_debuffs_overlapping_330_480")
    recur_b = recurring("boss_buffs_overlapping_330_480")

    spikes_rel = [pf["spike_rel_midnight_s"] for pf in fights
                  if pf["spike_rel_midnight_s"] is not None]
    lust_p3_rel = [lc["rel_midnight_s"] for pf in fights
                   for lc in pf["bloodlust_casts"]
                   if lc["rel_midnight_s"] is not None and lc["rel_midnight_s"] >= 0]
    wipe_rel = [round(t - pf["p3_start_s"], 1) for pf in fights
                if pf["p3_start_s"] is not None
                for t in pf["mass_debuff_wipe_times_s"]
                if WIN_LO - 20 <= t <= WIN_HI + 20]
    vuln_named = [r for r in recur_d + recur_b
                  if r["vuln_hint"] and r["ability_id"] not in KNOWN_CLASS_DEBUFFS]
    npc_sourced = [r for r in recur_d + recur_b if r["npc_or_env_sourced_any"]]
    summary = {
        "n_fights": len(fights),
        "spike_slice_rel_midnight_all": spikes_rel,
        "spike_slice_rel_midnight_med": med(spikes_rel),
        "known_pot2_band_s": list(POT2_BAND),
        "known_breath_rel_midnight_s": BREATH_REL_MIDNIGHT,
        "bloodlust_in_p3_rel_midnight_all": sorted(lust_p3_rel),
        "bloodlust_in_p3_rel_midnight_med": med(lust_p3_rel),
        "bloodlust_in_p3_fights_n": sum(
            1 for pf in fights if any(
                lc["rel_midnight_s"] is not None and lc["rel_midnight_s"] >= 0
                for lc in pf["bloodlust_casts"])),
        "mass_debuff_wipe_rel_midnight_s": sorted(wipe_rel),
        "recurring_boss_debuffs_330_480": recur_d,
        "recurring_boss_buffs_330_480": recur_b,
        "vuln_keyword_hits_excl_class": vuln_named,
        "npc_or_env_sourced_recurring": npc_sourced,
        "aligned_with_spike_counts": dict(Counter(
            str(a["ability_id"]) for pf in fights
            for a in pf["auras_aligned_with_spike"])),
    }

    print("\n===== 교차 요약 =====")
    print(f"  spike rel Midnight: {spikes_rel} (med {summary['spike_slice_rel_midnight_med']})")
    print(f"  P3 블러드러스트 rel Midnight: {sorted(lust_p3_rel)} "
          f"(med {summary['bloodlust_in_p3_rel_midnight_med']}, "
          f"{summary['bloodlust_in_p3_fights_n']}/{len(fights)}판)")
    print(f"  집단 디버프 소거 rel Midnight: {sorted(wipe_rel)}")
    print(f"  취약 키워드(클래스 제외): {[(r['ability_id'], r['name']) for r in vuln_named]}")
    print(f"  NPC/환경 소스 반복 아우라: {[(r['ability_id'], r['name'], r['first_window_rel_midnight_med_s']) for r in npc_sourced]}")
    print("  3판 이상 반복 보스 디버프 [330,480] 상위:")
    for r in recur_d[:20]:
        print(f"    {r['ability_id']:>9} {r['name']:<30} n={r['fights_seen']} "
              f"first@Mid+{r['first_window_rel_midnight_med_s']}s "
              f"dur~{r['window_dur_med_s']}s stack≤{r['max_stack_seen']} "
              f"{'★' + str(r['vuln_hint']) if r['vuln_hint'] else ''}")
    print("  3판 이상 반복 보스 버프 [330,480]:")
    for r in recur_b:
        print(f"    {r['ability_id']:>9} {r['name']:<30} n={r['fights_seen']} "
              f"first@Mid+{r['first_window_rel_midnight_med_s']}s dur~{r['window_dur_med_s']}s")

    out = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "encounter_id": 3183, "encounter_name": "한밤의 도래(L'ura)",
            "difficulty": "Mythic(5)",
            "question": "P3 Midnight Falls 에 보스 받는피해증가(취약) 창이 고정 타이밍으로 존재하는가?",
            "method": [
                "top kill 5판(서로 다른 report), lura_top_aug_mining.json fights[] 순서 상위",
                "events(Debuffs/Buffs, hostilityType:Enemies) 전체 → targetID==보스 필터",
                "(gid,source)별 apply~remove 창 → gid 합집합, apply 없는 remove 는 orphan 으로 버림",
                "L'ura 동명 NPC 2개(240391 본체 / 257959) — 둘 다 추적",
                "DamageDone table 15s x12 (300~480s): 전체/보스/보스2 세 시리즈",
                "집단 디버프 소거(0.5s 내 10종+ remove) = 면역·전환 추정 시각",
                "버프 대조: 1판 Buffs table [340,400] vs [260,320]",
            ],
            "vuln_keywords": VULN_KEYWORDS,
            "errors": errors,
        },
        "summary": summary,
        "player_buff_check": buff_check,
        "fights": [{k: v for k, v in f.items() if not k.startswith("_")}
                   for f in fights],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT}")
    rate1 = cli.points_left()
    if rate0 and rate1:
        print(f"pts used: {rate1['pointsSpentThisHour'] - rate0['pointsSpentThisHour']:.1f}")


if __name__ == "__main__":
    main()
