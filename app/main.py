"""FastAPI 앱 — 기존 wcl_v2_data + 캐시 + 랭킹 CSV 를 JSON API 로 노출.

엔드포인트:
  GET /api/ping                              — 헬스 체크
  GET /api/rankings/{difficulty}            — heroic|mythic top100 랭킹 (CSV → JSON)
  GET /api/report/{rid}                      — V2Data.report_meta(rid)
  GET /api/character/{rid}/{fid}/{char}     — pfight + casts + buffs + stats + prepull

기존 V2Data 싱글톤 그대로 사용. 디스크 캐시 / API 키 모두 wcl_v2_data 가 처리.
"""
from __future__ import annotations

import atexit
import logging
import sys
from pathlib import Path

import json

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# 기존 백엔드 그대로 import
from wcl_v2_data import V2Data

from app import talent_tree as tt_render
from app import timeline as tl_render

log = logging.getLogger("app.main")

# Frozen (.exe) vs dev — DATA_DIR 은 항상 exe 옆 (사용자가 캐시 갱신 가능),
# STATIC_DIR 은 bundle 안 (read-only, PyInstaller --add-data 로 포함).
if getattr(sys, "frozen", False):
    DATA_DIR = Path(sys.executable).parent / "data"
    STATIC_DIR = Path(__file__).parent / "static"
else:
    DATA_DIR = Path(__file__).parent.parent / "data"
    STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

app = FastAPI(title="WowAnalyzer API", version="0.1.0")

# static 파일 마운트 (Week 2 에서 HTML/CSS/JS 추가)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """루트 — Week 2: SPA shell 서빙."""
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return idx.read_text(encoding="utf-8")
    # 파일 없으면 안내
    return (
        "<h1>index.html missing</h1>"
        f"<p>expected at: {idx}</p>"
        "<p>app/static/ 가 비어있으면 git pull 다시 받아주세요.</p>"
    )

# V2Data 싱글톤 — 첫 요청 때 lazy 초기화 (API 키 / 캐시 로드)
_v2_inst: V2Data | None = None


def _v2() -> V2Data:
    global _v2_inst
    if _v2_inst is None:
        _v2_inst = V2Data(data_dir=DATA_DIR)
        # FastAPI 핸들러가 캐시를 변경해도 디스크에 저장되지 않으면 .exe 재시작 시 손실.
        # atexit 으로 우아한 종료 시 flush. pywebview 윈도우 닫기 → 메인 스레드 종료 시 호출됨.
        atexit.register(_v2_inst.flush)
    return _v2_inst


# ── 헬스 ────────────────────────────────────────────────────────────────────
@app.get("/api/ping")
def ping() -> dict:
    return {"ok": True, "msg": "WowAnalyzer API live"}


# ── 랭킹 CSV → JSON ─────────────────────────────────────────────────────────
DIFFICULTY_FILES = {
    "heroic": "rankings_zone46_heroic_dps_top100.csv",
    "mythic": "rankings_zone46_mythic_dps_top100.csv",
}


@app.get("/api/rankings/{difficulty}")
def rankings(difficulty: str) -> Response:
    fname = DIFFICULTY_FILES.get(difficulty)
    if not fname:
        raise HTTPException(404, f"unknown difficulty '{difficulty}' "
                                 f"(use one of {list(DIFFICULTY_FILES)})")
    path = DATA_DIR / fname
    if not path.exists():
        raise HTTPException(404, f"rankings CSV not found: {path.name} "
                                 f"— run fetch_rankings_v2.py first")
    df = pd.read_csv(path)
    # 영문 보스명 → 한글 (도감 검증된 매핑). 미등록은 영문 유지.
    if "encounter_id" in df.columns and "encounter_name" in df.columns:
        df["encounter_name"] = df.apply(
            lambda r: BOSS_KR.get(int(r["encounter_id"]), r["encounter_name"])
                      if pd.notna(r["encounter_id"]) else r["encounter_name"],
            axis=1,
        )
    # pandas to_json 이 NaN → null 변환 처리 (orient=records). 인덱스 미포함.
    rows_json = df.to_json(orient="records", force_ascii=False)
    payload = (
        f'{{"difficulty":"{difficulty}","row_count":{len(df)},"rows":{rows_json}}}'
    )
    return Response(content=payload, media_type="application/json")


