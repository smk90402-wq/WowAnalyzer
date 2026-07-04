# -*- coding: utf-8 -*-
"""냉기 법사 — 버튼 변신 맵 + 프록→행동 매핑 + 쿨기 버스트 정렬 실측.

출력: data/frost_proc_map.json  (기존 파일 수정 없음, 신규 산출물)

입력(캐시만, WCL API 호출 없음):
  data/talent_trees.json                       Mage/Frost 공식 트리(ko) — 이름/설명 원문
  data/spell_db.json                           공식 툴팁(ko) — 버프/스킬 원문
  data/rankings_zone46_mythic_dps_top100.csv   top100 명단 (2026-07-03)
  data/v2_cache_player_fight.json              특성 노드/entry (채택률)
  data/v2_cache_report_meta.json               전투 시각
  scratchpad/frost_cd_events.json              냉법 302킬 casts+buffs (tmp_mine_frost_cd.py 가 추출)
  data/proc_sources_frost.json                 티어 세트 문구 (Blizzard API 원문, 기존 산출물)

특성 선택지(entry id) → 이름 매핑 근거:
  WCL 로그의 talents 는 게임 내 trait entry id 라 talent_trees.json 의 talent_id 와 번호가 다름.
  scratchpad/probe_entry_map.py 로 상위권 캐릭터 34명의 Blizzard 프로필 로드아웃(노드별 선택 옵션)과
  같은 캐릭터의 로그 entry 를 교차 투표해 확정. 103771 만 프로필 투표가 혼재(보스별 스왑 탓)라
  보스별 로그 분포로 판정: entry 128077 은 선봉대(광역 보스)에서만 93/99 채택, 그 외 8보스 ~0%
  → 광역 선택지 '갈라지는 광선'. (검증 산출: scratchpad/entry_map_votes.json)
"""
from __future__ import annotations
import json, sys, csv
from pathlib import Path
from collections import Counter, defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path(__file__).parent / "data"
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")
OUT = DATA / "frost_proc_map.json"

BOSS_KR = {
    "Imperator Averzian": "아베르지안", "Vorasius": "보라시우스",
    "Vaelgor & Ezzorak": "바엘고어", "Fallen-King Salhadaar": "살라다르",
    "Lightblinded Vanguard": "선봉대", "Crown of the Cosmos": "우주의 왕관",
    "Belo'ren, Child of Al'ar": "벨로렌", "Midnight Falls": "한밤의 도래(르우라)",
    "Chimaerus, the Undreamt God": "카이메루스",
}

# ---- 스펠 ID (302킬 이벤트 실측 + spell_db 공식명 교차확인) ----
RAY = 205021        # 서리 광선
ORB = 84714         # 얼어붙은 구슬
SPIKE = 199786      # 혹한의 쐐기 (시전)
SPIKE_BUFF = 1222865  # 혹한의 쐐기! (강화 준비 버프)
ICICLE_BUFF = 205473  # 고드름 (중첩 버프)
FLURRY = 44614      # 진눈깨비
FROSTBOLT = 116     # 얼음 화살
ICELANCE = 30455    # 얼음창
BF = 190446         # 두뇌 빙결 (버프)
FOF = 44544         # 서리의 손가락 (버프)
TRINKET_USE = 1260459  # 무위의 시야 = 바엘고어의 마지막 시선 사용 (시전+버프 동일 ID)
POTION = 1236994    # 무모함의 물약 (시전+버프 동일 ID, 30초)
TIMEWARP = 80353    # 시간 왜곡 (버프)
BLINK = 1953        # 점멸
SHIMMER = 212653    # 일렁임
MIRROR = 1270829    # 반영 (점멸 대체 선택지)

TRINKET_DUR = 15.0  # 무위의 시야 15초 (감쇠형) — spell_db 1260459
POTION_DUR = 30.0   # 무모함의 물약 30초 — spell_db 1236994

# probe_entry_map.py 확정 매핑 (entry id -> 옵션명). 근거는 모듈 docstring 참조.
ENTRY_NAMES = {
    134418: "혹한의 집중", 128077: "갈라지는 광선",
    134421: "눈보라(위치 지정)", 134538: "눈보라(대상 시전)",
    134183: "시간 걸음", 134182: "시간 재정렬",
    126060: "공간 조작", 80237: "겨울해일",
    136839: "고독한 겨울", 134406: "물의 정령 소환(소거법: 반대 옵션 확정)",
    80163: "일렁임", 134197: "점멸 연마",
}

# Blizzard API 원문 (2026-07-04, /data/wow/spell/{id}, locale=ko_KR) — 산산조각 체계 기반 설명용
SHATTER_BASE = {
    "spell_id": 1246769, "name": "산산조각",
    "text": "얼음 화살 및 진눈깨비로 피해를 입히면 대상에게 빙결을 부여합니다. 최대 20번까지 중첩됩니다.\n\n"
            "얼음창으로 피해를 입히면 적을 산산조각 내 빙결 4중첩을 소모하고, 제거된 중첩 하나당 375의 냉기 피해를 입힙니다.",
    "source": "Blizzard API spell 1246769 (기본 지속효과, 트리 밖)",
}
MASTERY = {
    "spell_id": 1246752, "name": "특화: 빙결과 산산조각",
    "text": "적을 빙결 상태로 만드는 주문의 공격력이 32%만큼 증가합니다.\n\n적을 산산조각 내는 주문의 공격력이 32%만큼 증가합니다.",
    "source": "Blizzard API spell 1246752",
}


# ---------------------------------------------------------------- 로드
def load_tree():
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))["Mage/Frost"]
    nodes = {}
    for tr in ("class", "spec"):
        for nd in tt[tr]:
            nodes[nd["id"]] = (tr, nd)
    for hname, h in tt["hero"].items():
        for nd in h["nodes"]:
            nodes.setdefault(nd["id"], (f"hero:{hname}", nd))
    return nodes


def load_samples():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    fr = [r for r in rows if r["class"] == "Mage" and r["spec"] == "Frost"]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    seen, out = set(), []
    for r in fr:
        key = f"{r['report_id']}:{r['fight_id']}:{r['character']}"
        if key in seen:
            continue
        seen.add(key)
        p = pf.get(key)
        if not isinstance(p, dict) or not p.get("nodes"):
            continue
        out.append({
            "rank": int(r["rank"]), "boss": r["encounter_name"],
            "nodes": [int(x) for x in p["nodes"]],
            "talents": [int(x) for x in (p.get("talents") or [])],
        })
    return fr, pf, out


