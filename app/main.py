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
import re

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import auth


class CharIn(BaseModel):
    name: str
    server: str
    region: str = "kr"


class FrontLog(BaseModel):
    level: str = "info"   # debug / info / warn / error
    msg: str
    src: str = "fe"       # source (e.g., 'console.error', 'window.onerror')
    url: str | None = None
    line: int | None = None

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

# 인증 — 일시 비활성화 (사용자 요청 "로그인 일단 롤백"). 코드는 app/auth.py
# + app/admin.py 그대로 보존, 미들웨어/엔드포인트만 끔. 다시 켜고 싶으면
# 아래 블록 unindent / 미들웨어 함수 다시 활성화.
auth.init(DATA_DIR)  # users.db / auth_secret 은 그대로 둬도 무관

app = FastAPI(title="WowAnalyzer API", version="0.1.0")

# auth_gate 미들웨어 비활성화 — 모든 /api/* 가 인증 없이 통과.
# /auth/login, /auth/me 도 사용 안 함 (frontend 가 호출 안 함).

# static 파일 마운트 (Week 2 에서 HTML/CSS/JS 추가)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """루트 — SPA shell 바로 서빙 (인증 비활성)."""
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return idx.read_text(encoding="utf-8")
    return "<h1>index.html missing</h1>"

# V2Data 싱글톤 — 첫 요청 때 lazy 초기화 (API 키 / 캐시 로드)
_v2_inst: V2Data | None = None


def _v2() -> V2Data:
    global _v2_inst
    if _v2_inst is None:
        _v2_inst = V2Data(data_dir=DATA_DIR)
        # FastAPI 핸들러가 캐시를 변경해도 디스크에 저장되지 않으면 .exe 재시작 시 손실.
        # atexit 으로 우아한 종료 시 flush. pywebview 윈도우 닫기 → 메인 스레드 종료 시 호출됨.
        atexit.register(_v2_inst.flush)
        atexit.register(_save_cache_manifest)
    return _v2_inst


# ── 캐시 manifest — LFS push 회피 시 다른 PC 가 무얼 받아야 하는지 명시 ──
# v2_cache_*.json (대용량, LFS) 는 push 안 하더라도 이 파일 (작은 JSON) 은
# git 트래킹되어 다른 PC 에서 pull 받음. 그 PC 가 manifest 보고
# 본인 PC 의 캐시와 diff 비교 → 누락된 키 자동 페치 가능.
def _save_cache_manifest() -> None:
    if _v2_inst is None:
        return
    try:
        manifest = {
            "generated_at": __import__("time").time(),
            "host": __import__("socket").gethostname(),
            "pfight_keys": sorted(k for k, v in _v2_inst.pfight.items()
                                  if isinstance(v, dict)),
            "events_keys": sorted(k for k, v in _v2_inst.events.items()
                                  if isinstance(v, dict)),
            "report_meta_rids": sorted(_v2_inst.meta.keys()),
        }
        path = DATA_DIR / "cache_manifest.json"
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8")
        log.info("cache_manifest 저장: pfight=%d events=%d meta=%d",
                 len(manifest["pfight_keys"]), len(manifest["events_keys"]),
                 len(manifest["report_meta_rids"]))
    except Exception as e:
        log.warning("cache_manifest 저장 실패: %s", e)


# ── 헬스 ────────────────────────────────────────────────────────────────────
@app.get("/api/ping")
def ping() -> dict:
    return {"ok": True, "msg": "WowAnalyzer API live"}


# ── frontend 로그 → 백엔드 .log 파일 ────────────────────────────────────────
_fe_log = logging.getLogger("frontend")


@app.post("/api/log")
def fe_log(body: FrontLog) -> dict:
    """JS 에서 호출 — 에러/디버그 메시지를 백엔드 log 파일에 기록."""
    level = (body.level or "info").lower()
    fn = getattr(_fe_log, level, _fe_log.info)
    loc = f" @ {body.url}:{body.line}" if body.url else ""
    fn("[%s]%s %s", body.src, loc, body.msg)
    return {"ok": True}


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
    # 클래스/전문화 한글 컬럼 추가 (영문 class/spec 은 필터/트리 API 용으로 보존).
    if "class" in df.columns:
        df["class_kr"] = df["class"].map(CLASS_KR).fillna(df["class"])
    if "spec" in df.columns:
        df["spec_kr"] = df["spec"].map(SPEC_KR).fillna(df["spec"])
    # pandas to_json 이 NaN → null 변환 처리 (orient=records). 인덱스 미포함.
    rows_json = df.to_json(orient="records", force_ascii=False)
    payload = (
        f'{{"difficulty":"{difficulty}","row_count":{len(df)},"rows":{rows_json}}}'
    )
    return Response(content=payload, media_type="application/json")