# ── V2 report meta (lazy) ───────────────────────────────────────────────────
@app.get("/api/report/{rid}")
def report_meta(rid: str) -> JSONResponse:
    meta = _v2().report_meta(rid)
    if not meta:
        raise HTTPException(404, f"report '{rid}' 조회 실패 — private/잘못된 ID/네트워크")
    # 한글 보스명 채우기 — 구버전 캐시는 fight.name 자체가 비어있음
    if isinstance(meta, dict):
        for f in meta.get("fights") or []:
            if isinstance(f, dict):
                eid = f.get("encounterID")
                if isinstance(eid, int):
                    f["name"] = BOSS_KR.get(eid) or f.get("name") or f"enc {eid}"
    return JSONResponse(meta)


# ── 캐릭터 상세 (pfight + events + prepull) ─────────────────────────────────
@app.get("/api/character/{rid}/{fid}/{char}")
def character_detail(rid: str, fid: int, char: str) -> JSONResponse:
    """선택 캐릭의 talents/gear + casts/buffs + prepull buffs + stats.

    캐시 미스면 V2 GraphQL 호출 (수~십초). 캐시 hit 이면 ms 단위.
    """
    v2 = _v2()
    pfight_key = f"{rid}:{fid}:{char}"
    if pfight_key not in v2.pfight:
        # backfill_v2 와 동일 흐름: pfight 페치 (talents + gear 포함)
        try:
            v2.player_fight(rid, fid, char)
        except Exception as e:
            raise HTTPException(502, f"V2 player_fight 실패: {e}")
    pf = v2.pfight.get(pfight_key)
    if not isinstance(pf, dict):
        raise HTTPException(404, f"{char} 데이터 캐시 미스 + 재페치 실패")

    sid = pf.get("sourceID") if isinstance(pf.get("sourceID"), int) else None
    raw_gear = pf.get("gear") or []
    item_db = _item_db()

    # gear 에 한글명 + 아이콘 + 슬롯 한글명 inject
    enriched_gear = []
    for g in raw_gear:
        if not isinstance(g, dict):
            continue
        iid = g.get("id")
        slot = g.get("slot") if isinstance(g.get("slot"), int) else -1
        meta = item_db.get(str(iid), {}) if isinstance(iid, int) else {}
        enriched_gear.append({
            "slot": slot,
            "slot_kr": SLOT_KR.get(slot, f"슬롯 #{slot}"),
            "id": iid,
            "name_ko": meta.get("name_ko") or "",
            "icon": meta.get("icon") or "",
            "quality": meta.get("quality") or "",
            "ilvl": g.get("ilvl") or meta.get("ilvl"),
            "gems": g.get("gems") or [],
            "ench": g.get("ench"),
        })
    # 슬롯 순 정렬 (-1 은 끝으로)
    enriched_gear.sort(key=lambda g: (g["slot"] if g["slot"] >= 0 else 999))

    # stats 한글화
    raw_stats = pf.get("stats") or {}
    stats_kr: list[dict] = []
    if isinstance(raw_stats, dict):
        # 1차 스탯 (체력/힘/민첩/지능) 먼저, 그 다음 2차 스탯
        primary = ["Stamina", "Strength", "Agility", "Intellect"]
        secondary = ["Crit", "Haste", "Mastery", "Versatility",
                     "Leech", "Avoidance", "Speed"]
        for k in primary + secondary + ["Item Level"]:
            if k in raw_stats:
                rating = raw_stats[k]
                pct = None
                ratio = RATING_PER_PCT.get(k)
                if ratio and isinstance(rating, (int, float)):
                    pct = rating / ratio
                stats_kr.append({
                    "key": k,
                    "label_kr": STAT_KR.get(k, k),
                    "rating": rating,
                    "pct": pct,  # null 이면 1차 스탯 (rating only)
                })

    # 임의 로그 탭용 — talent_trees.json 5스펙 중 picked nodes 와 가장 많이
    # 매칭되는 스펙 추론. ranking row 의 class/spec 없을 때 프론트가 사용.
    # node_id 사용 (WCL combatantInfo nodeID ↔ Blizzard node.id, 100% 매칭).
    inferred_cls, inferred_spec = _infer_spec(pf.get("nodes") or [])

    out: dict = {
        "rid": rid, "fid": fid, "char": char, "sourceID": sid,
        "talents": pf.get("talents") or [],
        "gear": enriched_gear,
        "stats": raw_stats or None,
        "stats_kr": stats_kr,
        "inferred_class": inferred_cls,
        "inferred_spec": inferred_spec,
    }
    # casts + buffs — events_for 가 sid 매핑 + 페치 모두 처리
    ev = v2.events_for(rid, fid, char) or {}
    out["casts"] = ev.get("casts") or []
    out["buffs"] = ev.get("buffs") or []

    # prepull (별도 캐시) — sid 필요. 캐시 hit 만 반환, miss 시 V2 페치 안 함.
    # 이유: prefetch_prepull.py 가 백필 담당. 핫패스에서 추가 API 호출하면
    # 첫 클릭이 수~십초 지연되고, 백필 안 된 캐릭은 어차피 데이터 부족.
    spell_db = _spell_db()
    if sid is not None:
        prepull_key = f"{rid}:{fid}:{sid}"
        cached_pp = v2.prepull.get(prepull_key)
        raw_pp = cached_pp if isinstance(cached_pp, list) else []
        # spell_db 로 name/icon 한글화 — 프론트에서 그대로 쓰게
        enriched_pp: list[dict] = []
        seen: set[int] = set()
        for p in raw_pp:
            if not isinstance(p, dict):
                continue
            spid = p.get("spell_id")
            if not isinstance(spid, int) or spid in seen:
                continue
            seen.add(spid)
            meta_sp = spell_db.get(str(spid), {})
            enriched_pp.append({
                "spell_id": spid,
                "ts": p.get("ts"),
                "name_ko": meta_sp.get("name_ko") or meta_sp.get("name_en") or f"#{spid}",
                "icon": meta_sp.get("icon") or "",
            })
        out["prepull"] = enriched_pp
    else:
        out["prepull"] = []

    # fight window
    meta = v2.meta.get(rid)
    if isinstance(meta, dict):
        for f in meta.get("fights") or []:
            if f.get("id") == fid:
                out["fight_window"] = [f.get("startTime"), f.get("endTime")]
                eid_ = f.get("encounterID")
                out["encounter_id"] = eid_
                # 한글 보스명 우선 — meta 캐시에 name 없는 (구버전 캐시) 도 대비
                out["encounter_name"] = (
                    BOSS_KR.get(int(eid_)) if isinstance(eid_, int) else None
                ) or f.get("name")
                break

    return JSONResponse(out)


