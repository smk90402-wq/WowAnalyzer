"""우리 공대 2026-07-19 르우라(3183 신화) 세션 — 코칭 대상 2인 심층 마이닝.

대상: 하늘연달스물엿새(증강 기원사) + 이디*(부정 죽음의 기사, masterData에서 확정)
리포트: CPA42mqBHXMyca86 (27풀, 최고 37.42%)

산출: data/lura_own_pair_mining.json
사용: python tmp_mine_lura_own_pair.py explore   → actors/캐스트 테이블 관측 (ID 확정)
      python tmp_mine_lura_own_pair.py           → 본 분석
      python tmp_mine_lura_own_pair.py refresh   → API 캐시 무시하고 재조회

포인트 절약: 쿼리 결과를 스크래치패드에 캐시. 리포트 쿼리 사이 sleep(0.3).
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from wcl_v2 import WCLV2, WCLV2Error

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\66e6c09f-1b73-4a06-9a39-f108d6bcda2a\scratchpad")
SCRATCH.mkdir(parents=True, exist_ok=True)

REPORT_CODE = "CPA42mqBHXMyca86"
ENCOUNTER_ID = 3183
DIFFICULTY = 5
AUG_NAME = "하늘연달스물엿새"
DK_PREFIX = "이디"
CRYSTAL_AURA = 1253031  # '일렁이는 빛' — 여명의 수정 운반 self-debuff (이름 검증함)
KST = timezone(timedelta(hours=9))
OUT_JSON = DATA / "lura_own_pair_mining.json"

REFRESH = "refresh" in sys.argv
EXPLORE = "explore" in sys.argv

# ── 추적 스펠 분류 규칙 (이름은 masterData/Casts 테이블에서 발견 — ID 하드코딩 금지)
# ※ 이 리포트는 영어 이름으로 반환됨 (explore로 확인). 한국어 앵커 대응:
#    영겁의 숨결=Breath of Eons, 화염 숨결=Fire Breath, 대격변=Upheaval,
#    예지=Prescience, 시간 건너뛰기=Time Skip, 일렁이는 빛=Glimmering(1253031)
AUG_MAJOR_KEYS = ["Breath of Eons", "Fire Breath", "Upheaval", "Prescience", "Time Skip"]
UDK_MAJOR_KEYS = ["Army of the Dead", "Dark Transformation", "Apocalypse",
                  "Gargoyle", "Abomination"]  # 뒤 3개는 이 로그에 없음 (explore 확인)
DEF_KEYS = ["Obsidian Scales", "Renewing Blaze", "Zephyr", "Time Dilation",
            "Anti-Magic", "Icebound", "Death Pact", "Lichborne", "Vampiric Blood"]
CONSUM_KEYS = ["Potion", "Healthstone", "Light's Potential"]
MECH_KEYS = ["Dawn Crystal"]  # 수정 투입(운반 종료) 액션 — 창 끝과 일치 (fight25 검증)
UTILITY_EXCLUDE = {"Hover", "Glide", "Rescue", "Quell", "Wing Buffet",
                   "Blessing of the Bronze", "Activate Weyrnstone", "Expunge",
                   "Verdant Embrace", "Azure Strike", "Mind Freeze", "Death Grip",
                   "Raise Ally", "Graveyard", "Death Strike", "Spatial Paradox",
                   "Tip the Scales", "Death Charge", "Outbreak",
                   "Charge!"}  # Charge!(1259633)는 죽음의 군대와 65/66회 2s내 동시 → 자동 연동 캐스트
MELEE_NAMES = {"근접 공격", "Melee", "자동 공격"}
CORE_TOP_N = 6          # 세션 캐스트수 상위 N개 = 핵심 딜사이클 스펠 (CPM 대상)
CPM_MIN_DUR_S = 90      # CPM 집계에 넣는 최소 풀 길이
TOP_REPORTS_N = 5       # 숨결 쿨 실측용 상위 증강 로그 수

cli = WCLV2()
_last_q = [0.0]


def q(name: str, gql: str, variables: dict | None = None) -> dict:
    """캐시 우선 쿼리. 캐시 파일: scratchpad/ownpair_{name}.json"""
    cache = SCRATCH / f"ownpair_{name}.json"
    if cache.exists() and not REFRESH:
        return json.loads(cache.read_text(encoding="utf-8"))
    wait = 0.3 - (time.time() - _last_q[0])
    if wait > 0:
        time.sleep(wait)
    data = cli.query(gql, variables)
    _last_q[0] = time.time()
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def mmss(t: float) -> str:
    sign = "-" if t < 0 else ""
    t = abs(t)
    return f"{sign}{int(t) // 60}:{int(t) % 60:02d}"


def med(vals, nd=1):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), nd) if vals else None


# ═══ 1. 리포트 골격: fights + phaseTransitions + masterData ═══════════════
Q_MAIN = """
query($code: String!) {
  reportData { report(code: $code) {
    title startTime endTime
    fights(killType: Encounters) {
      id startTime endTime encounterID difficulty kill name
      bossPercentage lastPhase
      phaseTransitions { id startTime }
    }
    masterData(translate: true) {
      abilities { gameID name }
      actors(type: "Player") { id name subType }
    }
  } }
}
"""

main_data = q("main", Q_MAIN, {"code": REPORT_CODE})["reportData"]["report"]
report_start_ms = float(main_data["startTime"])
fights = sorted(
    (f for f in main_data.get("fights") or []
     if f.get("encounterID") == ENCOUNTER_ID and f.get("difficulty") == DIFFICULTY),
    key=lambda f: f["startTime"],
)
if not fights:
    raise SystemExit("no L'ura fights")
S_ALL = float(fights[0]["startTime"])
E_ALL = float(fights[-1]["endTime"])

master = main_data["masterData"]
ability_names = {int(a["gameID"]): a["name"] for a in master["abilities"]
                 if a.get("gameID") is not None and a.get("name")}
actors = master["actors"]

aug = next((a for a in actors if a["name"] == AUG_NAME), None)
dks = [a for a in actors if str(a["name"]).startswith(DK_PREFIX)
       and a.get("subType") == "DeathKnight"]
if aug is None or not dks:
    print("actors:", [(a["id"], a["name"], a.get("subType")) for a in actors])
    raise SystemExit(f"player not found: aug={aug} dk_candidates={dks}")
if len(dks) > 1:
    print(f"[주의] '{DK_PREFIX}' DK 후보 {len(dks)}명: {[d['name'] for d in dks]} → 첫 번째 사용")
dk = dks[0]
AUG_ID, DK_ID = int(aug["id"]), int(dk["id"])
print(f"players: aug={AUG_NAME}(#{AUG_ID})  udk={dk['name']}(#{DK_ID})")
print(f"fights: {len(fights)}  (id {fights[0]['id']}..{fights[-1]['id']})  "
      f"crystal aura {CRYSTAL_AURA} = {ability_names.get(CRYSTAL_AURA)!r}")

# ═══ 2. 페이즈 이름 (있으면) ═══════════════════════════════════════════════
phase_names: dict[int, dict] = {}
try:
    ph = q("phases", """