# ── 스펙 메타 종합 (4차원 분석 표) ─────────────────────────────────────────
@app.get("/api/spec-meta")
def spec_meta() -> Response:
    """run_full_analysis 산출 spec_meta_ranking.csv + 로테 raw 메트릭 → JSON 표."""
    p = DATA_DIR / "spec_meta_ranking.csv"
    if not p.exists():
        raise HTTPException(404, "spec_meta_ranking.csv 없음 — run_full_analysis.py 실행 필요")
    df = pd.read_csv(p)  # spec_meta_ranking.csv 에 ease(커뮤니티)·rot_rank·로그메트릭 이미 포함
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", df.index + 1)
    df["class_kr"] = df["class"].map(CLASS_KR).fillna(df["class"])
    df["spec_kr"] = df["spec"].map(SPEC_KR).fillna(df["spec"])
    # 스킬천장 (가이드/아키타입 추정) inject
    df["skill_ceiling"] = df.apply(
        lambda r: SKILL_CEILING.get((r["class"], r["spec"]), (0, ""))[0], axis=1)
    df["skill_label"] = df["skill_ceiling"].map(SKILL_LABEL).fillna("?")
    df["skill_reason"] = df.apply(
        lambda r: SKILL_CEILING.get((r["class"], r["spec"]), (0, ""))[1], axis=1)
    # 실전 메타 강도 (파스 무관, raw DPS) inject
    df["raid_tier"] = df.apply(lambda r: RAID_TIER.get((r["class"], r["spec"]), "?"), axis=1)
    df["mplus_tier"] = df.apply(lambda r: MPLUS_TIER.get((r["class"], r["spec"]), "?"), axis=1)
    df["meta_note"] = df.apply(lambda r: META_NOTE.get((r["class"], r["spec"]), ""), axis=1)
    df["tuning"] = df.apply(lambda r: TUNING.get((r["class"], r["spec"]), ("", ""))[0], axis=1)
    df["tuning_note"] = df.apply(lambda r: TUNING.get((r["class"], r["spec"]), ("", ""))[1], axis=1)
    # 특임/유틸 부담 (1낮음~5높음, 높을수록 파스 불리) inject
    df["burden"] = df.apply(lambda r: UTILITY_BURDEN.get((r["class"], r["spec"]), (0, ""))[0], axis=1)
    df["burden_note"] = df.apply(lambda r: UTILITY_BURDEN.get((r["class"], r["spec"]), (0, ""))[1], axis=1)
    # 막공 환영도 (1기피~5최우선) inject — KR 취업 시장 실측 합성
    df["pug"] = df.apply(lambda r: PUG_WELCOME.get((r["class"], r["spec"]), (0, ""))[0], axis=1)
    df["pug_note"] = df.apply(lambda r: PUG_WELCOME.get((r["class"], r["spec"]), (0, ""))[1], axis=1)
    # KR 취업 시장 실측 수치 (kr_pug_market.json) — 팝업/툴팁용
    kp = DATA_DIR / "kr_pug_market.json"
    if kp.exists():
        import json as _json
        km = {(s["class"], s["spec"]): s for s in _json.loads(kp.read_text(encoding="utf-8"))["specs"]}
        def _km(r, k):
            return (km.get((r["class"], r["spec"])) or {}).get(k)
        df["pug_emp"] = df.apply(lambda r: _km(r, "employment"), axis=1)        # 취업률 = KR 신화유니크/영웅풀
        df["pug_emp_capped"] = df.apply(lambda r: _km(r, "heroic_capped"), axis=1)  # 영웅풀 캡 → 취업률 과대평가
        df["pug_to"] = df.apply(lambda r: _km(r, "slots_per_raid"), axis=1)     # 공대당 평균 자리수
        df["pug_present"] = df.apply(lambda r: _km(r, "p_present_pct"), axis=1) # 공대에 1명이상 있을 %
    else:
        df["pug_emp"] = None; df["pug_emp_capped"] = None
        df["pug_to"] = None; df["pug_present"] = None
    # 모집단(인구) → 파스 유리도 inject. 인구↑=깔아주는 뉴비 많아 평균이상 실력자 고파스 쉬움.
    # (WCL ranking 은 page20=2000 에서 하드캡 → 2000=상위인기, <2000=정확 인구.)
    pop_path = DATA_DIR / "spec_population.csv"
    if pop_path.exists():
        pop = pd.read_csv(pop_path)
        col = "pop_real" if "pop_real" in pop.columns else "pop_avg"
        pop = pop[["class", "spec", col, "pop_favor"]].rename(columns={col: "pop_avg"})
        # WCL CamelCase → CSV 공백형 정규화 후 머지
        pop["spec"] = pop["spec"].replace({"BeastMastery": "Beast Mastery"})
        pop["class"] = pop["class"].replace({"DemonHunter": "Demon Hunter", "DeathKnight": "Death Knight"})
        df = df.merge(pop, on=["class", "spec"], how="left")
    else:
        df["pop_avg"] = None
        df["pop_favor"] = None
    # 스펙 가이드(설명/로테/꿀팁) inject — 팝업 우측 패널용
    guide = _spellify(_spec_guide())
    df["guide_desc"] = df.apply(
        lambda r: (guide.get(f'{r["class"]}|{r["spec"]}') or {}).get("desc", ""), axis=1)
    df["guide_rotation"] = df.apply(
        lambda r: (guide.get(f'{r["class"]}|{r["spec"]}') or {}).get("rotation", ""), axis=1)
    df["guide_tips"] = df.apply(
        lambda r: (guide.get(f'{r["class"]}|{r["spec"]}') or {}).get("tips", []), axis=1)
    keep = ["rank", "kr", "class", "spec", "class_kr", "spec_kr", "score",
            "ease", "rot_rank", "pi_indep", "uplift_pct", "pi_rate_pct", "consistency",
            "raid_tier", "mplus_tier", "meta_note", "tuning", "tuning_note",
            "burden", "burden_note", "pug", "pug_note",
            "pug_emp", "pug_emp_capped", "pug_to", "pug_present", "pop_avg", "pop_favor",
            "guide_desc", "guide_rotation", "guide_tips",
            "aoe_ratio", "skill_ceiling", "skill_label", "skill_reason",
            "cleave_med", "unique_spells", "apm", "bigram_entropy"]
    keep = [c for c in keep if c in df.columns]
    rows_json = df[keep].to_json(orient="records", force_ascii=False)
    return Response(content=f'{{"row_count":{len(df)},"rows":{rows_json}}}',
                    media_type="application/json")


# ── 딜사이클 베이스 (로테이션 데이터) ────────────────────────────────────────
@app.get("/api/rotation")
def rotation_data() -> Response:
    """data/rotation_data.json 그대로 서빙 (클래스>전문화>빌드>단일/광/오프너).

    매 요청 재로드 → json 편집 즉시 반영. 사용자 후속 차별화 편집 용이.
    """
    p = DATA_DIR / "rotation_data.json"
    if not p.exists():
        raise HTTPException(404, "rotation_data.json 없음")
    data = _spellify(json.loads(p.read_text(encoding="utf-8")))
    return Response(content=json.dumps(data, ensure_ascii=False),
                    media_type="application/json")


_SPELL_TOKEN = re.compile(r"\{\{s:(\d+)(?::([^}]+))?\}\}")

def _spellify(obj):
    """{{s:ID}} / {{s:ID:표시명}} → 아이콘+한글명+wowhead 호버 툴팁 anchor (spell_db 기반).

    스펙 팝업/딜사이클 텍스트에서 스킬·패시브·버프를 텍스트 대신 아이콘+마우스오버로
    보여주기 위한 서버측 확장 (사용자 요청 2026-06-11). 프런트는 innerHTML 렌더라 그대로 작동,
    툴팁은 index.html 의 wowhead power.js 가 처리.
    """
    if isinstance(obj, dict):
        return {k: _spellify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_spellify(x) for x in obj]
    if not isinstance(obj, str):
        return obj
    db = _spell_db()
    def rep(m):
        sid, label = m.group(1), m.group(2)
        v = db.get(sid) or {}
        name = label or v.get("name_ko") or f"#{sid}"
        icon = (v.get("icon") or "inv_misc_questionmark.jpg").replace(".jpg", "")
        return (f'<a class="wh-spell" href="https://ko.wowhead.com/spell={sid}" '
                f'data-wowhead="spell={sid}&domain=ko" target="_blank" rel="noopener">'
                f'<img class="wh-ico" src="https://wow.zamimg.com/images/wow/icons/small/{icon}.jpg" '
                f'alt="" loading="lazy"><span>{name}</span></a>')
    return _SPELL_TOKEN.sub(rep, obj)