# ── 타임라인 HTML (iframe srcdoc 으로 embed) ───────────────────────────────
_spell_db_cache: dict | None = None
_item_db_cache: dict | None = None


def _spell_db() -> dict:
    """spell_db.json 한 번만 로드. ~3MB, 약 4500 entries."""
    global _spell_db_cache
    if _spell_db_cache is None:
        path = DATA_DIR / "spell_db.json"
        if path.exists():
            _spell_db_cache = json.loads(path.read_text(encoding="utf-8"))
        else:
            _spell_db_cache = {}
    return _spell_db_cache


def _item_db() -> dict:
    """item_db.json 한 번만 로드. ~150KB, 923 entries."""
    global _item_db_cache
    if _item_db_cache is None:
        path = DATA_DIR / "item_db.json"
        if path.exists():
            _item_db_cache = json.loads(path.read_text(encoding="utf-8"))
        else:
            _item_db_cache = {}
    return _item_db_cache


# ── 한글 / rating 매핑 ─────────────────────────────────────────────────────
STAT_KR: dict[str, str] = {
    "Item Level": "장비레벨",
    "Stamina":    "체력",
    "Strength":   "힘",
    "Agility":    "민첩성",
    "Intellect":  "지능",
    "Crit":       "극대화",
    "Haste":      "가속",
    "Mastery":    "특화",
    "Versatility": "유연",
    "Leech":      "흡혈",
    "Avoidance":  "회피",
    "Speed":      "이동속도",
}

RATING_PER_PCT: dict[str, float] = {
    "Crit":        35.0,
    "Haste":       33.0,
    "Mastery":     35.0,
    "Versatility": 40.0,
    "Leech":       25.0,
    "Avoidance":   20.0,
    "Speed":       30.0,
}

SLOT_KR: dict[int, str] = {
    0: "머리",     1: "목",       2: "어깨",
    4: "가슴",     5: "허리",     6: "다리",     7: "발",
    8: "손목",     9: "손",
    10: "반지 1",  11: "반지 2",
    12: "장신구 1", 13: "장신구 2",
    14: "망토",
    15: "주무기",  16: "보조무기",
    17: "원거리",
}