def load_events(fr, pf):
    """302킬 casts+buffs (스크래치패드 캐시 우선, 없으면 대형 캐시 스트림 추출)."""
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    wanted = {}
    for r in fr:
        rid, fid, ch = r["report_id"], int(r["fight_id"]), r["character"]
        p = pf.get(f"{rid}:{fid}:{ch}")
        if not isinstance(p, dict):
            continue
        sid = p.get("sourceID")
        m = meta.get(rid)
        if sid is None or not m:
            continue
        f = next((x for x in (m.get("fights") or []) if x.get("id") == fid), None)
        if not f:
            continue
        key = f"{rid}:{fid}:{sid}"
        if key not in wanted:
            wanted[key] = {"boss": r["encounter_name"], "rank": int(r["rank"]),
                           "t0": f["startTime"], "t1": f["endTime"]}
    cache = SCRATCH / "frost_cd_events.json"
    if cache.exists():
        ev = json.load(open(cache, encoding="utf-8"))
    else:  # tmp_mine_frost_cd.py 와 동일한 증분 파싱
        s = open(DATA / "v2_cache_events.json", encoding="utf-8").read()
        dec = json.JSONDecoder()
        ev, i, n = {}, 1, len(s)
        while i < n:
            while i < n and s[i] in " \t\r\n,":
                i += 1
            if i >= n or s[i] == "}":
                break
            key, i = dec.raw_decode(s, i)
            while s[i] in " \t\r\n:":
                i += 1
            val, i = dec.raw_decode(s, i)
            if key in wanted:
                ev[key] = val
        SCRATCH.mkdir(parents=True, exist_ok=True)
        json.dump(ev, open(cache, "w", encoding="utf-8"))
    return wanted, ev


# ---------------------------------------------------------------- 통계 도구
def pct(vals, q):
    if not vals:
        return None
    v = sorted(vals)
    return v[min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))]


def med(vals):
    return pct(vals, .5)


def union_len(intervals, lo, hi):
    iv = sorted((max(lo, a), min(hi, b)) for a, b in intervals if min(hi, b) > max(lo, a))
    tot, ce = 0.0, lo - 1
    for a, b in iv:
        if a > ce:
            tot += b - a
            ce = b
        elif b > ce:
            tot += b - ce
            ce = b
    return tot


def buff_windows(buffs, spell_id, dur_ms):
    """applybuff→removebuff 짝짓기. 선행 remove(프리풀)는 0부터, 미종료는 dur 로 마감."""
    evs = sorted((b[0], b[2]) for b in buffs if b[1] == spell_id and b[2] in ("applybuff", "removebuff"))
    wins, start = [], None
    for ts, typ in evs:
        if typ == "applybuff":
            if start is None:
                start = ts
        else:
            wins.append((0 if start is None else start, ts))
            start = None
    if start is not None:
        wins.append((start, start + dur_ms))
    return wins


# ---------------------------------------------------------------- 과제 1: 버튼 변신 맵
def adoption(samples, node_id, entry=None):
    n = len(samples)
    tot = t20 = n20 = 0
    for s in samples:
        if s["rank"] <= 20:
            n20 += 1
        hit = False
        if entry is None:
            hit = node_id in s["nodes"]
        elif len(s["nodes"]) == len(s["talents"]):
            hit = any(nid == node_id and tid == entry for nid, tid in zip(s["nodes"], s["talents"]))
        if hit:
            tot += 1
            if s["rank"] <= 20:
                t20 += 1
    return {"n": tot, "of": n, "pct": round(100 * tot / n, 1),
            "top20_n": t20, "top20_of": n20, "top20_pct": round(100 * t20 / n20, 1) if n20 else None}


def per_boss_entry_share(samples, node_id):
    out = defaultdict(Counter)
    for s in samples:
        if len(s["nodes"]) != len(s["talents"]):
            continue
        for nid, tid in zip(s["nodes"], s["talents"]):
            if nid == node_id:
                out[BOSS_KR.get(s["boss"], s["boss"])][tid] += 1
    return {b: {ENTRY_NAMES.get(t, str(t)): c for t, c in cc.items()} for b, cc in out.items()}