_SPELL_MAP_CACHE: str | None = None


@app.get("/api/spell-map")
def spell_map() -> Response:
    """한글 스킬명 → {id, icon} 맵 — 프런트 wsify()(스킬명 자동 아이콘+호버툴팁) 용.

    main.js ensureSpellMap() 이 기대하는 형태: {"map": {이름: {id, icon(.jpg 제외)}}}.
    같은 이름 여러 ID(랭크/변형)면 먼저 나온 것 유지. 1글자 이름은 오매칭 노이즈라 제외.
    """
    global _SPELL_MAP_CACHE
    if _SPELL_MAP_CACHE is None:
        m: dict[str, dict] = {}
        for sid, v in _spell_db().items():
            if not isinstance(v, dict):
                continue
            name = (v.get("name_ko") or "").strip()
            if len(name) < 2 or name in m:
                continue
            try:
                m[name] = {"id": int(sid), "icon": (v.get("icon") or "").replace(".jpg", "")}
            except ValueError:
                continue
        _SPELL_MAP_CACHE = json.dumps({"map": m}, ensure_ascii=False)
    return Response(content=_SPELL_MAP_CACHE, media_type="application/json")


_STAT_DR_CACHE: dict | None = None


def _stat_dr() -> dict:
    global _STAT_DR_CACHE
    if _STAT_DR_CACHE is None:
        p = DATA_DIR / "stat_dr.json"
        import json as _json
        _STAT_DR_CACHE = _json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _STAT_DR_CACHE


def _effective_pct(stat_kr: str, rating: int) -> float | None:
    """rating → 실효%(점감 적용). 한밤 DR 브래킷 누진.

    brk=[[1320,0.10],...]: 1320 은 -10% 구간의 *시작*. 즉 0~1320 무점감,
    1320~1760 에 -10%, 1760~2200 에 -20%... 각 구간의 rating 부분만 해당 페널티.
    (maxroll 검증: 가속 1320=30% 무점감, +264 → 35.4%)
    """
    dr = _stat_dr()
    per = dr.get("per_1pct", {}).get(stat_kr)
    brk = dr.get("brackets", {}).get(stat_kr)
    if not per or not brk or not rating:
        return None
    floor = brk[0][0]
    eff = min(rating, floor) * 1.0   # 0~첫경계: 무점감
    prev = floor
    for i in range(len(brk)):
        if rating <= prev:
            break
        penalty = brk[i][1]
        upper = brk[i + 1][0] if i + 1 < len(brk) else float("inf")
        seg = min(rating, upper) - prev
        if seg > 0:
            eff += seg * (1 - penalty)
        prev = upper
    return round(eff / per, 1)


@app.get("/api/stat-dr")
def stat_dr() -> Response:
    """한밤 2차스탯 점감(DR) 브래킷 — maxroll 출처. 스탯 탭 표시용."""
    return Response(content=__import__("json").dumps(_stat_dr(), ensure_ascii=False),
                    media_type="application/json")


@app.get("/api/boss-stats")
def boss_stats() -> Response:
    """data/boss_stats.json — 보스별 스탯 분포 (top1~20 개별 + 21~100 평균).

    같은 전문화도 광특/단일특 스탯이 다름(빌드별 분리). 한글 보스명 + 실효%(DR) inject.
    """
    p = DATA_DIR / "boss_stats.json"
    if not p.exists():
        raise HTTPException(404, "boss_stats.json 없음 — extract_boss_stats.py 실행 필요")
    import json as _json
    data = _json.loads(p.read_text(encoding="utf-8"))
    STATS = ["특화", "치명", "가속", "유연"]

    def add_eff(stats: dict) -> dict:
        return {k: _effective_pct(k, v) for k, v in stats.items()}

    for spec_key, bosses in data.items():
        for eid, d in bosses.items():
            d["boss_kr"] = BOSS_KR.get(int(eid), d.get("boss_kr", eid))
            for row in d.get("top", []):
                row["eff"] = add_eff(row.get("stats", {}))
            for blk in (d.get("top_avg") or []):
                blk["eff"] = add_eff(blk.get("stats", {}))
            for blk in (d.get("rest_avg") or []):
                blk["eff"] = add_eff(blk.get("stats", {}))
    return Response(content=_json.dumps({"data": data}, ensure_ascii=False),
                    media_type="application/json")


@app.get("/api/boss-dealcycle")
def boss_dealcycle() -> Response:
    """data/boss_dealcycle.json — 네임드별 실측 딜사이클 (top100 events 역산).

    오프너·쿨기 타이밍·블러드/물약 커버리지·버프 업타임·빌드 분기. 한글 보스명 inject.
    """
    p = DATA_DIR / "boss_dealcycle.json"
    if not p.exists():
        raise HTTPException(404, "boss_dealcycle.json 없음 — extract_boss_dealcycle.py 실행 필요")
    import json as _json
    data = _json.loads(p.read_text(encoding="utf-8"))
    # 보스명 한글화 (BOSS_KR)
    for spec_key, bosses in data.items():
        for eid, d in bosses.items():
            d["boss_kr"] = BOSS_KR.get(int(eid), d.get("boss_kr", eid))
    return Response(content=_json.dumps({"data": data}, ensure_ascii=False),
                    media_type="application/json")


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
@app.get("/api/gear/{rid}/{fid}/{char}")
def gear_only(rid: str, fid: int, char: str) -> JSONResponse:
    """장비창 전용 경량 엔드포인트 — player_fight 캐시에서 gear 만 (casts/buffs 안 건드림).

    character_detail 은 events 캐시 미스 시 WCL 페치로 느림(8초+). 장비창은 gear 만
    필요하므로 캐시 hit 이면 즉시(ms), 미스면 즉시 404 (WCL 페치 안 함).
    """
    pf = _v2().pfight.get(f"{rid}:{fid}:{char}")
    if not isinstance(pf, dict):
        raise HTTPException(404, f"{char} 장비 캐시 미스")
    item_db = _item_db()
    gear = []
    for g in (pf.get("gear") or []):
        if not isinstance(g, dict):
            continue
        iid = g.get("id")
        slot = g.get("slot") if isinstance(g.get("slot"), int) else -1
        meta = item_db.get(str(iid), {}) if isinstance(iid, int) else {}
        # 보석 enrich — gem ID 는 아이템 ID 라 item_db 에 이름·아이콘 있음
        gems = []
        for gem_id in (g.get("gems") or []):
            gm = item_db.get(str(gem_id), {})
            gems.append({"id": gem_id, "name_ko": gm.get("name_ko") or "",
                         "icon": gm.get("icon") or ""})
        gear.append({
            "slot": slot, "slot_kr": SLOT_KR.get(slot, f"슬롯 #{slot}"), "id": iid,
            "name_ko": meta.get("name_ko") or "", "icon": meta.get("icon") or "",
            "quality": meta.get("quality") or "", "ilvl": g.get("ilvl") or meta.get("ilvl"),
            "gems": gems, "ench": g.get("ench"),
        })
    gear.sort(key=lambda g: (g["slot"] if g["slot"] >= 0 else 999))
    return JSONResponse({"gear": gear})