# 한밤 raid (zone 46 = 꿈의 균열) 한글 보스명. 도감 검증된 7명 + 미확인 2명.
# memory/feedback_wow_kr_terms.md 의 권위 매핑.
BOSS_KR: dict[int, str] = {
    3176: "전제군주 아베르지안",
    3177: "보라시우스",
    3178: "바엘고어와 에조라크",
    3179: "몰락한 왕 살라다르",
    3180: "빛에 눈이 먼 선봉대",
    3181: "우주의 왕관",
    3182: "알라르의 자식 벨로렌",     # TODO 도감 검증
    3183: "한밤이 내린다",            # TODO 도감 검증
    3306: "꿈결을 벗어난 신 카이메루스",
}


@app.get("/api/timeline/{rid}/{fid}/{char}", response_class=HTMLResponse)
def timeline_html(rid: str, fid: int, char: str, orientation: str = "h") -> str:
    """캐스트/버프 + fight_window + spell_db → 완성된 HTML 문서.

    프론트엔드는 iframe.srcdoc 에 그대로 박아 넣음 (Qt WebView 와 동일 흐름).
    """
    v2 = _v2()
    pfight_key = f"{rid}:{fid}:{char}"
    if pfight_key not in v2.pfight:
        try:
            v2.player_fight(rid, fid, char)
        except Exception as e:
            raise HTTPException(502, f"player_fight 실패: {e}")
    ev = v2.events_for(rid, fid, char) or {}
    casts = ev.get("casts") or []
    buffs = ev.get("buffs") or []
    # 본인 sourceID (외부 버프 필터링용)
    pf = v2.pfight.get(pfight_key) or {}
    char_src = pf.get("sourceID") if isinstance(pf.get("sourceID"), int) else None
    # fight window
    meta = v2.meta.get(rid) or {}
    fw: list = []
    for f in meta.get("fights") or []:
        if f.get("id") == fid:
            fw = [f.get("startTime"), f.get("endTime")]
            break
    return tl_render.render_html(
        char=char, casts=casts, buffs=buffs,
        fight_window=fw, spell_db=_spell_db(),
        char_source_id=char_src,
        orientation=orientation,
    )


# ── 특성 트리 HTML (iframe srcdoc embed) ───────────────────────────────────
_talent_trees_cache: dict | None = None


def _talent_trees() -> dict:
    global _talent_trees_cache
    if _talent_trees_cache is None:
        path = DATA_DIR / "talent_trees.json"
        if path.exists():
            _talent_trees_cache = json.loads(path.read_text(encoding="utf-8"))
        else:
            _talent_trees_cache = {}
    return _talent_trees_cache


# (cls, spec) → spec 트리의 node_id set — talent_trees.json 의 spec 섹션만.
# class 트리 노드는 같은 클래스 내 spec 끼리 공유돼서 spec 구분 못 함.
# WCL combatantInfo.talentTree[].nodeID 와 매칭 (Blizzard node.id).
_spec_node_sets: dict[tuple[str, str], set[int]] | None = None


def _build_spec_node_sets() -> dict[tuple[str, str], set[int]]:
    """각 spec 트리의 spec+hero 섹션 node_id 집합 (class 섹션 제외)."""
    out: dict[tuple[str, str], set[int]] = {}
    for key, tree in _talent_trees().items():
        if "/" not in key:
            continue
        cls_, spec_ = key.split("/", 1)
        ids: set[int] = set()
        # spec 트리만 — class 트리는 모든 spec 가 공유라 변별 못함
        for n in (tree.get("spec") or []):
            nid = n.get("id")
            if isinstance(nid, int):
                ids.add(nid)
        for _, hdat in (tree.get("hero") or {}).items():
            for n in (hdat.get("nodes") or []):
                nid = n.get("id")
                if isinstance(nid, int):
                    ids.add(nid)
        out[(cls_, spec_)] = ids
    return out


