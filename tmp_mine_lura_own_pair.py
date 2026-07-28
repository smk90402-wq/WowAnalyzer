"""우리 공대 신화 르우라(3183) 전체 트라이 — 코칭 대상 2인 심층 마이닝 (멀티 리포트).

대상: 하늘연달스물엿새(증강 기원사) + 이디*(부정 죽음의 기사, masterData에서 확정)
리포트: WCL userID 2897558('이해뜸') 의 최근 리포트 25개 중 신화 르우라 풀이 있는 것
        전부(최신 MAX_REPORTS개까지) 자동 발견 — 새 공대 날짜가 올라오면 재실행만 하면
        자동 반영 (RefreshLuraPair.bat 더블클릭).

산출: data/lura_own_pair_mining.json
      칠흑의 힘(395296) 유지율 채굴 포함 — tmp_mine_lura_own_em.py 별도 실행 불필요.
사용: python tmp_mine_lura_own_pair.py explore   → 병합 캐스트 테이블 관측 (ID 확정)
      python tmp_mine_lura_own_pair.py           → 본 분석
      python tmp_mine_lura_own_pair.py refresh   → API 캐시 무시하고 재조회

포인트 절약: 리포트×쿼리 단위 캐시(리포트의 르우라 풀 수가 늘면 키가 바뀌어 자동 무효화).
쿼리 사이 sleep(0.3). 상위로그 숨결 레퍼런스는 기존 산출 JSON 값을 재사용(재채굴 안 함).
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

USER_ID = 2897558       # WCL 계정 '이해뜸' — 우리 공대 로그 업로더
MAX_REPORTS = 10        # 최신 N개 르우라 리포트까지
ENCOUNTER_ID = 3183
DIFFICULTY = 5
AUG_NAME = "하늘연달스물엿새"
DK_PREFIX = "이디"
CRYSTAL_AURA = 1253031  # '일렁이는 빛' — 여명의 수정 운반 self-debuff (이름 검증함)
EBON_MIGHT = 395296     # 칠흑의 힘 self-buff (상위권 채굴과 같은 방식으로 uptime 측정)
KST = timezone(timedelta(hours=9))
OUT_JSON = DATA / "lura_own_pair_mining.json"

REFRESH = "refresh" in sys.argv
EXPLORE = "explore" in sys.argv

# ── 추적 스펠 분류 규칙 (이름은 masterData/Casts 테이블에서 발견 — ID 하드코딩 금지)
# ※ 이 계정 리포트들은 영어 이름으로 반환됨 (07-19·07-26·07-13 explore로 확인). 한국어 앵커:
#    영겁의 숨결=Breath of Eons, 화염 숨결=Fire Breath, 대격변=Upheaval,
#    예지=Prescience, 시간 건너뛰기=Time Skip, 일렁이는 빛=Glimmering(1253031)
AUG_MAJOR_KEYS = ["Breath of Eons", "Fire Breath", "Upheaval", "Prescience", "Time Skip"]
UDK_MAJOR_KEYS = ["Army of the Dead", "Dark Transformation", "Apocalypse",
                  "Gargoyle", "Abomination"]  # 뒤 3개는 12.0 부정 빌드에 없음 (explore 확인)
DEF_KEYS = ["Obsidian Scales", "Renewing Blaze", "Zephyr", "Time Dilation",
            "Anti-Magic", "Icebound", "Death Pact", "Lichborne", "Vampiric Blood"]
CONSUM_KEYS = ["Potion", "Healthstone", "Light's Potential"]
MECH_KEYS = ["Dawn Crystal"]  # 수정 투입(운반 종료) 액션 — 창 끝과 일치 (07-19 fight25 검증)
UTILITY_EXCLUDE = {"Hover", "Glide", "Rescue", "Quell", "Wing Buffet",
                   "Blessing of the Bronze", "Activate Weyrnstone", "Expunge",
                   "Verdant Embrace", "Azure Strike", "Mind Freeze", "Death Grip",
                   "Raise Ally", "Graveyard", "Death Strike", "Spatial Paradox",
                   "Tip the Scales", "Death Charge", "Outbreak",
                   "Charge!"}  # Charge!(1259633)는 죽음의 군대와 2s내 동시 → 자동 연동 캐스트
MELEE_NAMES = {"근접 공격", "Melee", "자동 공격"}
CORE_TOP_N = 6          # 전체 세션 캐스트수 상위 N개 = 핵심 딜사이클 스펠 (CPM 대상)
CPM_MIN_DUR_S = 90      # CPM·칠흑의 힘 유지율 집계에 넣는 최소 풀 길이
TOP_REPORTS_N = 5       # 숨결 쿨 실측용 상위 증강 로그 수 (레퍼런스 재채굴 폴백 전용)
DELAY_VS_TOP_S = 15.0   # 같은 인덱스 상위로그 med + 15s 초과 → 지연
BREATH_NAME = "Breath of Eons"  # = 영겁의 숨결

cli = WCLV2()
_last_q = [0.0]


def q(name: str, gql: str, variables: dict | None = None, cached: bool = True) -> dict:
    """캐시 우선 쿼리. 캐시 파일: scratchpad/ownpair_{name}.json"""
    cache = SCRATCH / f"ownpair_{name}.json"
    if cached and cache.exists() and not REFRESH:
        return json.loads(cache.read_text(encoding="utf-8"))
    wait = 0.3 - (time.time() - _last_q[0])
    if wait > 0:
        time.sleep(wait)
    data = cli.query(gql, variables)
    _last_q[0] = time.time()
    if cached:
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def mmss(t: float) -> str:
    sign = "-" if t < 0 else ""
    t = abs(t)
    return f"{sign}{int(t) // 60}:{int(t) % 60:02d}"


def med(vals, nd=1):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), nd) if vals else None


# ═══ 1. 리포트 자동 발견: userID 최근 25개 → 신화 르우라 풀 포함만 ═══════════
Q_DISCOVER = """
query($uid: Int!) { reportData { reports(userID: $uid, limit: 25) {
  data { code title startTime
    fights(killType: Encounters) { encounterID difficulty }
  }
} } }
"""
disc = q("discovery", Q_DISCOVER, {"uid": USER_ID}, cached=False)
cands = []
for r in (disc["reportData"]["reports"] or {}).get("data") or []:
    n_lura = sum(1 for f in r.get("fights") or []
                 if f.get("encounterID") == ENCOUNTER_ID and f.get("difficulty") == DIFFICULTY)
    if n_lura:
        cands.append({"code": r["code"], "title": r.get("title"),
                      "start_ms": float(r["startTime"]), "n_lura": n_lura})
cands.sort(key=lambda r: -r["start_ms"])
reps = sorted(cands[:MAX_REPORTS], key=lambda r: r["start_ms"])  # 시간순 처리
if not reps:
    raise SystemExit("userID 리포트 중 신화 르우라 풀이 있는 리포트가 없음")
print(f"리포트 발견: {len(cands)}개 중 최신 {len(reps)}개 사용")
for r in reps:
    dt = datetime.fromtimestamp(r["start_ms"] / 1000, KST)
    print(f"  {r['code']}  {dt:%Y-%m-%d}  {r['title']!r}  르우라 신화 {r['n_lura']}풀")

# ═══ 2. 리포트별 골격: fights + phaseTransitions + masterData (actor ID는 리포트마다 다름) ═══
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
ability_names: dict[int, str] = {}
absence_notes: list[str] = []
for rep in reps:
    rep["key"] = f"{rep['code']}_L{rep['n_lura']}"
    main = q(f"{rep['key']}_main", Q_MAIN, {"code": rep["code"]})["reportData"]["report"]
    rep["title"] = main.get("title") or rep["title"]
    rep["start_ms"] = float(main["startTime"])
    rep["date_kst"] = datetime.fromtimestamp(rep["start_ms"] / 1000, KST).date().isoformat()
    fights = sorted(
        (f for f in main.get("fights") or []
         if f.get("encounterID") == ENCOUNTER_ID and f.get("difficulty") == DIFFICULTY),
        key=lambda f: f["startTime"],
    )
    if not fights:
        raise SystemExit(f"{rep['code']}: 발견 단계와 달리 르우라 fight 없음")
    rep["fights"] = fights
    rep["s_all"] = float(fights[0]["startTime"])
    rep["e_all"] = float(fights[-1]["endTime"])

    master = main["masterData"]
    for a in master["abilities"]:
        if a.get("gameID") is not None and a.get("name"):
            ability_names[int(a["gameID"])] = a["name"]
    actors = master["actors"]
    aug_actor = next((a for a in actors if a["name"] == AUG_NAME), None)
    dks = [a for a in actors if str(a["name"]).startswith(DK_PREFIX)
           and a.get("subType") == "DeathKnight"]
    if len(dks) > 1:
        print(f"[주의] {rep['code']}: '{DK_PREFIX}' DK 후보 {len(dks)}명 "
              f"{[d['name'] for d in dks]} → 첫 번째 사용")
    dk_actor = dks[0] if dks else None
    rep["aug_actor"], rep["dk_actor"] = aug_actor, dk_actor
    rep["aug_id"] = int(aug_actor["id"]) if aug_actor else None
    rep["dk_id"] = int(dk_actor["id"]) if dk_actor else None
    for tag, actor, nm in (("aug", aug_actor, AUG_NAME), ("udk", dk_actor, f"{DK_PREFIX}*")):
        if actor is None:
            note = f"{rep['code']}({rep['date_kst']}): {nm} 로스터에 없음 — 해당 리포트는 이 플레이어 집계에서 제외"
            absence_notes.append(note)
            print(f"[결장] {note}")
    print(f"{rep['code']} {rep['date_kst']}: fights {len(fights)} "
          f"(id {fights[0]['id']}..{fights[-1]['id']})  "
          f"aug=#{rep['aug_id']}  udk=#{rep['dk_id']}")

# ═══ 3. 페이즈 이름 (인카운터 공통 — 한 번만) ═══════════════════════════════
phase_names: dict[int, dict] = {}
try:
    ph = q("phases", """