@app.get("/api/character/{rid}/{fid}/{char}")
def character_detail(rid: str, fid: int, char: str, cache_only: int = 0) -> JSONResponse:
    """선택 캐릭의 talents/gear + casts/buffs + prepull buffs + stats.

    캐시 미스면 V2 GraphQL 호출 (수~십초). 캐시 hit 이면 ms 단위.
    cache_only=1 이면 캐시 미스 시 WCL 페치 안 하고 즉시 404 (장비창용 — 8초 행 방지).
    """
    v2 = _v2()
    pfight_key = f"{rid}:{fid}:{char}"
    if pfight_key not in v2.pfight:
        if cache_only:
            raise HTTPException(404, f"{char} 캐시에 없음 (cache_only)")
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
        "inferred_class_kr": CLASS_KR.get(inferred_cls or "", inferred_cls),
        "inferred_spec_kr": SPEC_KR.get(inferred_spec or "", inferred_spec),
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

    # 매 character fetch 후 manifest 자동 갱신 (force-kill 시 atexit 못 잡는
    # 케이스 대비 — 가장 자주 호출되는 endpoint).
    _save_cache_manifest()
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

# 한밤 raid (zone 46) 한글 보스명 — Blizzard journal-encounter ko_KR 전수 검증 (2026-05-30).
# WCL encounter_id → Blizzard journalID: 3176→2733 ... 3306→2795 (영문명 exact 매칭).
# 9개 전부 공식 API 값. 추측 아님. (스크립트: blizzard.py journal-encounter)
BOSS_KR: dict[int, str] = {
    3176: "전제군주 아베르지안",
    3177: "보라시우스",
    3178: "바엘고어와 에조라크",
    3179: "몰락한 왕 살라다르",
    3180: "빛에 눈이 먼 선봉대",
    3181: "우주의 왕관",
    3182: "알라르의 자손 벨로렌",
    3183: "한밤의 도래",
    3306: "꿈결을 벗어난 신 카이메루스",
}

# 클래스/전문화 공식 ko_KR — Blizzard playable-class/specialization 인덱스 (2026-05-30).
# WCL 영문명(공백 포함) → 한국 클라 공식명. 추측 아님 (Fury=분노, 격노 아님).
CLASS_KR: dict[str, str] = {
    "Death Knight": "죽음의 기사", "Demon Hunter": "악마사냥꾼",
    "Druid": "드루이드", "Evoker": "기원사", "Hunter": "사냥꾼",
    "Mage": "마법사", "Monk": "수도사", "Paladin": "성기사",
    "Priest": "사제", "Rogue": "도적", "Shaman": "주술사",
    "Warlock": "흑마법사", "Warrior": "전사",
}
SPEC_KR: dict[str, str] = {
    "Frost": "냉기", "Unholy": "부정", "Devourer": "포식", "Havoc": "파멸",
    "Balance": "조화", "Feral": "야성", "Augmentation": "증강",
    "Devastation": "황폐", "Beast Mastery": "야수", "Marksmanship": "사격",
    "Survival": "생존", "Arcane": "비전", "Fire": "화염", "Windwalker": "풍운",
    "Retribution": "징벌", "Shadow": "암흑", "Assassination": "암살",
    "Outlaw": "무법", "Subtlety": "잠행", "Elemental": "정기",
    "Enhancement": "고양", "Affliction": "고통", "Demonology": "악마",
    "Destruction": "파괴", "Arms": "무기", "Fury": "분노",
}

