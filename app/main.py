"""FastAPI 앱 — 기존 wcl_v2_data + 캐시 + 랭킹 CSV 를 JSON API 로 노출.

엔드포인트:
  GET /api/ping                              — 헬스 체크
  GET /api/rankings/{difficulty}            — heroic|mythic top100 랭킹 (CSV → JSON)
  GET /api/report/{rid}                      — V2Data.report_meta(rid)
  GET /api/character/{rid}/{fid}/{char}     — pfight + casts + buffs + stats + prepull

기존 V2Data 싱글톤 그대로 사용. 디스크 캐시 / API 키 모두 wcl_v2_data 가 처리.
"""
from __future__ import annotations

import logging
from pathlib import Path

import json

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# 기존 백엔드 그대로 import
from wcl_v2_data import V2Data

from app import timeline as tl_render

log = logging.getLogger("app.main")

DATA_DIR = Path(__file__).parent.parent / "data"
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

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
    out: dict = {
        "rid": rid, "fid": fid, "char": char, "sourceID": sid,
        "talents": pf.get("talents") or [],
        "gear": pf.get("gear") or [],
        "stats": pf.get("stats") or None,
    }
    # casts + buffs — events_for 가 sid 매핑 + 페치 모두 처리
    ev = v2.events_for(rid, fid, char) or {}
    out["casts"] = ev.get("casts") or []
    out["buffs"] = ev.get("buffs") or []

    # prepull (별도 캐시) — sid 필요
    if sid is not None:
        prepull_key = f"{rid}:{fid}:{sid}"
        cached_pp = v2.prepull.get(prepull_key)
        if cached_pp is not None:
            out["prepull"] = cached_pp
        else:
            try:
                out["prepull"] = v2.pre_pull_buffs(rid, fid, char)
            except Exception as e:
                log.warning("prepull 실패: %s", e)
                out["prepull"] = []
    else:
        out["prepull"] = []

    # fight window
    meta = v2.meta.get(rid)
    if isinstance(meta, dict):
        for f in meta.get("fights") or []:
            if f.get("id") == fid:
                out["fight_window"] = [f.get("startTime"), f.get("endTime")]
                out["encounter_id"] = f.get("encounterID")
                out["encounter_name"] = f.get("name")
                break

    return JSONResponse(out)


# ── 타임라인 HTML (iframe srcdoc 으로 embed) ───────────────────────────────
_spell_db_cache: dict | None = None


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
        orientation=orientation,
    )


# ── V2 rate limit (디버깅용) ────────────────────────────────────────────────
@app.get("/api/rate")
def rate_left() -> JSONResponse:
    rate = _v2().points_left()
    return JSONResponse(rate or {"warning": "rate info unavailable"})