query($code: String!) { reportData { report(code: $code) {
  phases { encounterID separatesWipes phases { id name isIntermission } }
} } }""", {"code": reps[0]["code"]})["reportData"]["report"].get("phases") or []
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

# ═══ 4. 캐스트 테이블 (리포트별 세션 창) → gameID 기준 병합 후 분류 ═══════════
def table_entries(t):
    d = (t or {}).get("data") or {}
    return d.get("entries") or []


def merge_entries(dst: dict, entries):
    for e in entries:
        gid, name = e.get("guid"), e.get("name") or ""
        total = int(e.get("total") or 0)
        if gid is None or total == 0:
            continue
        gid = int(gid)
        cur = dst.setdefault(gid, {"guid": gid, "name": name, "total": 0})
        cur["total"] += total
        if name:
            cur["name"] = name  # 시간순 처리 → 최신 리포트 이름 우선


aug_merged: dict[int, dict] = {}
udk_merged: dict[int, dict] = {}
for rep in reps:
    fields = []
    if rep["aug_id"] is not None:
        fields.append(f'aug: table(dataType: Casts, startTime: {rep["s_all"]:.1f}, '
                      f'endTime: {rep["e_all"]:.1f}, sourceID: {rep["aug_id"]})')
    if rep["dk_id"] is not None:
        fields.append(f'udk: table(dataType: Casts, startTime: {rep["s_all"]:.1f}, '
                      f'endTime: {rep["e_all"]:.1f}, sourceID: {rep["dk_id"]})')
    if not fields:
        continue
    gql = "query($code: String!) { reportData { report(code: $code) { " + " ".join(fields) + " } } }"
    tables = q(f"{rep['key']}_tables", gql, {"code": rep["code"]})["reportData"]["report"]
    merge_entries(aug_merged, table_entries(tables.get("aug")))
    merge_entries(udk_merged, table_entries(tables.get("udk")))


def classify(entries, major_keys):
    """캐스트 테이블 → {구분: {gameID: name}}. 전체 세션 총 캐스트수 기준."""
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


aug_cat, aug_counts = classify(list(aug_merged.values()), AUG_MAJOR_KEYS)
udk_cat, udk_counts = classify(list(udk_merged.values()), UDK_MAJOR_KEYS)

if EXPLORE:
    for tag, merged, cat in (("AUG", aug_merged, aug_cat), ("UDK", udk_merged, udk_cat)):
        print(f"\n== {tag} 캐스트 테이블 (전체 리포트 병합) ==")
        for e in sorted(merged.values(), key=lambda x: -x["total"]):
            print(f"  {e['guid']:>8}  {e['name']:<24} {e['total']:>5}")
        print(f"  분류: {json.dumps({k: v for k, v in cat.items()}, ensure_ascii=False)}")
    sys.exit(0)

for tag, cat in (("AUG", aug_cat), ("UDK", udk_cat)):
    print(f"{tag} major={list(cat['major'].values())} def={list(cat['defensive'].values())} "
          f"consum={list(cat['consumable'].values())} mech={list(cat['mech'].values())} "
          f"core={list(cat['core'].values())}")

breath_ids = [gid for gid, nm in aug_cat["major"].items() if nm == BREATH_NAME]
if not breath_ids:
    raise SystemExit("Breath of Eons gameID 미발견 — explore로 확인 필요")
BREATH_ID = breath_ids[0]


# ═══ 5. 추적 스펠 이벤트 + 죽음/수정 + 칠흑의 힘 (리포트별) ══════════════════
def tracked_ids(cat):
    ids = {}
    for group in cat.values():
        ids.update(group)
    return ids


def fetch_casts(rep: dict, tag: str, source_id: int, ids: dict[int, str]) -> dict[int, list]:
    fields = []
    for gid in sorted(ids):
        fields.append(
            f"a{gid}: events(dataType: Casts, startTime: {rep['s_all']:.1f}, "
            f"endTime: {rep['e_all']:.1f}, "
            f"abilityID: {gid}, sourceID: {source_id}, limit: 10000) {{ data nextPageTimestamp }}"
        )
    gql = ("query($code: String!) { reportData { report(code: $code) { "
           + " ".join(fields) + " } } }")
    res = q(f"{rep['key']}_casts_{tag}", gql, {"code": rep["code"]})["reportData"]["report"]
    out = {}
    for gid in ids:
        blob = res.get(f"a{gid}") or {}
        if blob.get("nextPageTimestamp"):
            raise RuntimeError(f"{rep['code']} {tag} ability {gid} paginated — limit 초과")
        out[gid] = blob.get("data") or []
    return out


def fetch_death_crystal(rep: dict) -> tuple[list, list]:
    gql = f"""