# 점수뽑기 스킬천장 (1=쉬움 ~ 5=매우어려움) — 로그 통계로 안 잡히는 최적화 난이도.
# 출처: 클래스 아키타입/커뮤니티 통념 + 사용자 제보(포식). **주관적 추정** (한밤 전용
# 가이드 미존재). 로테 난이도와 별개 — "이 스펙으로 고파스 뽑기가 얼마나 까다롭나".
SKILL_CEILING: dict[tuple[str, str], tuple[int, str]] = {
    ("Mage", "Frost"): (1, "정형적·변동 작음, 안정적으로 고파스"),
    ("Mage", "Fire"): (4, "연소 윈도우 + 점화 RNG로 변동 큼"),
    ("Mage", "Arcane"): (4, "마나/소각 페이즈 관리가 빡셈"),
    ("Warlock", "Demonology"): (2, "폭정 정렬만 맞추면 안정적"),
    ("Warlock", "Affliction"): (3, "다중 도트 갱신·악의의 마법 타이밍"),
    ("Warlock", "Destruction"): (2, "불씨 관리, 비교적 관대"),
    ("Demon Hunter", "Devourer"): (4, "붕괴하는 별 버스트 5~6회 + 기력관리 (사용자 제보)"),
    ("Demon Hunter", "Havoc"): (3, "탈태 윈도우 관리"),
    ("Druid", "Balance"): (3, "천체 에너지·일식 관리"),
    ("Druid", "Feral"): (5, "출혈 스냅샷·기력·도트 관리, 최상위 천장"),
    ("Hunter", "Beast Mastery"): (1, "이동 중 시전, 매우 관대"),
    ("Hunter", "Marksmanship"): (3, "정밀 사격·트릭샷 타이밍"),
    ("Hunter", "Survival"): (4, "근접 냥꾼, 복잡한 우선순위"),
    ("Monk", "Windwalker"): (4, "복잡한 우선순위·기 관리"),
    ("Paladin", "Retribution"): (2, "비교적 정형적"),
    ("Priest", "Shadow"): (4, "도트·정신력 관리"),
    ("Rogue", "Assassination"): (3, "출혈·기력 관리"),
    ("Rogue", "Outlaw"): (4, "한 방의 멋 굴림·즉흥 대응"),
    ("Rogue", "Subtlety"): (5, "그림자 춤 윈도우·심포니, 최난도"),
    ("Shaman", "Elemental"): (3, "소용돌이·정기 관리"),
    ("Shaman", "Enhancement"): (4, "소용돌이·복잡한 우선순위"),
    ("Evoker", "Augmentation"): (5, "지원 스펙·흑요석 정렬, 매우 복잡"),
    ("Evoker", "Devastation"): (3, "정수 관리"),
    ("Warrior", "Arms"): (3, "거인의 강타 윈도우 정렬"),
    ("Warrior", "Fury"): (2, "격노 유지, APM 높지만 관대"),
    ("Death Knight", "Unholy"): (3, "고름 상처 관리"),
    ("Death Knight", "Frost"): (3, "룬·룬마력 관리"),
}
SKILL_LABEL = {1: "쉬움", 2: "쉬움", 3: "중간", 4: "어려움", 5: "매우어려움"}

# ── 실전 메타 강도 (S~D) — **파스와 무관, raw DPS/실전 강함** ───────────────────
# 출처: 최신 유튜브(12.0.5, 밸패 후) — 레이드는 KDVow "kings dethroned" 상세 분석,
#   쐐기는 Marcelian/Flame 콤프 + Sky 전체 티어. 시즌 튜닝 따라 변함.
# raid/M+ 가 갈리는 스펙(냉기죽기·비전·생존 등)은 META_NOTE 로 표기.
RAID_TIER: dict[tuple[str, str], str] = {
    ("Warlock", "Demonology"): "S", ("Mage", "Frost"): "S", ("Hunter", "Survival"): "S",
    ("Death Knight", "Frost"): "S", ("Demon Hunter", "Devourer"): "S", ("Monk", "Windwalker"): "S",
    ("Evoker", "Augmentation"): "A", ("Druid", "Balance"): "A", ("Rogue", "Outlaw"): "A",
    ("Shaman", "Elemental"): "A", ("Paladin", "Retribution"): "A", ("Priest", "Shadow"): "A",
    ("Death Knight", "Unholy"): "A",
    ("Warlock", "Affliction"): "B", ("Warrior", "Arms"): "B", ("Warlock", "Destruction"): "B",
    ("Hunter", "Marksmanship"): "B", ("Evoker", "Devastation"): "B", ("Shaman", "Enhancement"): "B",
    ("Warrior", "Fury"): "B", ("Demon Hunter", "Havoc"): "B", ("Rogue", "Subtlety"): "B",
    ("Hunter", "Beast Mastery"): "B",
    ("Rogue", "Assassination"): "C", ("Mage", "Arcane"): "C", ("Mage", "Fire"): "C",
    ("Druid", "Feral"): "C",
}
# 쐐기 티어 = **mythicstats.com/dps 실측** (WCL API 기반 16~24키 평균딜, period 1065 week10).
# 유튜브 티어영상은 부정확 판명(냉마 S로 잘못 적었었음 → 실측 F) → 실측 데이터로 전면 교체.
# 사이트 6등급(S~F): S=1~2위, B=3~6, C=7~13, D=14~22, F=23~27 (avg DPS 6분할).
MPLUS_TIER: dict[tuple[str, str], str] = {
    ("Death Knight", "Unholy"): "S", ("Demon Hunter", "Devourer"): "S",
    ("Warlock", "Demonology"): "B", ("Evoker", "Augmentation"): "B",
    ("Paladin", "Retribution"): "B", ("Warrior", "Arms"): "B",
    ("Druid", "Feral"): "C", ("Rogue", "Outlaw"): "C", ("Hunter", "Survival"): "C",
    ("Rogue", "Assassination"): "C", ("Warlock", "Affliction"): "C",
    ("Rogue", "Subtlety"): "C", ("Hunter", "Beast Mastery"): "C",
    ("Warrior", "Fury"): "D", ("Shaman", "Enhancement"): "D", ("Mage", "Arcane"): "D",
    ("Monk", "Windwalker"): "D", ("Priest", "Shadow"): "D", ("Hunter", "Marksmanship"): "D",
    ("Demon Hunter", "Havoc"): "D", ("Death Knight", "Frost"): "D", ("Shaman", "Elemental"): "D",
    ("Mage", "Fire"): "F", ("Warlock", "Destruction"): "F", ("Mage", "Frost"): "F",
    ("Evoker", "Devastation"): "F", ("Druid", "Balance"): "F",
}
# ── 최근 튜닝 모멘텀 (PvE 순변동) — **공식 블리자드 핫픽스 시계열** ──────────
# 출처: Icy-Veins(=Wowhead 한글판과 동일 블리자드 원본) 튜닝 패스 3회 종합:
#   ① 한밤 레이드前(pre-raid) ② 5/5 대규모 ③ 5/28 신화後(post-mythic). 2026-06 리서치.
# 방향: ↑↑강한버프 ↑버프 →유지/혼재 ↓너프 ↓↓강한너프 (티어=현재강도 / 이건=추세).
TUNING: dict[tuple[str, str], tuple[str, str]] = {
    ("Warrior", "Arms"): ("↑↑", "3패스 연속 버프 (전체+15%·마무리+20%·압도+20%) — 급상승"),
    ("Warrior", "Fury"): ("↑↑", "전체+10%·+5%·마무리/학살자 버프 누적"),
    ("Priest", "Shadow"): ("↑↑", "전체+16% + 죽음의말+80%·환영+35% — 대폭 버프"),
    ("Rogue", "Subtlety"): ("↑↑", "기습/그림자칼+20%·전체+7% 누적"),
    ("Mage", "Arcane"): ("↑↑", "비전작렬+25%·권능의부담 대폭 — 5/28 추가버프"),
    ("Hunter", "Marksmanship"): ("↑↑", "신속+20%·폭발+100%·다중+30% 대폭"),
    ("Hunter", "Survival"): ("↑↑", "평타+35%·폭탄+80%·전체+4% 누적 — raid S 등극"),
    ("Hunter", "Beast Mastery"): ("↑↑", "날카로운+35%·코브라+100%·+4%×2 — 본캐, 계속 버프받는중"),
    ("Druid", "Balance"): ("↑↑", "전체+20%(세트너프 동반) — 큰 상향"),
    ("Warlock", "Affliction"): ("↑↑", "불안정+20%·부패+20%·고통+10% 부활버프"),
    ("Demon Hunter", "Havoc"): ("↑", "전체+6%·핵심기+10% — 데바스 대비 상향"),
    ("Rogue", "Outlaw"): ("↑", "전체+9% 버프"),
    ("Shaman", "Enhancement"): ("↑", "전체+8%·+5% 누적"),
    ("Druid", "Feral"): ("↑", "전체+6%·+3%(광기-8% 동반) — 순상향"),
    ("Paladin", "Retribution"): ("↑", "근접+25%·심판+25%(신성폭풍-12%·최후선고 조정) 순상향"),
    ("Shaman", "Elemental"): ("↑", "사슬/지진+10% 소폭"),
    ("Death Knight", "Frost"): ("↑", "+5%·+4% 버프 — raid S 유지"),
    ("Mage", "Fire"): ("→", "파이어볼/점화 버프 ↔ 점화확산 너프 — 혼재"),
    ("Warlock", "Destruction"): ("→", "혼돈의화살+35% ↔ 헬콜러 너프 — 혼재"),
    ("Rogue", "Assassination"): ("→", "큰 변동 없음 (소폭 버프만)"),
    ("Evoker", "Devastation"): ("↓", "대량분해 보너스 15→10% 너프"),
    ("Warlock", "Demonology"): ("↓", "악마 재조정·영혼수확자 대폭 너프"),
    ("Death Knight", "Unholy"): ("↓", "전체-20%(표적버프 동반)·마구스/기사 -15~25%"),
    ("Evoker", "Augmentation"): ("↓↓", "전체+13%였다가 세트 반토막·-5% — 너프 추세"),
    ("Demon Hunter", "Devourer"): ("↓↓", "전체-4%·-3%·섬멸자 너프 — 과튜닝 회수중"),
}