query($code: String!) { reportData { report(code: $code) {
  phases { encounterID separatesWipes phases { id name isIntermission } }
} } }""", {"code": REPORT_CODE})["reportData"]["report"].get("phases") or []
    for enc in ph:
        if enc.get("encounterID") == ENCOUNTER_ID:
            for p in enc.get("phases") or []:
                phase_names[int(p["id"])] = {
                    "name": p.get("name") or f"P{p['id']}",
                    "intermission": bool(p.get("isIntermission")),
                }
except WCLV2Error as e:
    print(f"[phases 스키마 미지원 → P{{id}} 폴백] {str(e)[:120]}")
print("phase names:", phase_names)

# ═══ 3. 캐스트 테이블 (세션 전체 창) — 스펠 ID 발견 ═════════════════════════
Q_TABLES = f"""
query($code: String!) {{ reportData {{ report(code: $code) {{
  aug: table(dataType: Casts, startTime: {S_ALL:.1f}, endTime: {E_ALL:.1f}, sourceID: {AUG_ID})
  udk: table(dataType: Casts, startTime: {S_ALL:.1f}, endTime: {E_ALL:.1f}, sourceID: {DK_ID})
}} }} }}
"""
tables = q("tables", Q_TABLES, {"code": REPORT_CODE})["reportData"]["report"]


def table_entries(t):
    d = (t or {}).get("data") or {}
    return d.get("entries") or []


def classify(entries, major_keys):
    """캐스트 테이블 → {구분: {gameID: name}}. 세션 총 캐스트수 포함."""
    cat = {"major": {}, "defensive": {}, "consumable": {}, "mech": {}, "core": {}}
    counts = {}
    ranked = []
    for e in entries:
        gid = e.get("guid")
        name = e.get("name") or ""
        total = int(e.get("total") or 0)
        if gid is None or name in MELEE_NAMES or total == 0:
            continue
        gid = int(gid)
        counts[gid] = total
        if any(k in name for k in major_keys):
            cat["major"][gid] = name
        elif any(k in name for k in DEF_KEYS):
            cat["defensive"][gid] = name
        elif any(k in name for k in CONSUM_KEYS):
            cat["consumable"][gid] = name
        elif any(k in name for k in MECH_KEYS):
            cat["mech"][gid] = name
        elif name not in UTILITY_EXCLUDE:
            ranked.append((total, gid, name))
    for total, gid, name in sorted(ranked, reverse=True)[:CORE_TOP_N]:
        cat["core"][gid] = name
    return cat, counts


aug_cat, aug_counts = classify(table_entries(tables["aug"]), AUG_MAJOR_KEYS)
udk_cat, udk_counts = classify(table_entries(tables["udk"]), UDK_MAJOR_KEYS)

if EXPLORE:
    for tag, entries, cat in (("AUG", table_entries(tables["aug"]), aug_cat),
                              ("UDK", table_entries(tables["udk"]), udk_cat)):
        print(f"\n== {tag} 캐스트 테이블 (세션 전체) ==")
        for e in sorted(entries, key=lambda x: -int(x.get("total") or 0)):
            print(f"  {e.get('guid'):>8}  {e.get('name'):<24} {e.get('total'):>5}")
        print(f"  분류: {json.dumps({k: v for k, v in cat.items()}, ensure_ascii=False)}")
    sys.exit(0)

for tag, cat in (("AUG", aug_cat), ("UDK", udk_cat)):
    print(f"{tag} major={list(cat['major'].values())} def={list(cat['defensive'].values())} "
          f"consum={list(cat['consumable'].values())} mech={list(cat['mech'].values())} "
          f"core={list(cat['core'].values())}")


# ═══ 4. 추적 스펠 이벤트 (플레이어별 aliased abilityID 쿼리) ═══════════════
def tracked_ids(cat):
    ids = {}
    for group in cat.values():
        ids.update(group)
    return ids


def fetch_casts(pname: str, source_id: int, ids: dict[int, str]) -> dict[int, list]:
    fields = []
    for gid in sorted(ids):
        fields.append(
            f"a{gid}: events(dataType: Casts, startTime: {S_ALL:.1f}, endTime: {E_ALL:.1f}, "
            f"abilityID: {gid}, sourceID: {source_id}, limit: 10000) {{ data nextPageTimestamp }}"
        )
    gql = ("query($code: String!) { reportData { report(code: $code) { "
           + " ".join(fields) + " } } }")
    res = q(f"casts_{pname}", gql, {"code": REPORT_CODE})["reportData"]["report"]
    out = {}
    for gid in ids:
        blob = res.get(f"a{gid}") or {}
        if blob.get("nextPageTimestamp"):
            raise RuntimeError(f"{pname} ability {gid} paginated — limit 초과")
        out[gid] = blob.get("data") or []
    return out


aug_events = fetch_casts("aug", AUG_ID, tracked_ids(aug_cat))
udk_events = fetch_casts("udk", DK_ID, tracked_ids(udk_cat))

# 이벤트 type 관측 (empower 스펠은 cast 대신 begincast/empowerend 일 수 있음)
type_obs = Counter()
for gid, evs in list(aug_events.items()) + list(udk_events.items()):
    for e in evs:
        type_obs[(ability_names.get(gid, gid), e.get("type"))] += 1
print("event types:", dict(sorted(type_obs.items(), key=lambda x: -x[1])[:20]))


def cast_times(evs):
    """'cast' 우선, 없으면 empowerend, 그래도 없으면 begincast."""
    for want in ("cast", "empowerend", "begincast"):
        ts = [e for e in evs if e.get("type") == want]
        if ts:
            return ts
    return []


# ═══ 5. 죽음 + 수정 운반 디버프 (한 쿼리) ═════════════════════════════════
Q_DEATH_CRYSTAL = f"""
query($code: String!) {{ reportData {{ report(code: $code) {{
  deaths: events(dataType: Deaths, hostilityType: Friendlies,
                 startTime: {S_ALL:.1f}, endTime: {E_ALL:.1f}, limit: 5000)
    {{ data nextPageTimestamp }}
  crystal: events(dataType: Debuffs, abilityID: {CRYSTAL_AURA},
                  hostilityType: Friendlies,
                  startTime: {S_ALL:.1f}, endTime: {E_ALL:.1f}, limit: 10000)
    {{ data nextPageTimestamp }}
}} }} }}
"""
dc = q("death_crystal", Q_DEATH_CRYSTAL, {"code": REPORT_CODE})["reportData"]["report"]
for k in ("deaths", "crystal"):
    if (dc.get(k) or {}).get("nextPageTimestamp"):
        raise RuntimeError(f"{k} paginated")
death_events = (dc.get("deaths") or {}).get("data") or []
crystal_events = (dc.get("crystal") or {}).get("data") or []
print(f"deaths(all players)={len(death_events)}  crystal debuff events={len(crystal_events)}")

# ═══ 6. 상위 증강 로그에서 영겁의 숨결 실효쿨 실측 ═════════════════════════
BREATH_NAME = "Breath of Eons"  # = 영겁의 숨결
breath_ids = [gid for gid, nm in aug_cat["major"].items() if nm == BREATH_NAME]
if not breath_ids:
    raise SystemExit("Breath of Eons gameID 미발견 — explore로 확인 필요")
BREATH_ID = breath_ids[0]

rank_data = q("rankings", """
query($id: Int!) { worldData { encounter(id: $id) {
  characterRankings(metric: dps, difficulty: 5,
                    className: "Evoker", specName: "Augmentation", page: 1)
} } }""", {"id": ENCOUNTER_ID})
rankings = ((rank_data.get("worldData") or {}).get("encounter") or {}) \
    .get("characterRankings", {}).get("rankings") or []
top_refs, seen_codes = [], set()
for r in rankings:
    rep = r.get("report") or {}
    code, fid = rep.get("code"), rep.get("fightID")
    if not code or code in seen_codes:
        continue
    seen_codes.add(code)
    top_refs.append({"code": code, "fight": int(fid), "char": r.get("name"),
                     "amount": r.get("amount"), "rank_pos": len(top_refs) + 1})
    if len(top_refs) >= TOP_REPORTS_N:
        break
print(f"top aug refs: {[(t['code'], t['fight'], t['char']) for t in top_refs]}")

fields = []
for i, t in enumerate(top_refs):
    fields.append(f'r{i}: report(code: "{t["code"]}") {{ '
                  f'fights(fightIDs: [{t["fight"]}]) {{ id startTime endTime kill }} }}')
top_fights = q("top_fights", "query { reportData { " + " ".join(fields) + " } }")["reportData"]

fields = []
for i, t in enumerate(top_refs):
    fs = (top_fights.get(f"r{i}") or {}).get("fights") or []
    if not fs:
        continue
    f0 = fs[0]
    t["t0"], t["t1"], t["kill"] = float(f0["startTime"]), float(f0["endTime"]), bool(f0["kill"])
    fields.append(
        f'r{i}: report(code: "{t["code"]}") {{ '
        f'events(dataType: Casts, abilityID: {BREATH_ID}, hostilityType: Friendlies, '
        f'startTime: {t["t0"]:.1f}, endTime: {t["t1"]:.1f}, limit: 2000) {{ data }} }}'
    )
top_breath = q("top_breath", "query { reportData { " + " ".join(fields) + " } }")["reportData"]

ref_gaps, ref_firsts, ref_counts = [], [], []
ref_gaps_by_idx = defaultdict(list)   # 1-based 간격 인덱스 → [gap,...]
for i, t in enumerate(top_refs):
    if "t0" not in t:
        continue
    evs = ((top_breath.get(f"r{i}") or {}).get("events") or {}).get("data") or []
    by_src = defaultdict(list)
    for e in evs:
        if e.get("type") == "cast":
            by_src[e.get("sourceID")].append((float(e["timestamp"]) - t["t0"]) / 1000)
    t["breath_by_source"] = {str(k): [round(x, 1) for x in sorted(v)]
                             for k, v in by_src.items()}
    for src, ts in by_src.items():
        ts = sorted(ts)
        ref_firsts.append(ts[0])
        ref_counts.append(len(ts) / ((t["t1"] - t["t0"]) / 60000))
        for j in range(len(ts) - 1):
            g = ts[j + 1] - ts[j]
            ref_gaps.append(g)
            ref_gaps_by_idx[j + 1].append(g)

ref_gaps.sort()
if not ref_gaps:
    raise SystemExit("top log 숨결 간격 0건 — abilityID 재확인 필요")
# 상위로그 간격은 인덱스 구조: gap1~73s, gap2~79s(시간 건너뛰기 반영), gap3~118s(민쿨)…
REF_GAP_MED = {i: round(statistics.median(v), 1) for i, v in sorted(ref_gaps_by_idx.items())}
REF_GAP_ALL_MED = med(ref_gaps)
MIN_READY_GAP = round(ref_gaps[0], 1)     # 이보다 짧은 간격은 물리적으로 불가로 간주
DELAY_VS_TOP_S = 15.0                     # 같은 인덱스 상위로그 med + 15s 초과 → 지연
breath_ref = {
    "ability_id": BREATH_ID,
    "n_top_reports": sum(1 for t in top_refs if "t0" in t),
    "all_kills": all(t.get("kill") for t in top_refs if "t0" in t),
    "n_gaps": len(ref_gaps),
    "gap_min_s": MIN_READY_GAP,
    "gap_med_s": REF_GAP_ALL_MED,
    "gap_med_by_index": REF_GAP_MED,
    "raw_cd_estimate_s": REF_GAP_MED.get(3),  # 시간 건너뛰기 미적용 구간(3번째 간격)이 민쿨 근사
    "first_cast_med_s": med(ref_firsts),
    "casts_per_min_med": med(ref_counts, 2),
    "note": ("영겁의 숨결 기본쿨 ~120s. 시간 건너뛰기(개전 ~10s, ~150s)로 gap1/2가 "
             "~73/79s로 압축되는 케이던스가 상위로그 공통 패턴. 지연 판정은 같은 "
             "인덱스의 상위로그 중앙값 대비 +15s 초과."),
    "sources": [{k: t.get(k) for k in
                 ("code", "fight", "char", "kill", "breath_by_source")} for t in top_refs],
}
print(f"숨결 케이던스(상위로그): 인덱스별 med {REF_GAP_MED} · min={MIN_READY_GAP}s "
      f"전체med={REF_GAP_ALL_MED}s (간격 {len(ref_gaps)}건/{breath_ref['n_top_reports']}로그)")

# ═══ 7. 풀별 분석 ═════════════════════════════════════════════════════════
by_fight_death = defaultdict(list)
for e in death_events:
    by_fight_death[e.get("fight")].append(e)
by_fight_crystal = defaultdict(list)
for e in crystal_events:
    by_fight_crystal[e.get("fight")].append(e)


def phase_label(pid):
    meta = phase_names.get(pid)
    if not meta:
        return f"P{pid}"
    nm = meta["name"]
    return nm if nm else f"P{pid}"


def build_phase_track(fight):
    t0 = float(fight["startTime"])
    trans = sorted(fight.get("phaseTransitions") or [], key=lambda x: x["startTime"])
    return [(round((float(tr["startTime"]) - t0) / 1000, 1), int(tr["id"])) for tr in trans]


def phase_at(track, t):
    cur = track[0][1] if track else 1
    for ts, pid in track:
        if t >= ts - 0.05:
            cur = pid
        else:
            break
    return phase_label(cur)


def player_pull(fight, events_by_gid, cat, pid_actor):
    t0, t1 = float(fight["startTime"]), float(fight["endTime"])
    dur = (t1 - t0) / 1000
    fid = fight["id"]
    track = build_phase_track(fight)

    def rel_casts(gid):
        evs = [e for e in events_by_gid.get(gid, []) if e.get("fight") == fid]
        return sorted(round((float(e["timestamp"]) - t0) / 1000, 1)
                      for e in cast_times(evs))

    out = {"majors": {}, "defensives": {}, "consumables": {}, "mech": {}, "cpm": {}}
    for gid, nm in cat["major"].items():
        ts = rel_casts(gid)
        if ts:
            out["majors"][nm] = [{"t": t, "mmss": mmss(t), "phase": phase_at(track, t)}
                                 for t in ts]
    for slot, key in (("defensives", "defensive"), ("consumables", "consumable"),
                      ("mech", "mech")):
        for gid, nm in cat[key].items():
            ts = rel_casts(gid)
            if ts:
                out[slot][nm] = [{"t": t, "phase": phase_at(track, t)} for t in ts]
    for gid, nm in cat["core"].items():
        n = len(rel_casts(gid))
        if dur >= 1:
            out["cpm"][nm] = round(n / (dur / 60), 2)
    deaths = []
    for e in by_fight_death[fid]:
        if int(e.get("targetID") or 0) != pid_actor:
            continue
        t = round((float(e["timestamp"]) - t0) / 1000, 1)
        kid = int(e.get("killingAbilityGameID") or 0)
        deaths.append({"t": t, "mmss": mmss(t), "phase": phase_at(track, t),
                       "cause": ability_names.get(kid, str(kid))})
    out["deaths"] = deaths
    return out


def crystal_windows(fight, target_id):
    """운반 창: applydebuff→removedebuff. 미종결은 풀 끝으로 닫음."""
    t0, t1 = float(fight["startTime"]), float(fight["endTime"])
    fid = fight["id"]
    evs = sorted((e for e in by_fight_crystal[fid]
                  if int(e.get("targetID") or 0) == target_id),
                 key=lambda e: e["timestamp"])
    wins, start = [], None
    for e in evs:
        t = round((float(e["timestamp"]) - t0) / 1000, 1)
        ty = e.get("type")
        if ty in ("applydebuff", "refreshdebuff"):
            if start is None:
                start = t
        elif ty == "removedebuff" and start is not None:
            wins.append([start, t])
            start = None
    if start is not None:
        wins.append([start, round((t1 - t0) / 1000, 1)])
    return wins


def breath_analysis(fight, breaths, wins):
    """숨결 캐스트↔운반 창 정렬 + 지연 판정.

    지연 판정: 같은 인덱스의 상위로그 간격 med + 15s 초과.
    지연 캐스트에 대해 '준비창'([이전+ref_med, 실제 캐스트])이 운반 창과 겹치면
    운반 탓 지연으로 귀속. 마지막 캐스트 후 풀이 ref+15s 이상 이어졌으면 말미 스킵.
    """
    dur = (float(fight["endTime"]) - float(fight["startTime"])) / 1000
    track = build_phase_track(fight)

    def carry_overlap(lo, hi):
        return round(sum(max(0.0, min(w[1], hi) - max(w[0], lo)) for w in wins), 1)

    casts, delay_windows = [], []
    for i, b in enumerate(breaths):
        during = next((w for w in wins if w[0] <= b <= w[1]), None)
        gap = round(b - breaths[i - 1], 1) if i else None
        ref = REF_GAP_MED.get(i, REF_GAP_ALL_MED) if i else None
        delta = round(gap - ref, 1) if gap is not None else None
        delayed = bool(delta is not None and delta > DELAY_VS_TOP_S)
        row = {
            "t": b, "mmss": mmss(b), "phase": phase_at(track, b),
            "during_carry": during is not None,
            "carry_rel_s": round(b - during[0], 1) if during else None,
            "gap_since_prev_s": gap,
            "ref_gap_top_med_s": ref,
            "delta_vs_top_s": delta,
            "delayed": delayed,
        }
        if delayed:
            ready = breaths[i - 1] + ref
            ol = carry_overlap(ready, b)
            row["ready_window"] = [round(ready, 1), b]
            row["delay_carry_overlap_s"] = ol
            row["delayed_during_carry"] = ol >= 3
            delay_windows.append((ready, b))
        casts.append(row)
    # 말미 스킵: 마지막 캐스트 + (다음 인덱스 ref) + 15s < 풀 종료
    tail = None
    if breaths:
        nxt_ref = REF_GAP_MED.get(len(breaths), REF_GAP_ALL_MED)
        expected_next = breaths[-1] + nxt_ref
        if dur > expected_next + DELAY_VS_TOP_S:
            tail = {"last_cast_s": breaths[-1], "expected_next_s": round(expected_next, 1),
                    "pull_end_s": round(dur, 1),
                    "missed_by_s": round(dur - expected_next, 1),
                    "carry_overlap_s": carry_overlap(expected_next, dur)}
    carries = []
    for w in wins:
        cast_in = [b for b in breaths if w[0] <= b <= w[1]]
        held_ol = round(sum(max(0.0, min(b_, w[1]) - max(a_, w[0]))
                            for a_, b_ in delay_windows), 1)
        carries.append({
            "window": w, "dur_s": round(w[1] - w[0], 1),
            "phase": phase_at(track, w[0]),
            "breath_cast_in_window": [round(b, 1) for b in cast_in],
            "delay_overlap_s": held_ol,
            "held_while_carrying": held_ol >= 3,
        })
    return casts, carries, tail


pulls = []
for pull_no, fight in enumerate(fights, 1):
    fid = fight["id"]
    t0, t1 = float(fight["startTime"]), float(fight["endTime"])
    dur = round((t1 - t0) / 1000, 1)
    track = build_phase_track(fight)
    aug_p = player_pull(fight, aug_events, aug_cat, AUG_ID)
    udk_p = player_pull(fight, udk_events, udk_cat, DK_ID)
    wins = crystal_windows(fight, AUG_ID)
    breaths = [c["t"] for c in aug_p["majors"].get(BREATH_NAME, [])]
    bcasts, carries, tail = breath_analysis(fight, breaths, wins)
    holders = len({int(e.get("targetID") or 0) for e in by_fight_crystal[fid]
                   if e.get("type") == "applydebuff"})
    max_pid = max((pid for _, pid in track), default=1)
    pulls.append({
        "pull": pull_no, "fight_id": fid,
        "start_kst": datetime.fromtimestamp((report_start_ms + t0) / 1000, KST)
        .isoformat(timespec="seconds"),
        "duration_s": dur, "duration_mmss": mmss(dur),
        "boss_remaining_pct": round(float(fight.get("bossPercentage") or 0), 2),
        "last_phase": int(fight.get("lastPhase") or 0),
        "max_phase_id": max_pid,
        "kill": bool(fight.get("kill")),
        "phases": [{"t": ts, "mmss": mmss(ts), "phase": phase_label(pid)}
                   for ts, pid in track],
        "reached_p3": max_pid >= 4,  # id4 = Stage Three: Midnight Falls
        "wcl_url": f"https://ko.warcraftlogs.com/reports/{REPORT_CODE}#fight={fid}",
        "aug": {**aug_p, "crystal_carry_windows": [
            {"start": w[0], "end": w[1], "dur_s": round(w[1] - w[0], 1)} for w in wins],
            "breath_casts": bcasts, "carry_breath_check": carries,
            "breath_tail_skip": tail},
        "udk": udk_p,
        "raid_crystal_holders": holders,
    })

# ═══ 8. 세션 집계 ═════════════════════════════════════════════════════════
def aggregate(pkey: str, cat: dict) -> dict:
    firsts = defaultdict(list)
    per_pull_n = defaultdict(list)
    cpm_acc = defaultdict(list)
    def_uses = Counter()
    consum_uses = Counter()
    mech_uses = Counter()
    def_n, deaths = [], []
    for p in pulls:
        d = p[pkey]
        for nm, casts in d["majors"].items():
            firsts[nm].append(casts[0]["t"])
            per_pull_n[nm].append(len(casts))
        for nm in cat["major"].values():
            if nm not in d["majors"]:
                per_pull_n[nm].append(0)
        def_n.append(sum(len(v) for v in d["defensives"].values()))
        for nm, v in d["defensives"].items():
            def_uses[nm] += len(v)
        for nm, v in d["consumables"].items():
            consum_uses[nm] += len(v)
        for nm, v in d["mech"].items():
            mech_uses[nm] += len(v)
        deaths.extend(d["deaths"])
        if p["duration_s"] >= CPM_MIN_DUR_S:
            for nm, v in d["cpm"].items():
                cpm_acc[nm].append(v)
    return {
        "pulls": len(pulls),
        "first_cast_med_s": {nm: med(v) for nm, v in firsts.items()},
        "casts_per_pull_med": {nm: med(v) for nm, v in per_pull_n.items()},
        "casts_per_pull_total": {nm: sum(v) for nm, v in per_pull_n.items()},
        "core_cpm_med": {nm: med(v, 2) for nm, v in cpm_acc.items()},
        "core_cpm_pulls_used": (f">={CPM_MIN_DUR_S}s "
                                f"({sum(1 for p in pulls if p['duration_s'] >= CPM_MIN_DUR_S)}풀)"),
        "defensive_casts_per_pull_med": med(def_n),
        "defensive_uses_total": dict(def_uses.most_common()),
        "consumable_uses_total": dict(consum_uses.most_common()),
        "mech_uses_total": dict(mech_uses.most_common()),
        "deaths_total": len(deaths),
        "death_causes": dict(Counter(d["cause"] for d in deaths).most_common()),
        "death_phases": dict(Counter(d["phase"] for d in deaths).most_common()),
    }


aug_agg = aggregate("aug", aug_cat)
udk_agg = aggregate("udk", udk_cat)

# 숨결×운반 세션 요약
all_carries = [c for p in pulls for c in p["aug"]["carry_breath_check"]]
all_bcasts = [b for p in pulls for b in p["aug"]["breath_casts"]]
dur_by_phase = defaultdict(list)
for c in all_carries:
    dur_by_phase[c["phase"]].append(c["dur_s"])
delayed = [b for b in all_bcasts if b["delayed"]]
carry_summary = {
    "carry_windows_total": len(all_carries),
    "carry_dur_med_s": med([c["dur_s"] for c in all_carries]),
    "carry_dur_med_by_phase": {ph: {"n": len(v), "med_s": med(v)}
                               for ph, v in sorted(dur_by_phase.items())},
    "pulls_with_carry": sum(1 for p in pulls if p["aug"]["crystal_carry_windows"]),
    "breath_casts_total": len(all_bcasts),
    "breath_during_carry": sum(1 for b in all_bcasts if b["during_carry"]),
    "breath_delayed_total": len(delayed),
    "breath_delayed_during_carry": sum(1 for b in delayed if b.get("delayed_during_carry")),
    "delay_delta_med_s": med([b["delta_vs_top_s"] for b in delayed]),
    "held_while_carrying_windows": sum(1 for c in all_carries if c["held_while_carrying"]),
    "tail_skips": [
        {"pull": p["pull"], "fight_id": p["fight_id"], **p["aug"]["breath_tail_skip"]}
        for p in pulls if p["aug"]["breath_tail_skip"]],
    "delayed_casts_detail": [
        {"pull": p["pull"], "fight_id": p["fight_id"], **b}
        for p in pulls for b in p["aug"]["breath_casts"] if b["delayed"]],
}

best = next(p for p in pulls if p["fight_id"] == 25)

out = {
    "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
    "report": {"code": REPORT_CODE, "title": main_data.get("title"),
               "url": f"https://ko.warcraftlogs.com/reports/{REPORT_CODE}",
               "encounter_id": ENCOUNTER_ID, "difficulty": DIFFICULTY,
               "pulls": len(pulls), "kills": sum(p["kill"] for p in pulls),
               "note": "우리 공대 트라이 세션 — 전부 wipe (킬 0). 상위로그 기준과 달리 진도 기반."},
    "players": {
        "aug": {"actor_id": AUG_ID, "name": AUG_NAME, "class": aug.get("subType"),
                "spec": "Augmentation"},
        "udk": {"actor_id": DK_ID, "name": dk["name"], "class": dk.get("subType"),
                "spec": "Unholy"},
    },
    "ability_ids": {
        "aug": {str(gid): nm for grp in aug_cat.values() for gid, nm in grp.items()},
        "udk": {str(gid): nm for grp in udk_cat.values() for gid, nm in grp.items()},
        "crystal_carry_aura": {str(CRYSTAL_AURA): ability_names.get(CRYSTAL_AURA)},
    },
    "phase_names": {str(k): v for k, v in phase_names.items()},
    "breath_cd_reference_top_logs": breath_ref,
    "delay_rule": (f"간격 인덱스별 상위로그 med({REF_GAP_MED}) + {DELAY_VS_TOP_S}s 초과 → "
                   f"delayed. 지연 준비창과 운반 창이 3s+ 겹치면 delayed_during_carry."),
    "notes": [
        "리포트가 영어 스펠명으로 반환됨 — 앵커 대응: 영겁의 숨결=Breath of Eons, "
        "화염 숨결=Fire Breath, 대격변=Upheaval, 예지=Prescience, 시간 건너뛰기=Time Skip, "
        "일렁이는 빛=Glimmering(1253031), 여명의 수정=Dawn Crystal(1253050).",
        "UDK 대재앙/가고일/흉물 소환은 이 로그에 0회 — 부정 12.0 빌드에서 미사용/부재. "
        "주기 쿨기는 어둠의 변신(1233448, ~45s)과 죽음의 군대(42650, 실측 간격 ~95s).",
        "Charge!(1259633)는 죽음의 군대 캐스트와 65/66회 2s 이내 동시 발생(med 0.8s) — "
        "자동 연동 캐스트로 판단, 별도 추적 제외.",
        "Dawn Crystal(1253050) 캐스트 시각 = Glimmering 운반 창의 끝(투입 액션). "
        "fight25에서 7/7 일치 손검증.",
        "phaseTransitions id: 1=Stage One, 2=Intermission, 3=Stage Two, "
        "4=Stage Three(Midnight Falls), 5=Stage Four. WCL fight.lastPhase는 "
        "중간 페이즈 번호 체계가 달라 last_phase=3 ↔ max_phase_id=4가 P3 도달.",
    ],
    "session_aggregates": {"aug": aug_agg, "udk": udk_agg,
                           "aug_crystal_carry": carry_summary},
    "best_pull": best,
    "pulls": pulls,
}
DATA.mkdir(exist_ok=True)
OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nwrote {OUT_JSON}")

# ═══ 9. 손검증 출력: 최고 풀(fight 25) ════════════════════════════════════
print(f"\n===== 손검증: 최고 풀 pull{best['pull']} fight25 "
      f"({best['boss_remaining_pct']}%, {best['duration_mmss']}, "
      f"lastPhase={best['last_phase']}) =====")
print("phases:", [(p['mmss'], p['phase']) for p in best['phases']])
for pkey, label in (("aug", AUG_NAME), ("udk", dk["name"])):
    d = best[pkey]
    print(f"\n[{label}]")
    for nm, casts in d["majors"].items():
        print(f"  {nm}: {[(c['mmss'], c['phase']) for c in casts]}")
    for nm, casts in d["defensives"].items():
        print(f"  (생존기) {nm}: {[c['t'] for c in casts]}")
    for nm, casts in d["consumables"].items():
        print(f"  (소모품) {nm}: {[c['t'] for c in casts]}")
    for nm, casts in d["mech"].items():
        print(f"  (기믹) {nm}: {[c['t'] for c in casts]}")
    print(f"  CPM: {d['cpm']}")
    print(f"  죽음: {d['deaths']}")
print(f"\n수정 운반(aug): {best['aug']['crystal_carry_windows']}")
for c in best["aug"]["carry_breath_check"]:
    print(f"  창 {c['window']} {c['phase']}: 창내 숨결 {c['breath_cast_in_window']} "
          f"지연겹침 {c['delay_overlap_s']}s 홀드={c['held_while_carrying']}")
print(f"숨결 캐스트 상세: {[(b['mmss'], b['gap_since_prev_s'], b['ref_gap_top_med_s'], b['delayed']) for b in best['aug']['breath_casts']]}")
print(f"말미 스킵: {best['aug']['breath_tail_skip']}")

print("\n===== 세션 요약 =====")
print(f"AUG 숨결/풀 med={aug_agg['casts_per_pull_med'].get(BREATH_NAME)} "
      f"첫숨결 med={aug_agg['first_cast_med_s'].get(BREATH_NAME)}s "
      f"지연 {carry_summary['breath_delayed_total']}회 / 총 {carry_summary['breath_casts_total']}캐스트")
print(f"AUG 운반: {carry_summary['carry_windows_total']}창 "
      f"({carry_summary['pulls_with_carry']}풀), med {carry_summary['carry_dur_med_s']}s, "
      f"페이즈별 {carry_summary['carry_dur_med_by_phase']}")
print(f"AUG 운반중 숨결 {carry_summary['breath_during_carry']}회 / "
      f"지연 중 운반귀속 {carry_summary['breath_delayed_during_carry']}회 / "
      f"운반중 홀드 {carry_summary['held_while_carrying_windows']}창 / "
      f"말미스킵 {len(carry_summary['tail_skips'])}풀")
print(f"AUG deaths={aug_agg['deaths_total']} {aug_agg['death_causes']}")
print(f"UDK deaths={udk_agg['deaths_total']} {udk_agg['death_causes']}")
print(f"UDK majors/풀 med: {udk_agg['casts_per_pull_med']}")
print(f"UDK core CPM med: {udk_agg['core_cpm_med']}")