def build_swap_map(tree_nodes, samples, measured):
    def opt(node_id, talent_id=None):
        tr, nd = tree_nodes[node_id]
        opts = nd["options"]
        if talent_id is not None:
            opts = [o for o in opts if o["talent_id"] == talent_id]
        return tr, nd, opts

    entries = []

    # 1) 고드름: 얼음 화살 → 혹한의 쐐기 (핵심 변신)
    tr, nd, [o] = opt(109915)
    entries.append({
        "kind": "버튼 변신(강화)", "original": "얼음 화살", "becomes": "혹한의 쐐기",
        "node_id": 109915, "tree": "냉기 전문화", "talent": o["name"], "spell_id": o["spell_id"],
        "condition": "전투 중 5.4초마다 고드름이 자동으로 1개씩 쌓임(버프 205473). 5개가 모이면 '혹한의 쐐기!' 버프(1222865)가 뜨며 얼음 화살 버튼이 혹한의 쐐기로 강화됨. 시전하면 다시 얼음 화살로.",
        "duration": "다음 시전까지 유지(자연 만료 없음 — 실측 참조)",
        "official_desc": o["desc"].replace("\r", ""),
        "adoption": adoption(samples, 109915),
        "measured": measured.get("spike", {}),
        "note": "우박(고드름 -1초, 노드 108857)은 0/885, 빙결술사(쐐기+20%, 108852)도 0/885 — 쐐기 강화 노드는 안 찍고 고드름 하나만 100%.",
    })

    # 2) 혜성 폭풍: 서리 광선 → 혜성 폭풍 (죽은 기술)
    tr, nd, [o] = opt(62185)
    entries.append({
        "kind": "버튼 변신(대체)", "original": "서리 광선", "becomes": "혜성 폭풍",
        "node_id": 62185, "tree": "냉기 전문화(정점)", "talent": o["name"], "spell_id": o["spell_id"],
        "condition": "특성을 찍으면 서리 광선 버튼 자체가 혜성 폭풍으로 대체", "duration": "상시",
        "official_desc": o["desc"].replace("\r", ""),
        "adoption": adoption(samples, 62185),
        "note": "상위권 채택 0/885, 302킬 시전 0회 — 레이드에서 죽은 선택지.",
    })

    # 3) 혹한의 쐐기 선택 노드 (빙하의 한기 / 빙하 분쇄) — 아무도 안 찍음
    tr, nd, opts = opt(108863)
    entries.append({
        "kind": "버튼 성질 변경(선택 노드)", "original": "혹한의 쐐기", "becomes": None,
        "node_id": 108863, "tree": "냉기 전문화",
        "options": [{"talent": o["name"], "spell_id": o["spell_id"], "official_desc": o["desc"].replace("\r", "")} for o in opts],
        "adoption": adoption(samples, 108863),
        "note": "노드 자체가 0/885 — 상위권은 쐐기 성질 변경 없이 기본형(빙결 3중첩 부여)으로 씀.",
    })

    # 4) 눈보라 선택 노드: 같은 버튼, 시전 방식이 변함
    tr, nd, opts = opt(108864)
    entries.append({
        "kind": "버튼 성질 변경(선택 노드)", "original": "눈보라", "becomes": None,
        "node_id": 108864, "tree": "냉기 전문화",
        "options": [
            {"talent": "눈보라(위치 지정)", "spell_id": 190356, "entry": 134421,
             "official_desc": [o for o in opts if o["spell_id"] == 190356][0]["desc"].replace("\r", ""),
             "adoption": adoption(samples, 108864, 134421)},
            {"talent": "눈보라(대상 시전)", "spell_id": 1248829, "entry": 134538,
             "official_desc": [o for o in opts if o["spell_id"] == 1248829][0]["desc"].replace("\r", ""),
             "adoption": adoption(samples, 108864, 134538)},
        ],
        "per_boss": per_boss_entry_share(samples, 108864),
        "measured": measured.get("blizzard", {}),
        "note": "96%가 위치 지정형. 실제 시전도 190356만 관측(대상 시전형 1248829 시전 0회). 눈보라 자체가 302킬 중 55킬에서만 눌린 조연(바엘고어 쌍보스에 집중).",
    })

    # 5) 서리 광선 선택 노드: 갈라지는 광선 / 혹한의 집중
    tr, nd, opts = opt(103771)
    entries.append({
        "kind": "버튼 성질 변경(선택 노드)", "original": "서리 광선", "becomes": None,
        "node_id": 103771, "tree": "냉기 전문화",
        "options": [
            {"talent": "혹한의 집중", "spell_id": 1247055, "entry": 134418,
             "official_desc": [o for o in opts if o["spell_id"] == 1247055][0]["desc"].replace("\r", ""),
             "adoption": adoption(samples, 103771, 134418)},
            {"talent": "갈라지는 광선", "spell_id": 418733, "entry": 128077,
             "official_desc": [o for o in opts if o["spell_id"] == 418733][0]["desc"].replace("\r", ""),
             "adoption": adoption(samples, 103771, 128077)},
        ],
        "per_boss": per_boss_entry_share(samples, 103771),
        "note": "단일 대상 8보스는 혹한의 집중(광선 +30%) ~100%, 쫄 웨이브 보스인 선봉대만 갈라지는 광선(주위 5명 30% 피해) 94% — 보스 따라 갈아끼우는 노드.",
    })

    # 6) 얼음장: 얼음 방패 버튼의 효과가 바뀜 (면역 → 70% 경감)
    tr, nd, [o] = opt(62085)
    entries.append({
        "kind": "버튼 성질 변경", "original": "얼음 방패(45438)", "becomes": "얼음장(414658)",
        "node_id": 62085, "tree": "직업 공용", "talent": o["name"], "spell_id": o["spell_id"],
        "condition": "특성을 찍으면 얼음 방패 자리가 얼음장으로 — 면역 대신 6초 70% 경감, 이동/시전 가능",
        "duration": "상시",
        "official_desc": o["desc"].replace("\r", ""),
        "adoption": adoption(samples, 62085),
        "measured": measured.get("iceblock", {}),
        "note": "302킬 실측: 얼음장 시전 497회 vs 얼음 방패 시전 3회 — 사실상 전원이 바뀐 버튼을 씀(딜 끊김 없이 경감).",
    })

    # 7) 일렁임: 점멸 → 일렁임
    tr, nd, opts = opt(62105)
    entries.append({
        "kind": "버튼 변신(대체)", "original": "점멸", "becomes": "일렁임",
        "node_id": 62105, "tree": "직업 공용",
        "options": [
            {"talent": "일렁임", "spell_id": 212653, "entry": 80163, "adoption": adoption(samples, 62105, 80163),
             "official_desc": [o for o in opts if o["spell_id"] == 212653][0]["desc"].replace("\r", "")},
            {"talent": "점멸 연마", "spell_id": 1244340, "entry": 134197, "adoption": adoption(samples, 62105, 134197),
             "official_desc": [o for o in opts if o["spell_id"] == 1244340][0]["desc"].replace("\r", "")},
        ],
        "measured": measured.get("blink", {}),
        "note": "99.7%가 일렁임. 302킬에서 점멸 시전 0회·일렁임 1,927회 — 점멸 버튼은 일렁임으로 바뀐다고 보면 됨(시전 중에도 사용 가능).",
    })

    # 8) 반영 (점멸 후 8초 점멸→반영) — 채택 0
    tr, nd, opts = opt(62094)
    entries.append({
        "kind": "버튼 변신(조건부 대체)", "original": "점멸(일렁임)", "becomes": "반영",
        "node_id": 62094, "tree": "직업 공용",
        "options": [
            {"talent": "공간 조작", "spell_id": 1244031, "entry": 126060, "adoption": adoption(samples, 62094, 126060),
             "official_desc": [o for o in opts if o["spell_id"] == 1244031][0]["desc"].replace("\r", "")},
            {"talent": "반영", "spell_id": 1270829, "entry": None, "adoption": {"n": 0, "of": len(samples), "pct": 0.0},
             "official_desc": [o for o in opts if o["spell_id"] == 1270829][0]["desc"].replace("\r", "")},
        ],
        "measured": measured.get("mirror", {}),
        "note": "885명 전원 공간 조작(충전 +1). 반영 채택 0, 시전 0회.",
    })

    # 9) 시간 돌리기: 버튼 자체가 2단(1타 표식 → 2타 귀환)
    tr, nd, [o] = opt(62115)
    entries.append({
        "kind": "2단 버튼(자체 변신)", "original": "시간 돌리기(1타: 표식)", "becomes": "시간 돌리기(2타: 귀환)",
        "node_id": 62115, "tree": "직업 공용", "talent": o["name"], "spell_id": o["spell_id"],
        "condition": "첫 시전 시 장소·체력 저장, 두 번째 시전 혹은 10초 후 귀환",
        "duration": "10초",
        "official_desc": o["desc"].replace("\r", ""),
        "adoption": adoption(samples, 62115),
        "measured": measured.get("altertime", {}),
        "note": "로그에도 두 ID가 따로 찍힘(1타 342245, 2타/귀환 342247).",
    })

    # 10) 시간 걸음 / 시간 재정렬 (시간 돌리기 성질 변경)
    tr, nd, opts = opt(108654)
    entries.append({
        "kind": "버튼 성질 변경(선택 노드)", "original": "시간 돌리기", "becomes": None,
        "node_id": 108654, "tree": "직업 공용",
        "options": [
            {"talent": "시간 걸음", "spell_id": 1244087, "entry": 134183, "adoption": adoption(samples, 108654, 134183),
             "official_desc": [o for o in opts if o["spell_id"] == 1244087][0]["desc"].replace("\r", "")},
            {"talent": "시간 재정렬", "spell_id": 1244090, "entry": 134182, "adoption": adoption(samples, 108654, 134182),
             "official_desc": [o for o in opts if o["spell_id"] == 1244090][0]["desc"].replace("\r", "")},
        ],
        "note": "90%가 시간 걸음(귀환 시 점멸/일렁임 쿨 초기화 — 기동성). 시간 재정렬(체력 25% 미만 자동 발동+50% 회복)은 9%가 보험용으로.",
    })

    # 11) 서리불꽃 강화 (서리불꽃 영웅트리 쪽 변신 — 미채택 증빙)
    tr, nd, [o] = opt(94641)
    entries.append({
        "kind": "버튼 변신(강화)", "original": "얼음불꽃 화살", "becomes": "얼음불꽃 화살(즉시+60%)",
        "node_id": 94641, "tree": "서리불꽃 영웅트리 계열", "talent": o["name"], "spell_id": o["spell_id"],
        "condition": "서리불꽃 주문 시전 시 10% 확률",
        "official_desc": o["desc"].replace("\r", ""),
        "adoption": adoption(samples, 94641),
        "note": "냉법 상위권 885명 전원 주문술사 영웅트리 — 서리불꽃 계열(얼음불꽃 화살 포함)은 채택 0.",
    })
    return entries