META_NOTE: dict[tuple[str, str], str] = {
    ("Death Knight", "Frost"): "레이드 S(보스딜 1위)↔쐐기 D(쿨기의존·단일약함) 극단 분리",
    ("Mage", "Frost"): "레이드 강함↔쐐기 F(실측 25위, mythicstats) — 레이드/쐐기 극단 분리",
    ("Hunter", "Survival"): "레이드 S(전체딜)↔쐐기 C(실측 9위)",
    ("Warlock", "Destruction"): "레이드 강함↔쐐기 F(실측 24위) — 단일 약함",
    ("Druid", "Balance"): "쐐기 F(실측 27위 최하위, mythicstats)",
    ("Evoker", "Devastation"): "쐐기 F(실측 26위) — 너프 후 추락",
    ("Hunter", "Beast Mastery"): "본인 본캐 — 레이드 B/쐐기 C(실측 13위). 단일 약함. 무빙자유라 특임차출 많음(파스 불리요인)",
}

# ── 특임/유틸 부담 (1낮음 ~ 5높음) — **파스 불리 요인** ──────────────────────
# 사용자 통찰: 상위 경쟁자는 '로그 몰아주기'(클리어팟이 특정 1명에게 딜 몰아주고 특임 면제)
# 가능하나, 일반 유저는 강제 특임을 본인이 맡음 → 그 시간 딜 손실 = 파스/일관성 직격.
# ★사용자 교정(중요)★: "이동 자유=편함"이 아니라 **"이동 자유=특임 차출 1순위"**.
#   무빙 자유로운 직업(특히 캐스팅없는 야냥)은 레이드가 "네가 가서 처리해"로 구슬소각·미끼·
#   원거리기믹·키팅을 다 떠맡김 (벨로렌 거북상 구슬특임이 정확한 예). → 부담 높음.
#   캐스터/터렛형(고정딜)이 오히려 "나 캐스팅중이라 못 감"으로 특임 빠지기 쉬움 = 부담 낮음.
# 부담 요소: 이동기믹 셔틀·소각/미끼·키팅·차단·해제·외생기 강제. 무빙+생존기 좋을수록 차출↑.
UTILITY_BURDEN: dict[tuple[str, str], tuple[int, str]] = {
    # 부담 낮음 (고정 캐스터·터렛형 — "캐스팅중"으로 특임 빠지기 쉬움 → 파스 유리)
    ("Warlock", "Destruction"): (2, "고정 캐스터, 관문 외엔 셔틀 차출 적음"),
    ("Warlock", "Demonology"): (2, "셋업형 고정딜, 특임 빠지기 쉬움"),
    ("Warlock", "Affliction"): (2, "도트 깔고 고정 — 자리 이탈 손해라 특임 면제 경향"),
    ("Mage", "Fire"): (2, "연소 윈도우 묶임 → 특임 차출 적음"),
    ("Mage", "Arcane"): (2, "버스트 셋업 묶임, 고정딜"),
    ("Priest", "Shadow"): (2, "도트+고정 채널, 무빙 약해 특임 잘 안 줌"),
    ("Evoker", "Devastation"): (2, "공명/시전 묶임 (25야드 제약)"),
    ("Mage", "Frost"): (3, "고정캐스터지만 블링크로 가끔 셔틀"),
    # 중간
    ("Hunter", "Marksmanship"): (3, "원거리지만 조준사격 캐스팅 묶임 — 야냥보단 덜 차출"),
    ("Warrior", "Arms"): (3, "돌진 기동 있어 셔틀 차출"),
    ("Warrior", "Fury"): (3, "돌진·기동기믹 차출"),
    ("Death Knight", "Unholy"): (3, "그립 쫄집결·AMZ 강제 유틸"),
    ("Death Knight", "Frost"): (3, "그립·AMZ 차출"),
    ("Rogue", "Assassination"): (3, "차단·해제독·기믹 관여"),
    ("Rogue", "Subtlety"): (3, "차단·기절·산개 셔틀"),
    ("Shaman", "Elemental"): (3, "정화·토템·이동기믹 차출"),
    ("Demon Hunter", "Devourer"): (3, "낙인·차단 관여 (메타 유지 묶임은 완화)"),
    # 높음 (무빙 자유·생존기 좋음 → 레이드가 이동기믹/소각/미끼/키팅 다 떠맡김 = 파스 불리)
    ("Hunter", "Beast Mastery"): (4, "★캐스팅0·100% 이동딜 = 레이드 이동기믹/구슬소각/미끼 차출 1순위 (벨로렌 거북상 구슬특임이 예). 본인 지적 반영 — 무빙자유=특임자석"),
    ("Hunter", "Survival"): (4, "근접+높은 기동, 미끼·차단·기믹 차출 잦음"),
    ("Demon Hunter", "Havoc"): (4, "최고 기동성 — 혼돈낙인·대규모차단·산개 단골 차출"),
    ("Monk", "Windwalker"): (4, "다리차기·고리·기믹 셔틀 단골 — 딜 끊김 잦음"),
    ("Rogue", "Outlaw"): (4, "기동 좋아 산개·셔틀 차출 잦음"),
    ("Druid", "Balance"): (4, "이동캐스팅+군중제어·미끼·키팅·전투부활 강제"),
    ("Druid", "Feral"): (4, "고기동 근접 — 키팅·미끼·전투부활·산개 단골"),
    ("Shaman", "Enhancement"): (4, "토템셔틀·대규모해제·키팅 차출 잦음"),
    ("Paladin", "Retribution"): (4, "축복(보호/희생)·외생기·해제 강제 — 유틸왕이라 딜 양보 잦음"),
    ("Evoker", "Augmentation"): (5, "버퍼라 본인딜<남딜 — 파스 개념 자체가 불리 (지원특화)"),
}