def _infer_spec(picked_nodes: list) -> tuple[str | None, str | None]:
    """캐릭의 picked node IDs 와 가장 많이 매칭되는 (class, spec) 반환.

    pfight['nodes'] = WCL combatantInfo nodeID 리스트.
    talent_trees.json 의 5개 타깃 스펙 (Demo Lock, Balance Druid, BM Hunter,
    Arms War, Fury War) 만 매칭 가능. 매칭 부족 (강한 매칭 X) 시 (None, None).
    """
    global _spec_node_sets
    if _spec_node_sets is None:
        _spec_node_sets = _build_spec_node_sets()
    if not picked_nodes:
        return None, None
    picked = {n for n in picked_nodes if isinstance(n, int)}
    if not picked:
        return None, None
    # 점수: spec 의 node_id 중 picked 와 겹치는 개수. spec 사이즈로 정규화.
    best_key: tuple[str, str] | None = None
    best_ratio = 0.0
    for key, ids in _spec_node_sets.items():
        if not ids:
            continue
        n = len(picked & ids)
        # 임계: spec 노드의 최소 30% 이상 매칭 — 잘못된 추론 회피
        ratio = n / len(ids)
        if ratio > best_ratio and ratio >= 0.30:
            best_ratio = ratio
            best_key = key
    return (best_key[0], best_key[1]) if best_key else (None, None)


@app.get("/api/talent-tree-aggregate", response_class=HTMLResponse)
def talent_tree_aggregate(cls: str = "", spec: str = "",
                          encounter_id: int = 0,
                          difficulty: str = "heroic") -> str:
    """Top100 aggregate — 보스/스펙별 모든 캐릭의 pfight cache 에서 노드 픽 합산.

    rankings CSV 의 (rid, fid, char) 튜플 → pfight 조회 → 카운트.
    pfight cache 미스인 캐릭은 skip. denom = 캐시 매칭된 캐릭 수.
    """
    if not cls or not spec:
        return tt_render._empty("class/spec query 누락")
    key = f"{cls}/{spec}"
    trees = _talent_trees()
    tree_data = trees.get(key)
    if not tree_data:
        return tt_render._empty(f"트리 데이터 없음: {key}")

    # rankings CSV 필터
    fname = DIFFICULTY_FILES.get(difficulty)
    if not fname:
        return tt_render._empty(f"unknown difficulty: {difficulty}")
    path = DATA_DIR / fname
    if not path.exists():
        return tt_render._empty(f"CSV 없음: {fname}")
    df = pd.read_csv(path)
    mask = (df["class"] == cls) & (df["spec"] == spec)
    if encounter_id:
        mask = mask & (df["encounter_id"] == encounter_id)
    sub = df[mask]
    if sub.empty:
        return tt_render._empty(f"필터링 결과 없음: {cls}/{spec} boss={encounter_id}")

    # pfight cache 합산
    v2 = _v2()
    pick_count: dict[int, int] = {}
    pts_dist: dict[int, dict[int, int]] = {}
    matched = 0
    from collections import Counter
    for _, r in sub.iterrows():
        rid = str(r.get("report_id") or "")
        fid_raw = r.get("fight_id")
        char_nm = str(r.get("character") or "")
        if not rid or not char_nm:
            continue
        try:
            fid_int = int(fid_raw)
        except (TypeError, ValueError):
            continue
        pf = v2.pfight.get(f"{rid}:{fid_int}:{char_nm}")
        if not isinstance(pf, dict):
            continue
        nodes = pf.get("nodes") or []
        if not nodes:
            continue
        matched += 1
        per_node = Counter(int(n) for n in nodes if isinstance(n, int))
        for nid, rk in per_node.items():
            pick_count[nid] = pick_count.get(nid, 0) + 1
            d = pts_dist.setdefault(nid, {})
            d[rk] = d.get(rk, 0) + 1

    if matched == 0:
        return tt_render._empty(
            f"백필된 캐릭 0명 — {cls}/{spec} boss={encounter_id}\n"
            f"전체 {len(sub)} 명 중 pfight 캐시 매칭 0. backfill_v2.py 필요."
        )

    # hero_picks 합산
    hero_dict = tree_data.get("hero") or {}
    hero_tids: dict[str, set[int]] = {}
    for hn, hd in hero_dict.items():
        tids: set[int] = set()
        for n in hd.get("nodes") or []:
            for opt in n.get("options") or []:
                tid = opt.get("talent_id")
                if isinstance(tid, int):
                    tids.add(tid)
        hero_tids[hn] = tids
    hero_picks: dict[str, int] = {hn: 0 for hn in hero_dict}
    for _, r in sub.iterrows():
        rid = str(r.get("report_id") or "")
        try:
            fid_int = int(r.get("fight_id"))
        except (TypeError, ValueError):
            continue
        char_nm = str(r.get("character") or "")
        pf = v2.pfight.get(f"{rid}:{fid_int}:{char_nm}")
        if not isinstance(pf, dict):
            continue
        talents = set(t for t in (pf.get("talents") or []) if isinstance(t, int))
        if not talents:
            continue
        best_hn = None; best_n = 0
        for hn, tids in hero_tids.items():
            n = len(talents & tids)
            if n > best_n:
                best_n = n; best_hn = hn
        if best_hn:
            hero_picks[best_hn] += 1

    return tt_render.render_html(
        tree_data, pick_count, pts_dist, hero_picks,
        denom=matched, spell_db=_spell_db(), hero_filter=None,
    )