# ---------------------------------------------------------------- 과제 3: 정렬 실측
def mine_alignment(wanted, ev):
    per_kill = []
    winterschill_orb = [0, 0]   # 겨울해일 검증: 구슬 직후 1.5초 내 두뇌 빙결 부여
    cast_counts = Counter()
    for key, info in wanted.items():
        e = ev.get(key)
        if not e:
            continue
        t0, t1 = info["t0"], info["t1"]
        D = (t1 - t0) / 1000
        casts = [(c[0], c[1]) for c in (e.get("casts") or []) if len(c) >= 3 and c[2] == "cast"]
        if len(casts) < 20:
            continue
        buffs = e.get("buffs") or []
        rel = lambda ts: (ts - t0) / 1000
        of = lambda sid: sorted(rel(ts) for ts, s in casts if s == sid)
        for _, s in casts:
            cast_counts[s] += 1
        rays, orbs = of(RAY), of(ORB)
        trink, pots = of(TRINKET_USE), of(POTION)
        spikes = of(SPIKE)
        tw_wins = [(rel(a), rel(b)) for a, b in buff_windows(buffs, TIMEWARP, 40_000)]
        pot_wins = [(rel(a), rel(b)) for a, b in buff_windows(buffs, POTION, int(POTION_DUR * 1000))]
        spike_buff_evs = sorted((rel(b[0]), b[2]) for b in buffs if b[1] == SPIKE_BUFF and b[2] in ("applybuff", "removebuff"))
        bf_gains = sorted(rel(b[0]) for b in buffs if b[1] == BF and b[2] in ("applybuff", "refreshbuff"))
        for o in orbs:
            winterschill_orb[1] += 1
            if any(o <= g <= o + 1.5 for g in bf_gains):
                winterschill_orb[0] += 1
        per_kill.append({
            "boss": BOSS_KR.get(info["boss"], info["boss"]), "rank": info["rank"], "D": D,
            "rays": rays, "orbs": orbs, "trink": trink, "pots": pots, "spikes": spikes,
            "tw_wins": tw_wins, "pot_wins": pot_wins, "spike_buff": spike_buff_evs,
        })

    def forward_stats(kills, uses_field, targets_field, w, back=0.0):
        """사용 시각 → target 시전 정렬. back>0 이면 사용 직전 back초의 시전(채널 중 사용)도 인정.

        무작위 기대치 = target 시전들이 만드는 [t-w, t+back] 구간이 전투에서 차지하는 비율
        (사용 시점을 무작위로 찍었을 때 우연히 정렬될 확률). 관측/기대 = lift.
        """
        obs_hit = obs_tot = 0
        null_cov = []
        deltas = []
        for k in kills:
            uses = [u for u in k[uses_field] if u <= k["D"] - w]
            tg = k[targets_field]
            if not tg:
                continue
            cov = union_len([(t - w, t + back) for t in tg], 0, k["D"]) / k["D"]
            for u in uses:
                nxt = next((t for t in tg if t >= u), None)
                if nxt is not None:
                    deltas.append(nxt - u)
                obs_tot += 1
                hit = (nxt is not None and nxt - u <= w) or \
                      (back > 0 and any(u - back <= t < u for t in tg))
                if hit:
                    obs_hit += 1
                null_cov.append(cov)
        if not obs_tot:
            return None
        obs = 100 * obs_hit / obs_tot
        exp = 100 * sum(null_cov) / len(null_cov)
        return {"uses": obs_tot, "within_s": w, "back_s": back,
                "observed_pct": round(obs, 1), "random_pct": round(exp, 1),
                "lift": round(obs / exp, 2) if exp else None,
                "delta_med_s": round(med(deltas), 1) if deltas else None,
                "delta_p75_s": round(pct(deltas, .75), 1) if deltas else None}

    def inwindow_stats(kills, wins_field, targets_field, fixed_dur=None, uses_field=None):
        """버프 창 안에서 나간 시전 비율 vs 창이 전투에서 차지하는 비율."""
        hit = tot = 0
        cov_num = cov_den = 0.0
        for k in kills:
            if fixed_dur is not None:
                wins = [(u, u + fixed_dur) for u in k[uses_field]]
            else:
                wins = k[wins_field]
            if not wins:
                continue
            tg = k[targets_field]
            cov_num += union_len(wins, 0, k["D"])
            cov_den += k["D"]
            for t in tg:
                tot += 1
                if any(a <= t <= b for a, b in wins):
                    hit += 1
        if not tot or not cov_den:
            return None
        obs = 100 * hit / tot
        exp = 100 * cov_num / cov_den
        return {"casts": tot, "observed_in_window_pct": round(obs, 1),
                "window_share_of_fight_pct": round(exp, 1),
                "lift": round(obs / exp, 2) if exp else None}

    def cadence(kills, field, cd):
        gaps, firsts, effs = [], [], []
        for k in kills:
            ts = k[field]
            if ts:
                firsts.append(ts[0])
                gaps += [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
                effs.append(len(ts) / (k["D"] / cd + 1))
        if not firsts:
            return None
        return {"first_use_med_s": round(med(firsts), 1),
                "gap_med_s": round(med(gaps), 1) if gaps else None,
                "gap_within_cd_plus3_pct": round(100 * sum(1 for g in gaps if g <= cd + 3) / len(gaps), 1) if gaps else None,
                "hold_beyond_cd_med_s": round(med([max(0.0, g - cd) for g in gaps]), 1) if gaps else None,
                "uses_per_fight_med": med(sorted(len(k[field]) for k in kills)),
                "efficiency_med": round(med(effs), 2)}

    def band_block(kills):
        return {
            "trinket_to_ray": {f"w{w}": forward_stats(kills, "trink", "rays", w) for w in (5, 10, 15)},
            "trinket_to_ray_incl_channeling": forward_stats(kills, "trink", "rays", 10, back=4.0),
            "trinket_to_orb": {f"w{w}": forward_stats(kills, "trink", "orbs", w) for w in (5, 10, 15)},
            "ray_in_trinket_window": inwindow_stats(kills, None, "rays", fixed_dur=TRINKET_DUR, uses_field="trink"),
            "orb_in_trinket_window": inwindow_stats(kills, None, "orbs", fixed_dur=TRINKET_DUR, uses_field="trink"),
            "ray_in_potion_window": inwindow_stats(kills, "pot_wins", "rays"),
            "orb_in_potion_window": inwindow_stats(kills, "pot_wins", "orbs"),
            "ray_in_timewarp": inwindow_stats(kills, "tw_wins", "rays"),
            "orb_in_timewarp": inwindow_stats(kills, "tw_wins", "orbs"),
        }

    top = [k for k in per_kill if k["rank"] <= 20]
    rest = [k for k in per_kill if k["rank"] > 20]

    # 보스별 대표 지표 (10초 정렬 lift)
    per_boss = {}
    bykill = defaultdict(list)
    for k in per_kill:
        bykill[k["boss"]].append(k)
    for b, ks in sorted(bykill.items(), key=lambda x: -len(x[1])):
        f = forward_stats(ks, "trink", "rays", 10)
        per_boss[b] = {"n": len(ks), "trinket_to_ray_w10": f}

    # 혹한의 쐐기! 버프 보유(들고 있는) 시간 실측
    holds = []
    for k in per_kill:
        start = None
        for t, typ in k["spike_buff"]:
            if typ == "applybuff":
                if start is None:
                    start = t
            elif start is not None:
                holds.append(t - start)
                start = None
    spike_meas = {
        "spike_casts_per_fight_med": med(sorted(len(k["spikes"]) for k in per_kill)),
        "buff_hold_med_s": round(med(holds), 1) if holds else None,
        "buff_hold_p90_s": round(pct(holds, .9), 1) if holds else None,
        "buff_hold_n": len(holds),
    }

    opener = {
        "trinket_first_med_s": round(med([k["trink"][0] for k in per_kill if k["trink"]]), 1),
        "trinket_first_within5s_pct": round(100 * sum(1 for k in per_kill if k["trink"] and k["trink"][0] <= 5) / sum(1 for k in per_kill if k["trink"]), 1),
        "potion_first_med_s": round(med([k["pots"][0] for k in per_kill if k["pots"]]), 1),
        "ray_first_med_s": round(med([k["rays"][0] for k in per_kill if k["rays"]]), 1),
        "orb_first_med_s": round(med([k["orbs"][0] for k in per_kill if k["orbs"]]), 1),
    }

    result = {
        "n_kills": len(per_kill),
        "bands": {"rank_1_20": len(top), "rank_21_100": len(rest)},
        "usage_cadence": {
            "trinket(무위의 시야, 90s쿨)": cadence(per_kill, "trink", 90),
            "ray(서리 광선, 표기 60s쿨-빙하 작용 단축)": cadence(per_kill, "rays", 60),
            "orb(얼어붙은 구슬, 60s쿨)": cadence(per_kill, "orbs", 60),
            "potion(무모함의 물약, 5분쿨)": cadence(per_kill, "pots", 300),
        },
        "opener": opener,
        "overall": band_block(per_kill),
        "rank_1_20": band_block(top),
        "rank_21_100": band_block(rest),
        "per_boss_trinket_ray": per_boss,
        "spike_measured": spike_meas,
        "sanity_checks": {
            "겨울해일(구슬→두뇌 빙결 1.5s 내)": {
                "orb_casts": winterschill_orb[1],
                "bf_within_1p5s_pct": round(100 * winterschill_orb[0] / winterschill_orb[1], 1) if winterschill_orb[1] else None,
                "comment": "entry 80237=겨울해일 매핑 교차 검증(885명 전원 채택)"},
            "blink_vs_shimmer_casts": {"점멸(1953)": cast_counts.get(BLINK, 0), "일렁임(212653)": cast_counts.get(SHIMMER, 0)},
            "반영(1270829)_casts": cast_counts.get(MIRROR, 0),
            "눈보라_casts": {"190356(위치)": cast_counts.get(190356, 0), "1248829(대상)": cast_counts.get(1248829, 0)},
            "얼음방패_vs_얼음장_casts": {"얼음 방패(45438)": cast_counts.get(45438, 0), "얼음장(414658)": cast_counts.get(414658, 0)},
            "시간돌리기_casts": {"1타(342245)": cast_counts.get(342245, 0), "2타/귀환(342247)": cast_counts.get(342247, 0)},
        },
    }
    kills_with_bliz = sum(1 for key, e in ev.items()
                          if any(len(c) >= 3 and c[2] == "cast" and c[1] in (190356, 1248829)
                                 for c in (e.get("casts") or [])))
    measured_for_map = {
        "spike": spike_meas,
        "blizzard": {"casts_190356": cast_counts.get(190356, 0), "casts_1248829": cast_counts.get(1248829, 0),
                     "kills_with_blizzard": kills_with_bliz},
        "iceblock": {"casts_45438": cast_counts.get(45438, 0), "casts_414658": cast_counts.get(414658, 0)},
        "blink": {"casts_blink": cast_counts.get(BLINK, 0), "casts_shimmer": cast_counts.get(SHIMMER, 0)},
        "mirror": {"casts": cast_counts.get(MIRROR, 0)},
        "altertime": {"casts_mark": cast_counts.get(342245, 0), "casts_return": cast_counts.get(342247, 0)},
    }
    return result, measured_for_map


# ---------------------------------------------------------------- 과제 2: 프록 → 행동 매핑
def strip_tooltip(html):
    import re
    t = re.sub(r"<br\s*/?>", "\n", html or "")
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\r", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def tooltip_body(db, sid):
    e = db.get(str(sid))
    if not e:
        return None
    txt = strip_tooltip(e.get("tooltip_ko"))
    # 머리말(이름/사정거리/재사용 등) 뒤의 본문만 남기기엔 포맷이 다양 — 원문 그대로 보존
    return txt


def build_proc_map(db, tree_nodes, samples, tier_texts):
    def tree_desc(node_id, spell_id=None):
        _, nd = tree_nodes[node_id]
        for o in nd["options"]:
            if spell_id is None or o["spell_id"] == spell_id:
                return o["desc"].replace("\r", "")
        return None

    return {
        "기본기_읽기전_배경": {
            "산산조각_체계": SHATTER_BASE,
            "특화": MASTERY,
            "쉬운_설명": "냉법의 뼈대: 얼음 화살·진눈깨비(등)가 적에게 '빙결'을 쌓고(최대 20중첩), 얼음창이 빙결 4중첩을 '산산조각'내 중첩당 추가 피해를 뽑는다. 아래 프록들은 전부 이 쌓기→깨기 순환의 어딘가를 강화한다.",
        },
        "procs": [
            {
                "name": "서리의 손가락", "buff_id": 44544, "talent_node": 62164, "talent_spell": 112965,
                "adoption": adoption(samples, 62164),
                "official_tooltip_buff": tooltip_body(db, 44544),
                "official_desc_talent": tree_desc(62164),
                "trigger": "얼음 화살 시전 시 15% 확률(얼어붙은 손길로 25% 더 자주 발동). 그 외 부여원: 혹한의 쐐기 시전 시 100%(순간 빙결), 얼어붙은 구슬 시전 시 1중첩+구슬이 피해를 입힐 때 3%(영원한 서리), 서리 광선 지속 중 2중첩(결정화된 굴절), 티어 2세트: 진눈깨비 시전 시 10%.",
                "effect": "별도 스킬이 아니고 버튼도 안 바뀜 — 내 몸에 붙는 충전형 버프(최대 2충전). 이게 있으면 '다음 얼음창'이 대상의 빙결 중첩과 무관하게 '빙결 4중첩을 산산조각 낸 것과 같은' 강화 피해로 들어가고, 실제 빙결 중첩은 소모하지 않는다. 티어 4세트로 이 산산조각 피해 +15%.",
            "consumed_by": "얼음창 (시전 1회당 1충전 소모)",
                "explain_easy": "처음 보는 사람용: 얼음창은 원래 '빙결이 쌓인 적'에게 써야 아픈 기술인데, 서리의 손가락 버프가 있으면 아무 때나 얼음창을 꽂아도 최대 위력(빙결 4중첩 산산조각)으로 들어간다. 그래서 냉법 화면에 이 버프가 뜨면 = '얼음창 공짜 강타권 1장'. 2장까지 저장되니 안 쓰고 묵히면 새 프록이 증발한다(실측: 상위권도 획득의 3.9%는 낭비, 대부분 2충전 상태 겹침).",
                "measured_ref": "frost_proc_timing.json — 소모까지 중앙 1.76초, 3초 내 소모 84.5%, 분당 획득 14.9회",
            },
            {
                "name": "두뇌 빙결", "buff_id": 190446, "talent_node": 62179, "talent_spell": 190447,
                "adoption": adoption(samples, 62179),
                "official_tooltip_buff": tooltip_body(db, 190446),
                "official_desc_talent": tree_desc(62179),
                "trigger": "얼음 화살 시전 시 25% 확률(얼어붙은 손길로 +20% 더 자주). 겨울해일(885명 전원 채택): 얼어붙은 구슬 시전 시 100% 부여 — 실측 302킬에서 구슬 직후 1.5초 내 두뇌 빙결 부여 확인.",
                "effect": "진눈깨비의 남은 쿨이 초기화되고, 다음 진눈깨비 공격력 +50%. 버튼은 그대로 진눈깨비 — '지금 눌러도 됨' 신호등.",
                "consumed_by": "진눈깨비 (강화 소모) → 소모하면 열기 동공이 뜸(아래)",
                "explain_easy": "진눈깨비 쿨 리셋+강화 티켓. 진눈깨비는 빙결 3중첩을 쌓아주는 핵심 셋업기라, 두뇌 빙결이 뜨면 '진눈깨비→얼음창' 콤보를 바로 돌리라는 뜻.",
                "measured_ref": "frost_proc_timing.json — 소모까지 중앙 1.27초, 3초 내 89.1%, 낭비 3.3%",
            },
            {
                "name": "열기 동공", "buff_id": 1247730, "talent_node": 62182, "talent_spell": 1247729,
                "adoption": adoption(samples, 62182),
                "official_tooltip_buff": tooltip_body(db, 1247730),
                "official_desc_talent": tree_desc(62182),
                "trigger": "두뇌 빙결을 소모하면(=강화 진눈깨비를 쓰면) 100%",
                "effect": "다음 얼음창이 빙결 4중첩을 '추가로' 산산조각 — 한 번에 8중첩 분량을 깬다.",
                "consumed_by": "얼음창",
                "explain_easy": "두뇌 빙결→진눈깨비 뒤에는 얼음창이 두 배로 아파진다. 진눈깨비(빙결 3~4중첩 적립)→얼음창(중첩+열기 동공 동시 정산) 순서를 지키면 자동으로 소모되는 구조라 따로 관리할 건 없음.",
            },
            {
                "name": "빗발치는 냉기", "buff_id": 270232, "talent_node": 108860, "talent_spell": 270233,
                "adoption": adoption(samples, 108860),
                "official_tooltip_buff": tooltip_body(db, 270232),
                "official_desc_talent": tree_desc(108860),
                "trigger": "얼어붙은 구슬 시전 시",
                "effect": "눈보라가 즉시 시전되고(시전바 생략) 눈보라 공격력 +20%.",
                "consumed_by": "눈보라",
                "explain_easy": "★상위권이 안 찍는 특성★ — 채택 4/885(0.5%), 버프 관측도 302킬 중 1킬. 이번 시즌 눈보라 자체가 거의 안 눌리는(302킬 중 55킬, 대부분 바엘고어) 조연이라 가이드에서 다룰 필요 없음.",
            },
            {
                "name": "차디찬 손길", "buff_id": 1263263, "talent_node": 110422, "talent_spell": 1262935,
                "adoption": adoption(samples, 110422),
                "official_tooltip_buff": tooltip_body(db, 1263263),
                "official_desc_talent": tree_desc(110422),
                "trigger": "적을 산산조각 낼 때 10% 확률로 유령(차디찬 손길)이 자동 소환 — 깬 빙결 중첩 하나당 확률 +1%p(버프 툴팁).",
                "effect": "유령이 적을 추적해 피해+빙결 1중첩. 유령이 피해를 입힐 때마다 내게 '주문 공격력 +1%' 8초 중첩 버프(1263263)가 쌓임 — 화면에 뜨는 버프는 이것.",
                "consumed_by": "없음(소모형 아님 — 자동 축적/자동 만료)",
                "explain_easy": "누르는 것도, 아껴 쓸 것도 없음. 얼음창을 정상적으로 돌리면 알아서 유령이 나오고 알아서 딜이 오른다. 302킬 전 킬에서 관측(버프 이벤트 6.5만 회) — '내 버프창에 자꾸 뜨는 저게 뭐지' 답변용.",
            },
            {
                "name": "공허파괴자의 합의 2세트(티어)", "buff_id": 44544,
                "adoption": "885/885 (2부위 이상)",
                "official_text": tier_texts.get("2set"),
                "trigger": "진눈깨비 시전 시 10% 확률",
                "effect": "새 버프가 아니라 기존 '서리의 손가락' 충전을 부여 + 진눈깨비 공격력 +10%.",
                "consumed_by": "얼음창 (서리의 손가락과 동일)",
                "explain_easy": "티어를 입으면 서리의 손가락이 더 자주 뜬다 — 관리법은 그대로(얼음창으로 소모).",
            },
            {
                "name": "공허파괴자의 합의 4세트(티어)", "buff_id": None,
                "adoption": "882/885 (4부위 이상)",
                "official_text": tier_texts.get("4set"),
                "trigger": "서리의 손가락 보유 중 (패시브)",
                "effect": "서리의 손가락이 산산조각 공격력을 +15% — 수치 강화만, 새 버프·버튼 없음.",
                "consumed_by": "없음",
                "explain_easy": "서리의 손가락 얼음창이 더 아파진다는 뜻. 행동 변화 없음.",
            },
        ],
    }


# ---------------------------------------------------------------- 메인
def main():
    tree_nodes = load_tree()
    fr, pf, samples = load_samples()
    print(f"특성 표본 {len(samples)}명 (top20 {sum(1 for s in samples if s['rank'] <= 20)})", flush=True)
    wanted, ev = load_events(fr, pf)
    print(f"이벤트 킬 {len(ev)}/{len(wanted)}", flush=True)

    alignment, measured = mine_alignment(wanted, ev)
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))

    # 티어 문구 (기존 proc_sources_frost.json 의 Blizzard API 원문 재사용)
    ps = json.load(open(DATA / "proc_sources_frost.json", encoding="utf-8"))
    tier_texts = {}
    for s in ps.get("sources", []):
        if s.get("source") == "티어":
            if "2세트" in (s.get("name") or ""):
                tier_texts["2set"] = {"text": s.get("effect"), "source": s.get("text_source")}
            if "4세트" in (s.get("name") or ""):
                tier_texts["4set"] = {"text": s.get("effect"), "source": s.get("text_source")}

    swap_map = build_swap_map(tree_nodes, samples, measured)
    proc_map = build_proc_map(db, tree_nodes, samples, tier_texts)

    # ---- 결론 문장 (실측 수치 기반) ----
    ov = alignment["overall"]
    t10 = ov["trinket_to_ray"]["w10"]
    o10 = ov["trinket_to_orb"]["w10"]
    riw = ov["ray_in_trinket_window"]
    cad = alignment["usage_cadence"]
    t5 = ov["trinket_to_ray"]["w5"]
    rp = ov["ray_in_potion_window"]
    rtw = ov["ray_in_timewarp"]
    top10 = alignment["rank_1_20"]["trinket_to_ray"]["w10"]
    rest10 = alignment["rank_21_100"]["trinket_to_ray"]["w10"]
    tc = cad["trinket(무위의 시야, 90s쿨)"]
    rc = cad["ray(서리 광선, 표기 60s쿨-빙하 작용 단축)"]
    oc = cad["orb(얼어붙은 구슬, 60s쿨)"]
    conclusion = {
        "질문": "냉법은 서리 광선/얼어붙은 구슬을 장신구·물약 버프에 맞춰 설계해서 쓰는 스펙인가, 그냥 쿨마다 던지는 스펙인가?",
        "수치": {
            "장신구 후 5초 내 광선": f"관측 {t5['observed_pct']}% vs 무작위 기대 {t5['random_pct']}% (lift {t5['lift']}, 지연 중앙 {t5['delta_med_s']}s)",
            "장신구 후 10초 내 광선": f"관측 {t10['observed_pct']}% vs 무작위 기대 {t10['random_pct']}% (lift {t10['lift']})",
            "장신구 후 10초 내 구슬": f"관측 {o10['observed_pct']}% vs 무작위 기대 {o10['random_pct']}% (lift {o10['lift']}, 지연 중앙 {o10['delta_med_s']}s)",
            "광선이 장신구 15초 창 안에서 나간 비율": f"{riw['observed_in_window_pct']}% (창의 전투 점유율 {riw['window_share_of_fight_pct']}%, lift {riw['lift']})",
            "광선이 물약 30초 창 안": f"{rp['observed_in_window_pct']}% (점유율 {rp['window_share_of_fight_pct']}%, lift {rp['lift']})",
            "광선이 시간 왜곡 창 안": f"{rtw['observed_in_window_pct']}% (점유율 {rtw['window_share_of_fight_pct']}%, lift {rtw['lift']})",
            "밴드 비교(장신구→광선 10s)": f"rank1-20 {top10['observed_pct']}% vs rank21-100 {rest10['observed_pct']}% (lift {top10['lift']} vs {rest10['lift']})",
            "장신구 사용 간격": tc,
            "광선 사용 간격": rc,
            "구슬 사용 간격": oc,
        },
        "판정": [
            f"서리 광선 = '장신구에 맞춰 설계'가 맞다. 장신구를 누르면 중앙 {t5['delta_med_s']}초 만에 광선이 나가고(5초 내 {t5['observed_pct']}%), 무작위 기대치의 {t5['lift']}배. 광선의 {riw['observed_in_window_pct']}%가 장신구 15초 창 안에서 나감(우연 기대 {riw['window_share_of_fight_pct']}%).",
            f"방향은 '광선을 오래 쥐고 기다린다'기보다 '장신구를 광선에 붙여 누른다'에 가깝다 — 광선 간격의 {rc['gap_within_cd_plus3_pct']}%가 쿨+3초 안(사실상 쿨마다)이고, 장신구는 쿨(90초)보다 중앙 {tc['hold_beyond_cd_med_s']}초 늦게 눌러 광선 타이밍에 맞춘다.",
            f"얼어붙은 구슬 = '쿨마다'가 맞다. 간격의 {oc['gap_within_cd_plus3_pct']}%가 쿨 즉시(중앙 {oc['gap_med_s']}초 — 영웅트리 '비전냉기의 가르침'(쇄편 피해마다 구슬 쿨 -0.25초, 885명 전원 채택)이 표기 60초를 크게 앞당김. 얼음창의 구슬 쿨감(백시 현상)은 채택 0), 장신구 정렬 lift 는 {ov['orb_in_trinket_window']['lift']}로 미미. 구슬을 위해 버프를 기다리는 흔적 없음.",
            f"물약은 오프너(중앙 {alignment['opener']['potion_first_med_s']}초)에 붙이고, 장신구도 첫 사용은 풀링 직후(중앙 {alignment['opener']['trinket_first_med_s']}초) — 오프너에 광선·구슬·물약·장신구가 한꺼번에 겹치는 구조.",
            f"상위 1-20위와 21-100위의 정렬 규율 차이는 거의 없다(lift {top10['lift']} vs {rest10['lift']}) — 장신구-광선 짝짓기는 상위권 전유물이 아니라 냉법의 기본기.",
        ],
    }

    out = {
        "_meta": {
            "generated_by": "tmp_mine_frost_procmap.py",
            "spec": "Mage|Frost", "zone": 46, "difficulty": "mythic", "partition": "12.0.7",
            "sample_talents": len(samples), "sample_event_kills": alignment["n_kills"],
            "naming": "스킬·특성명은 talent_trees.json / spell_db.json 공식 한글명만 사용. 선택지 entry 매핑 근거는 스크립트 docstring.",
            "no_wcl_api": True,
        },
        "task1_button_swap_map": swap_map,
        "task2_proc_action_map": proc_map,
        "task3_burst_alignment": alignment,
        "conclusion": conclusion,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"저장: {OUT}", flush=True)

    # ---- 콘솔 리포트 ----
    print("\n===== 과제3 핵심 =====")
    for w in (5, 10, 15):
        f = ov["trinket_to_ray"][f"w{w}"]
        print(f"장신구→광선 {w}s: 관측 {f['observed_pct']}% / 무작위 {f['random_pct']}% (lift {f['lift']}, 지연 중앙 {f['delta_med_s']}s)")
    for w in (5, 10, 15):
        f = ov["trinket_to_orb"][f"w{w}"]
        print(f"장신구→구슬 {w}s: 관측 {f['observed_pct']}% / 무작위 {f['random_pct']}% (lift {f['lift']}, 지연 중앙 {f['delta_med_s']}s)")
    print("광선 in 장신구창:", riw)
    print("광선 in 물약창:", ov["ray_in_potion_window"])
    print("광선 in 시간왜곡:", ov["ray_in_timewarp"])
    print("구슬 in 장신구창:", ov["orb_in_trinket_window"])
    print("케이던스:", json.dumps(cad, ensure_ascii=False, indent=1))
    print("오프너:", alignment["opener"])
    print("혹한의 쐐기 실측:", alignment["spike_measured"])
    print("검증:", json.dumps(alignment["sanity_checks"], ensure_ascii=False, indent=1))
    print("\n밴드 비교 (10s 장신구→광선):")
    for band in ("rank_1_20", "rank_21_100"):
        f = alignment[band]["trinket_to_ray"]["w10"]
        print(f"  {band}: 관측 {f['observed_pct']}% / 무작위 {f['random_pct']}% (lift {f['lift']})")


if __name__ == "__main__":
    main()