# ── 막공 환영도 (1기피 ~ 5최우선) — KR 취업 시장 실측 ──────────────────────
# ★사용자 교정(중요)★: "많이 보임 ≠ TO". 징벌은 정공마다 팔라 1자리 고정 × 인구 폭발이라
#   고유공대 수는 2위인데 실제 취업은 최악 → 공급(지원자) 대비 수요(자리)로 재측정 (v2).
# 방법 (전부 KR = 인벤 막공과 같은 시장, 2026-06 12.0.5):
#  · 취업률 = KR 신화 유니크 캐릭 ÷ KR 영웅 풀(우주의왕관+살라다르 — "영웅은 아무나 데려감"=지원자)
#  · TO = KR 신화 킬공대 1,316개 로스터 실측 공대당 평균 자리수 + 채용%(1명이상 보유 공대 비율)
#  · 클래스 동학 = 보유율("술사 없으면 정술이라도") + 슬롯 점유(징벌 940 vs 홀팔 782 경쟁)
#  · 취업률>1(고통 2.03·사격 1.44·냉죽·파괴) = 보스별 스왑 카드 — 본캐가 스펙만 바꾸는 것
#  · 인벤 공격대 모집글 315건 명시 모집 보조
# 핵심 실측: 징벌 취업률 0.672 하위6위(영웅풀 2097캡이라 실제 더 낮음)·팔라 보유율 95%로 필수
#  클래스도 아님 → 5에서 2로 교정. 술사 보유율 100%(전 공대 보유) → 정술 가점. 도적 보유율 55%.
#  등급은 3렌즈 독립채점+수석심판+적대검증 3명 (data/pug_welcome_analysis.json). 점수 미반영.
PUG_WELCOME: dict[tuple[str, str], tuple[int, str]] = {
    # 5 = 최우선 모심
    ("Mage", "Frost"): (5, "공대당 1.71자리 전 스펙 1위 · 채용 99% — 사실상 모든 공대가 냉법 한 자리를 깔고 감"),
    ("Warlock", "Demonology"): (5, "공대당 1.56자리 · 채용 91% + 흑마 보유율 100% + 인벤 5건 — 1~2자리 구조적 보장"),
    ("Death Knight", "Unholy"): (5, "공대당 1.37자리 · 채용 87% + 죽기 공대당 2.26명(클래스 1위) + 인벤 '죽딜' 8건"),
    ("Demon Hunter", "Devourer"): (5, "공대당 1.22자리 · 채용 89%(전 스펙 3위) — 악사 딜 슬롯 사실상 독점"),
    ("Evoker", "Augmentation"): (5, "인벤 명시 12건 압도적 1위 + 공대당 1.17자리 · 채용 80% — 기원사 슬롯 1,537개 독점"),
    # 4 = 환영
    ("Hunter", "Beast Mastery"): (4, "공대당 0.96자리 · 채용 69% + 사냥꾼 보유율 99% — 본캐. 원딜 우대 시장에서 자리 흔함"),
    ("Hunter", "Marksmanship"): (4, "자체 0.58자리·채용 45% + 취업률 1.44(보스별 스왑 카드 가치) + 야수 전환 유연성"),
    ("Shaman", "Elemental"): (4, "0.74자리 · 채용 67% + 인벤 6건 + 술사 보유율 100%의 유일 현실 딜스펙 — '술사 없으면 정술이라도' 가점"),
    ("Rogue", "Subtlety"): (4, "취업률 0.865(비스왑 상위권) · 0.47자리 — 도적 유일 메타 스펙, 인벤 '도적' 5건이 향하는 곳"),
    # 3 = 무난
    ("Warlock", "Destruction"): (3, "전임 0.28자리·채용 22%지만 취업률 1.05 스왑 카드 + 흑마 보유율 100%가 받쳐줌"),
    ("Warlock", "Affliction"): (3, "전임 0.08자리뿐이나 취업률 2.03 전 스펙 1위 보스 스왑 카드 — 악마 겸업 전제로 자리 구함"),
    ("Death Knight", "Frost"): (3, "전임 0.16자리·채용 16% + 취업률 1.05 스왑 카드 + 죽기 클래스 수요(공대당 2.26명)"),
    ("Priest", "Shadow"): (3, "0.44자리 · 채용 42% — 공대 10곳 중 4곳에 자리 있는 중위권 + 사제 유일 딜스펙 안전망"),
    ("Druid", "Balance"): (3, "0.57자리 · 채용 52% — 공대 절반에 자리 + 드루 보유율 100% 안전망"),
    ("Warrior", "Fury"): (3, "0.49자리 · 채용 46% — 전사(보유율 99%) 주력 딜스펙의 무난한 중위권"),
    # 2 = 찬밥
    ("Paladin", "Retribution"): (2, "★취업률 0.672 하위6위(영웅풀 2097캡→실제 더 낮음) — 공급과잉. 팔라 보유율 95%로 필수클래스 아니고 홀팔(782슬롯)과 한 자리 경쟁. 본인 증언대로 인구 대비 TO 최악"),
    ("Hunter", "Survival"): (2, "0.20자리 · 채용 20% — 사냥꾼 딜 슬롯이 야수(0.96)·사격(0.58) 원딜에 쏠림"),
    ("Warrior", "Arms"): (2, "0.29자리 · 채용 28% — 같은 전사에서도 분노(639슬롯 vs 무기 379)에 밀리는 뒷순위"),
    ("Monk", "Windwalker"): (2, "0.32자리 · 채용 31% — 수도사 슬롯이 운무(1,101)·양조(569)에 쏠림, 풍운 427"),
    ("Demon Hunter", "Havoc"): (2, "0.16자리 · 채용 15% — 악사 딜 자리를 포식(1.22)이 다 가져가 스왑 압박"),
    ("Shaman", "Enhancement"): (2, "0.08자리 · 채용 8% — 술사 딜 슬롯을 정술(979 vs 고양 101)이 독식, 러스트 가치 무효"),
    ("Rogue", "Assassination"): (2, "0.06자리 · 채용 6% + 도적 보유율 55%라 클래스 안전망 없음 — 잠행 스왑이 입장권"),
    # 1 = 기피
    ("Mage", "Fire"): (1, "0.04자리 · 채용 3% — 법사 슬롯을 냉법(1.71)이 독식, 화염 본캐 자리는 사실상 없음"),
    ("Mage", "Arcane"): (1, "취업률 0.466 · 0.01자리 · 채용 1% · KR 신화 유니크 27명 — 전 지표 27위 꼴찌"),
    ("Druid", "Feral"): (1, "취업률 0.565(26위) · 0.08자리 — 드루 좌석이 조화(765슬롯)·힐·탱에 다 넘어감"),
    ("Rogue", "Outlaw"): (1, "0.05자리 · 채용 5% + 도적 보유율 55% — '없으면 데려간다' 안전망조차 없음"),
    ("Evoker", "Devastation"): (1, "0.03자리 · 채용 3%(46슬롯) — 기원사 좌석을 증강(1,537)·보존(539)이 차지, 증강 전환 요구받음"),
}


