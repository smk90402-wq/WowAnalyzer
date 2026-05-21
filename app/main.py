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

log = logging.getLogger("app.main")

DATA_DIR = Path(__file__).parent.parent / "data"
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI(title="WowAnalyzer API", version="0.1.0")

# static 파일 마운트 (Week 2 에서 HTML/CSS/JS 추가)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """루트 — Week 1 stub. Week 2 부터 실제 SPA shell 로 교체."""
    return """<!doctype html><html><head><meta charset="utf-8">
<title>WowAnalyzer (web)</title>
<style>
  body { background:#1a1614; color:#f5f0e8; font-family:'Segoe UI',sans-serif;
         padding:40px; line-height:1.6; }
  h1 { color:#d97757; margin-bottom:6px; }
  code { background:#221d1a; padding:2px 6px; border-radius:3px; color:#e6c190; }
  .note { color:#a39c8e; margin-top:12px; }
  a { color:#9bb5e0; }
</style></head><body>
<h1>WowAnalyzer (web migration)</h1>
<p>Week 1 — FastAPI 백엔드 wrap 완료. 프론트엔드는 Week 2 부터 작성 중.</p>
<p class="note">테스트 엔드포인트:</p>
<ul>
  <li><a href="/api/ping">/api/ping</a></li>
  <li><a href="/api/rankings/heroic">/api/rankings/heroic</a> (24300 rows)</li>
  <li><a href="/api/rankings/mythic">/api/rankings/mythic</a></li>
  <li><a href="/api/rate">/api/rate</a> (V2 rate limit)</li>
  <li>POST 형식: <code>/api/character/{rid}/{fid}/{char}</code></li>
</ul>
<p class="note">기존 LogAnalyze.exe (PySide6) 그대로 살아있음. 두 UI 가 같은 캐시 / 같은 V2Data 사용.</p>
</body></html>"""

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


# ── V2 rate limit (디버깅용) ────────────────────────────────────────────────
@app.get("/api/rate")
def rate_left() -> JSONResponse:
    rate = _v2().points_left()
    return JSONResponse(rate or {"warning": "rate info unavailable"})