@app.get("/api/talent-tree/{rid}/{fid}/{char}", response_class=HTMLResponse)
def talent_tree_html(rid: str, fid: int, char: str,
                     cls: str = "", spec: str = "") -> str:
    """특정 캐릭의 특성 트리 — 본인 픽 노드만 100% 표시 (단일캐릭 view).

    cls/spec 은 ranking row 의 class/spec 를 query 로 전달.
    추후 ?mode=top100 으로 aggregate 모드 추가 예정.
    """
    if not cls or not spec:
        return tt_render._empty("class/spec query 누락")
    key = f"{cls}/{spec}"
    trees = _talent_trees()
    tree_data = trees.get(key)
    if not tree_data:
        return tt_render._empty(
            f"트리 데이터 없음: {key} — fetch_talent_trees.py SPECS 에 추가 필요"
        )

    v2 = _v2()
    pf = v2.pfight.get(f"{rid}:{fid}:{char}")
    if not isinstance(pf, dict):
        try:
            pf = v2.player_fight(rid, fid, char)
        except Exception as e:
            return tt_render._empty(f"player_fight 실패: {e}")
    if not isinstance(pf, dict):
        return tt_render._empty(f"{char} pfight 캐시 미스 + 재페치 실패")

    nodes_picked = pf.get("nodes") or []
    talent_points = pf.get("talent_points") or {}
    talent_ids_picked = pf.get("talents") or []

    # node_id 기반 pick_count (denom=1 → picked = 100%, unpicked = 0%)
    pick_count: dict[int, int] = {int(nid): 1 for nid in nodes_picked
                                  if isinstance(nid, int)}
    # pts_dist: {node_id: {rank: 1}} — 노드 → 랭크 매핑은 talent_id→node 관계가 필요한데
    # 단순화: talent_tree json 의 options[].talent_id 와 매칭
    pts_dist: dict[int, dict[int, int]] = {}
    # talent_id 의 rank → node_id 매핑
    for section in ("class", "spec"):
        for n in (tree_data.get(section) or []):
            nid = n.get("id")
            if not isinstance(nid, int):
                continue
            for opt in (n.get("options") or []):
                tid = opt.get("talent_id")
                if tid is not None and str(tid) in talent_points:
                    pts_dist.setdefault(nid, {})[talent_points[str(tid)]] = 1
                    break
    # hero 도 마찬가지
    for hname, hdat in (tree_data.get("hero") or {}).items():
        for n in (hdat.get("nodes") or []):
            nid = n.get("id")
            if not isinstance(nid, int):
                continue
            for opt in (n.get("options") or []):
                tid = opt.get("talent_id")
                if tid is not None and str(tid) in talent_points:
                    pts_dist.setdefault(nid, {})[talent_points[str(tid)]] = 1
                    break

    # hero_picks — 이 캐릭이 어느 영웅트리 뽑았는지 (가장 많이 매칭되는 hero)
    hero_picks: dict[str, int] = {}
    hero_filter: str | None = None
    for hname, hdat in (tree_data.get("hero") or {}).items():
        h_node_ids = {n.get("id") for n in (hdat.get("nodes") or [])
                      if isinstance(n.get("id"), int)}
        matched = sum(1 for nid in nodes_picked if nid in h_node_ids)
        hero_picks[hname] = matched
        if matched > 0:
            if hero_filter is None or matched > hero_picks.get(hero_filter, 0):
                hero_filter = hname

    return tt_render.render_html(
        tree_data, pick_count, pts_dist, hero_picks,
        denom=1, spell_db=_spell_db(), hero_filter=hero_filter,
    )


# ── V2 rate limit (디버깅용) ────────────────────────────────────────────────
@app.get("/api/rate")
def rate_left() -> JSONResponse:
    # WCLV2 client 에 points_left — V2Data 가 wrap.
    try:
        rate = _v2().cli.points_left()
    except Exception as e:
        return JSONResponse({"warning": f"rate query 실패: {e}"}, status_code=503)
    return JSONResponse(rate or {"warning": "rate info unavailable"})