def _spec_guide() -> dict:
    """스펙별 팝업 가이드(설명/로테/꿀팁) — data/spec_guide.json. 매 요청 재로드(편집 즉시반영)."""
    p = DATA_DIR / "spec_guide.json"
    if not p.exists():
        return {}
    try:
        import json as _json
        return _json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


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


# ── 사용자 등록 캐릭터 (per-PC, gitignored) ────────────────────────────────
CHARS_FILE = DATA_DIR / "user_characters.json"


def _load_chars() -> list:
    if CHARS_FILE.exists():
        try:
            d = json.loads(CHARS_FILE.read_text(encoding="utf-8"))
            return d if isinstance(d, list) else []
        except Exception:
            return []
    return []


def _save_chars(chars: list) -> None:
    CHARS_FILE.write_text(
        json.dumps(chars, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/api/characters")
def chars_list() -> JSONResponse:
    """등록된 캐릭터 목록 — name, server (slug), region."""
    return JSONResponse(_load_chars())


@app.post("/api/characters")
def chars_add(body: CharIn) -> JSONResponse:
    """{name, server, region} 추가."""
    name = body.name.strip()
    server = body.server.strip().lower()
    region = body.region.strip().lower() or "kr"
    if not name or not server:
        raise HTTPException(400, "name + server 필수")
    chars = _load_chars()
    for c in chars:
        if (c.get("name") == name and c.get("server") == server
                and c.get("region") == region):
            raise HTTPException(409, "이미 등록됨")
    chars.append({"name": name, "server": server, "region": region})
    _save_chars(chars)
    return JSONResponse({"ok": True, "count": len(chars)})


@app.delete("/api/characters/{name}")
def chars_delete(name: str, server: str = "", region: str = "kr") -> JSONResponse:
    chars = _load_chars()
    new = [c for c in chars
           if not (c.get("name") == name
                   and (not server or c.get("server") == server)
                   and (not region or c.get("region") == region))]
    if len(new) == len(chars):
        raise HTTPException(404, f"{name} (server={server}) 못 찾음")
    _save_chars(new)
    return JSONResponse({"ok": True, "count": len(new)})


# WCL V2 characterData 쿼리 — recent reports 조회
Q_CHAR_REPORTS = """
query($name: String!, $server: String!, $region: String!, $limit: Int!) {
  characterData {
    character(name: $name, serverSlug: $server, serverRegion: $region) {
      id
      name
      recentReports(limit: $limit) {
        data {
          code
          title
          startTime
          endTime
          zone { id name }
          owner { name }
        }
      }
    }
  }
}
"""


@app.get("/api/character-reports")
def character_reports(name: str, server: str, region: str = "kr",
                      limit: int = 15) -> JSONResponse:
    """등록 캐릭의 WCL 최근 리포트 N개. (rid, title, 시각, 존)."""
    v2 = _v2()
    try:
        d = v2.cli.query(Q_CHAR_REPORTS, {
            "name": name, "server": server.lower(),
            "region": region.lower(), "limit": int(limit),
        })
    except Exception as e:
        raise HTTPException(502, f"WCL char query 실패: {e}")
    ch = (((d or {}).get("characterData") or {}).get("character") or {})
    if not ch:
        raise HTTPException(404,
            f"WCL 에 캐릭 없음: {name} @ {server} ({region}). "
            f"서버 slug (영문 소문자, 띄어쓰기 없이) 확인.")
    reports = ((ch.get("recentReports") or {}).get("data") or [])
    return JSONResponse({
        "char_id": ch.get("id"),
        "name": ch.get("name"),
        "reports": [
            {
                "code": r.get("code"),
                "title": r.get("title") or "",
                "startTime": r.get("startTime"),
                "endTime": r.get("endTime"),
                "zone_id": ((r.get("zone") or {}).get("id")),
                "zone_name": ((r.get("zone") or {}).get("name") or ""),
                "owner": ((r.get("owner") or {}).get("name") or ""),
            }
            for r in reports
        ],
    })