query($code: String!) {{ reportData {{ report(code: $code) {{
  deaths: events(dataType: Deaths, hostilityType: Friendlies,
                 startTime: {rep['s_all']:.1f}, endTime: {rep['e_all']:.1f}, limit: 5000)
    {{ data nextPageTimestamp }}
  crystal: events(dataType: Debuffs, abilityID: {CRYSTAL_AURA},
                  hostilityType: Friendlies,
                  startTime: {rep['s_all']:.1f}, endTime: {rep['e_all']:.1f}, limit: 10000)
    {{ data nextPageTimestamp }}
}} }} }}
"""
    dc = q(f"{rep['key']}_dc", gql, {"code": rep["code"]})["reportData"]["report"]
    for k in ("deaths", "crystal"):
        if (dc.get(k) or {}).get("nextPageTimestamp"):
            raise RuntimeError(f"{rep['code']} {k} paginated")
    return ((dc.get("deaths") or {}).get("data") or [],
            (dc.get("crystal") or {}).get("data") or [])


def fetch_em(rep: dict) -> dict[int, tuple[float, float]]:
    """fight_id → (uptime_ms, dur_ms). 상위권 채굴과 같은 Buffs table 방식."""
    if rep["aug_id"] is None:
        return {}
    fields = []
    for f in rep["fights"]:
        fields.append(
            f'f{f["id"]}: table(dataType: Buffs, abilityID: {EBON_MIGHT}, '
            f'sourceID: {rep["aug_id"]}, targetID: {rep["aug_id"]}, '
            f'startTime: {float(f["startTime"]):.1f}, endTime: {float(f["endTime"]):.1f})'
        )
    gql = ("query($code: String!) { reportData { report(code: $code) { "
           + " ".join(fields) + " } } }")
    payload = q(f"{rep['key']}_em", gql, {"code": rep["code"]})["reportData"]["report"]
    out = {}
    for f in rep["fights"]:
        table = (payload.get(f'f{f["id"]}') or {}).get("data") or {}
        auras = table.get("auras") or []
        up_ms = float(auras[0].get("totalUptime") or 0) if auras else 0.0
        out[f["id"]] = (up_ms, float(f["endTime"]) - float(f["startTime"]))
    return out


type_obs = Counter()
for rep in reps:
    rep["aug_events"] = fetch_casts(rep, "aug", rep["aug_id"], tracked_ids(aug_cat)) \
        if rep["aug_id"] is not None else {}
    rep["udk_events"] = fetch_casts(rep, "udk", rep["dk_id"], tracked_ids(udk_cat)) \
        if rep["dk_id"] is not None else {}
    rep["death_events"], rep["crystal_events"] = fetch_death_crystal(rep)
    rep["em"] = fetch_em(rep)
    for gid, evs in list(rep["aug_events"].items()) + list(rep["udk_events"].items()):
        for e in evs:
            type_obs[(ability_names.get(gid, gid), e.get("type"))] += 1
    print(f"{rep['code']}: deaths={len(rep['death_events'])} "
          f"crystal events={len(rep['crystal_events'])} em fights={len(rep['em'])}")
print("event types:", dict(sorted(type_obs.items(), key=lambda x: -x[1])[:15]))


def cast_times(evs):
    """'cast' 우선, 없으면 empowerend, 그래도 없으면 begincast."""
    for want in ("cast", "empowerend", "begincast"):
        ts = [e for e in evs if e.get("type") == want]
        if ts:
            return ts
    return []


# ═══ 6. 상위 증강 로그 숨결 레퍼런스 — 기존 산출 JSON 재사용 (재채굴 안 함) ═══
def mine_breath_reference() -> dict:
    """폴백 전용: 기존 JSON에 레퍼런스가 없을 때만 상위로그를 실측."""
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
    gap_med_by_index = {i: round(statistics.median(v), 1)
                        for i, v in sorted(ref_gaps_by_idx.items())}
    return {
        "ability_id": BREATH_ID,
        "n_top_reports": sum(1 for t in top_refs if "t0" in t),
        "all_kills": all(t.get("kill") for t in top_refs if "t0" in t),
        "n_gaps": len(ref_gaps),
        "gap_min_s": round(ref_gaps[0], 1),
        "gap_med_s": med(ref_gaps),
        "gap_med_by_index": gap_med_by_index,
        "raw_cd_estimate_s": gap_med_by_index.get(3),
        "first_cast_med_s": med(ref_firsts),
        "casts_per_min_med": med(ref_counts, 2),
        "note": ("영겁의 숨결 기본쿨 ~120s. 시간 건너뛰기(개전 ~10s, ~150s)로 gap1/2가 "
                 "~73/79s로 압축되는 케이던스가 상위로그 공통 패턴. 지연 판정은 같은 "
                 "인덱스의 상위로그 중앙값 대비 +15s 초과."),
        "sources": [{k: t.get(k) for k in
                     ("code", "fight", "char", "kill", "breath_by_source")} for t in top_refs],
    }


prev_out = {}
if OUT_JSON.exists():
    try:
        prev_out = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    except Exception:
        prev_out = {}
breath_ref = prev_out.get("breath_cd_reference_top_logs")
if breath_ref:
    print("숨결 상위로그 레퍼런스: 기존 JSON 재사용 (재채굴 안 함)")
else:
    breath_ref = mine_breath_reference()
REF_GAP_MED = {int(k): float(v) for k, v in breath_ref["gap_med_by_index"].items()}
REF_GAP_ALL_MED = breath_ref["gap_med_s"]
print(f"숨결 케이던스(상위로그): 인덱스별 med {REF_GAP_MED} · "
      f"min={breath_ref['gap_min_s']}s 전체med={REF_GAP_ALL_MED}s "
      f"(간격 {breath_ref['n_gaps']}건/{breath_ref['n_top_reports']}로그)")


# ═══ 7. 풀별 분석 ═════════════════════════════════════════════════════════
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


def absent_bucket():
    return {"majors": {}, "defensives": {}, "consumables": {}, "mech": {}, "cpm": {},
            "deaths": [], "absent": True}


def player_pull(fight, events_by_gid, cat, pid_actor, deaths_by_fight):
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
    for e in deaths_by_fight[fid]:
        if int(e.get("targetID") or 0) != pid_actor:
            continue
        t = round((float(e["timestamp"]) - t0) / 1000, 1)
        kid = int(e.get("killingAbilityGameID") or 0)
        deaths.append({"t": t, "mmss": mmss(t), "phase": phase_at(track, t),
                       "cause": ability_names.get(kid, str(kid))})
    out["deaths"] = deaths
    return out


def crystal_windows(fight, target_id, crystal_by_fight):
    """운반 창: applydebuff→removedebuff. 미종결은 풀 끝으로 닫음."""
    t0, t1 = float(fight["startTime"]), float(fight["endTime"])
    fid = fight["id"]
    evs = sorted((e for e in crystal_by_fight[fid]
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
em_up_ms = em_dur_ms = 0.0
for rep in reps:
    deaths_by_fight = defaultdict(list)
    for e in rep["death_events"]:
        deaths_by_fight[e.get("fight")].append(e)
    crystal_by_fight = defaultdict(list)
    for e in rep["crystal_events"]:
        crystal_by_fight[e.get("fight")].append(e)

    for fight in rep["fights"]:
        fid = fight["id"]
        t0, t1 = float(fight["startTime"]), float(fight["endTime"])
        dur = round((t1 - t0) / 1000, 1)
        track = build_phase_track(fight)
        if rep["aug_id"] is not None:
            aug_p = player_pull(fight, rep["aug_events"], aug_cat, rep["aug_id"], deaths_by_fight)
            wins = crystal_windows(fight, rep["aug_id"], crystal_by_fight)
        else:
            aug_p, wins = absent_bucket(), []
        udk_p = player_pull(fight, rep["udk_events"], udk_cat, rep["dk_id"], deaths_by_fight) \
            if rep["dk_id"] is not None else absent_bucket()
        breaths = [c["t"] for c in aug_p["majors"].get(BREATH_NAME, [])]
        bcasts, carries, tail = breath_analysis(fight, breaths, wins)
        holders = len({int(e.get("targetID") or 0) for e in crystal_by_fight[fid]
                       if e.get("type") == "applydebuff"})
        max_pid = max((pid for _, pid in track), default=1)
        aug_bucket = {**aug_p, "crystal_carry_windows": [
            {"start": w[0], "end": w[1], "dur_s": round(w[1] - w[0], 1)} for w in wins],
            "breath_casts": bcasts, "carry_breath_check": carries,
            "breath_tail_skip": tail}
        if fid in rep["em"] and rep["aug_id"] is not None:
            up_ms, dur_ms = rep["em"][fid]
            aug_bucket["ebon_might_uptime_pct"] = round(up_ms / dur_ms * 100, 1) if dur_ms else 0.0
            if dur_ms >= CPM_MIN_DUR_S * 1000:
                em_up_ms += up_ms
                em_dur_ms += dur_ms
        pulls.append({
            "pull": 0,  # 아래에서 전체 시간순 재부여
            "fight_id": fid,
            "report_code": rep["code"],
            "date": rep["date_kst"],
            "start_kst": datetime.fromtimestamp((rep["start_ms"] + t0) / 1000, KST)
            .isoformat(timespec="seconds"),
            "duration_s": dur, "duration_mmss": mmss(dur),
            "boss_remaining_pct": round(float(fight.get("bossPercentage") or 0), 2),
            "last_phase": int(fight.get("lastPhase") or 0),
            "max_phase_id": max_pid,
            "kill": bool(fight.get("kill")),
            "phases": [{"t": ts, "mmss": mmss(ts), "phase": phase_label(pid)}
                       for ts, pid in track],
            "reached_p3": max_pid >= 4,  # id4 = Stage Three: Midnight Falls
            "wcl_url": f"https://ko.warcraftlogs.com/reports/{rep['code']}#fight={fid}",
            "aug": aug_bucket,
            "udk": udk_p,
            "raid_crystal_holders": holders,
        })

pulls.sort(key=lambda p: p["start_kst"])
for i, p in enumerate(pulls, 1):
    p["pull"] = i
pulls_by_report = Counter(p["report_code"] for p in pulls)


# ═══ 8. 전체 세션 집계 ════════════════════════════════════════════════════
def aggregate(pkey: str, cat: dict) -> dict:
    firsts = defaultdict(list)
    per_pull_n = defaultdict(list)
    cpm_acc = defaultdict(list)
    def_uses = Counter()
    consum_uses = Counter()
    mech_uses = Counter()
    def_n, deaths = [], []
    used = [p for p in pulls if not p[pkey].get("absent")]
    for p in used:
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
        "pulls": len(used),
        "first_cast_med_s": {nm: med(v) for nm, v in firsts.items()},
        "casts_per_pull_med": {nm: med(v) for nm, v in per_pull_n.items()},
        "casts_per_pull_total": {nm: sum(v) for nm, v in per_pull_n.items()},
        "core_cpm_med": {nm: med(v, 2) for nm, v in cpm_acc.items()},
        "core_cpm_pulls_used": (f">={CPM_MIN_DUR_S}s "
                                f"({sum(1 for p in used if p['duration_s'] >= CPM_MIN_DUR_S)}풀)"),
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
aug_agg["ebon_might_uptime_pct"] = round(em_up_ms / em_dur_ms * 100, 1) if em_dur_ms else None
aug_agg["ebon_might_uptime_note"] = (
    ">=90s 풀 가중 평균 (버프 395296 self, 상위권 채굴과 동일 방식) — 전체 리포트 합산"
)

# 숨결×운반 전체 요약
all_carries = [c for p in pulls for c in p["aug"].get("carry_breath_check") or []]
all_bcasts = [b for p in pulls for b in p["aug"].get("breath_casts") or []]
dur_by_phase = defaultdict(list)
for c in all_carries:
    dur_by_phase[c["phase"]].append(c["dur_s"])
delayed = [b for b in all_bcasts if b["delayed"]]
carry_summary = {
    "carry_windows_total": len(all_carries),
    "carry_dur_med_s": med([c["dur_s"] for c in all_carries]),
    "carry_dur_med_by_phase": {ph: {"n": len(v), "med_s": med(v)}
                               for ph, v in sorted(dur_by_phase.items())},
    "pulls_with_carry": sum(1 for p in pulls if p["aug"].get("crystal_carry_windows")),
    "breath_casts_total": len(all_bcasts),
    "breath_during_carry": sum(1 for b in all_bcasts if b["during_carry"]),
    "breath_delayed_total": len(delayed),
    "breath_delayed_during_carry": sum(1 for b in delayed if b.get("delayed_during_carry")),
    "delay_delta_med_s": med([b["delta_vs_top_s"] for b in delayed]),
    "held_while_carrying_windows": sum(1 for c in all_carries if c["held_while_carrying"]),
    "tail_skips": [
        {"pull": p["pull"], "fight_id": p["fight_id"], "report_code": p["report_code"],
         **p["aug"]["breath_tail_skip"]}
        for p in pulls if p["aug"].get("breath_tail_skip")],
    "delayed_casts_detail": [
        {"pull": p["pull"], "fight_id": p["fight_id"], "report_code": p["report_code"], **b}
        for p in pulls for b in p["aug"].get("breath_casts") or [] if b["delayed"]],
}

best = min(pulls, key=lambda p: (0 if p["kill"] else 1, p["boss_remaining_pct"]))
kills_total = sum(p["kill"] for p in pulls)

report_entries = []
for rep in reps:
    rep_pulls = [p for p in pulls if p["report_code"] == rep["code"]]
    report_entries.append({
        "code": rep["code"], "title": rep["title"],
        "url": f"https://ko.warcraftlogs.com/reports/{rep['code']}",
        "date_kst": rep["date_kst"],
        "pulls": len(rep_pulls),
        "kills": sum(p["kill"] for p in rep_pulls),
        "best_boss_remaining_pct": min(p["boss_remaining_pct"] for p in rep_pulls),
        "aug_actor_id": rep["aug_id"], "udk_actor_id": rep["dk_id"],
    })

notes = [
    "여러 리포트 합산 — actor ID는 리포트마다 다름(reports[].aug_actor_id/udk_actor_id 참조). "
    "풀 번호는 전체 리포트 시간순으로 재부여, 원본 fight_id·report_code는 풀마다 보존.",
    "리포트가 영어 스펠명으로 반환됨 — 앵커 대응: 영겁의 숨결=Breath of Eons, "
    "화염 숨결=Fire Breath, 대격변=Upheaval, 예지=Prescience, 시간 건너뛰기=Time Skip, "
    "일렁이는 빛=Glimmering(1253031), 여명의 수정=Dawn Crystal(1253050).",
    "UDK 대재앙/가고일/흉물 소환은 이 로그들에 0회 — 부정 12.0 빌드에서 미사용/부재. "
    "주기 쿨기는 어둠의 변신(1233448, ~45s)과 죽음의 군대(42650, 실측 간격 ~95s).",
    "Charge!(1259633)는 죽음의 군대 캐스트와 2s 이내 동시 발생(med 0.8s) — "
    "자동 연동 캐스트로 판단, 별도 추적 제외.",
    "Dawn Crystal(1253050) 캐스트 시각 = Glimmering 운반 창의 끝(투입 액션). "
    "07-19 리포트 fight25에서 7/7 일치 손검증.",
    "phaseTransitions id: 1=Stage One, 2=Intermission, 3=Stage Two, "
    "4=Stage Three(Midnight Falls), 5=Stage Four. WCL fight.lastPhase는 "
    "중간 페이즈 번호 체계가 달라 last_phase=3 ↔ max_phase_id=4가 P3 도달.",
] + absence_notes

out = {
    "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
    "report": {"code": "multi",
               "title": Counter(r["title"] for r in reps).most_common(1)[0][0],
               "url": f"https://ko.warcraftlogs.com/reports/{reps[-1]['code']}",
               "encounter_id": ENCOUNTER_ID, "difficulty": DIFFICULTY,
               "pulls": len(pulls), "kills": kills_total,
               "n_reports": len(reps),
               "date_range_kst": [reps[0]["date_kst"], reps[-1]["date_kst"]],
               "note": f"우리 공대 신화 르우라 트라이 — 리포트 {len(reps)}개 합산 "
                       f"({reps[0]['date_kst']}~{reps[-1]['date_kst']}), 킬 {kills_total}회. "
                       "상위로그 기준과 달리 진도 기반. url은 최신 리포트."},
    "reports": report_entries,
    "players": {
        "aug": {"actor_id": reps[-1]["aug_id"], "name": AUG_NAME,
                "class": "Evoker", "spec": "Augmentation",
                "actor_ids_by_report": {rep["code"]: rep["aug_id"] for rep in reps}},
        "udk": {"actor_id": reps[-1]["dk_id"],
                "name": next((rep["dk_actor"]["name"] for rep in reversed(reps)
                              if rep["dk_actor"]), f"{DK_PREFIX}*"),
                "class": "DeathKnight", "spec": "Unholy",
                "actor_ids_by_report": {rep["code"]: rep["dk_id"] for rep in reps}},
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
    "notes": notes,
    "session_aggregates": {"aug": aug_agg, "udk": udk_agg,
                           "aug_crystal_carry": carry_summary},
    "best_pull": best,
    "pulls": pulls,
}
DATA.mkdir(exist_ok=True)
OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nwrote {OUT_JSON}")

# ═══ 9. 요약 + 손검증 출력 ═══════════════════════════════════════════════
print("\n===== 리포트별 풀 수 =====")
for r in report_entries:
    print(f"  {r['code']}  {r['date_kst']}  {r['pulls']}풀  킬{r['kills']}  "
          f"최고 진도 {r['best_boss_remaining_pct']}%")
print(f"총 {len(pulls)}풀 / 리포트 {len(reps)}개 / 킬 {kills_total}회")

print(f"\n===== 손검증: 최고 풀 pull{best['pull']} "
      f"({best['report_code']} fight{best['fight_id']}, {best['date']}, "
      f"{best['boss_remaining_pct']}%, {best['duration_mmss']}, "
      f"lastPhase={best['last_phase']}) =====")
print("phases:", [(p['mmss'], p['phase']) for p in best['phases']])
for pkey, label in (("aug", AUG_NAME), ("udk", out["players"]["udk"]["name"])):
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
print(f"\n수정 운반(aug): {best['aug'].get('crystal_carry_windows')}")
for c in best["aug"].get("carry_breath_check") or []:
    print(f"  창 {c['window']} {c['phase']}: 창내 숨결 {c['breath_cast_in_window']} "
          f"지연겹침 {c['delay_overlap_s']}s 홀드={c['held_while_carrying']}")
print(f"숨결 캐스트 상세: {[(b['mmss'], b['gap_since_prev_s'], b['ref_gap_top_med_s'], b['delayed']) for b in best['aug'].get('breath_casts') or []]}")
print(f"말미 스킵: {best['aug'].get('breath_tail_skip')}")

print("\n===== 전체 세션 요약 =====")
print(f"AUG 숨결/풀 med={aug_agg['casts_per_pull_med'].get(BREATH_NAME)} "
      f"첫숨결 med={aug_agg['first_cast_med_s'].get(BREATH_NAME)}s "
      f"지연 {carry_summary['breath_delayed_total']}회 / 총 {carry_summary['breath_casts_total']}캐스트")
print(f"AUG 칠흑의 힘 유지율(>=90s 가중): {aug_agg['ebon_might_uptime_pct']}%")
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
