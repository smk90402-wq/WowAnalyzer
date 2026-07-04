"""spell_id → 스킬 아이콘 PNG + 이름·설명 툴팁 (wago.tools db2 CSV).

이벤트 피드 마우스 툴팁용 백엔드. wago 체인 (2026-07 실측):
  아이콘: SpellMisc filter[SpellID] → SpellIconFileDataID → api/casc BLP → PNG
  툴팁 : SpellName.Name_lang + Spell.Description_lang
         — db2 CSV 가 locale=koKR 을 지원해(실측 확인) 한국어 우선, 비면 기본(enUS).
설명의 달러 변수($s1, $134735s1, $d, 달러중괄호 수식)는 SpellEffect/SpellDuration
값으로 치환하고(못 구하면 빈칸), 색코드(|cff...|r)는 제거. 정리 후에도 $ 나 | 가
남으면 desc 는 빈 문자열 — 지저분한 설명은 노출하지 않는다.

캐시:
  data/spell_tips.json  spell_id → {icon_fdid, name, desc} 누적 (파일 하나, Lock)
  data/icons/{fdid}.png 아이콘 디스크 캐시 (같은 fdid 공유)
  실패는 10분 네거티브 캐시 (replay_map 패턴) — wago 재시도 폭주 방지.
"""
from __future__ import annotations

import csv
import io
import json
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

# UA 헤더/에러 처리·BLP 디코드(Pillow 네이티브)·DATA_DIR 규칙은 replay_map 재사용
from app.replay_map import DATA_DIR, WAGO, MapError, _get, _to_int

ICONS_DIR = DATA_DIR / "icons"
TIPS_PATH = DATA_DIR / "spell_tips.json"

# db2 CSV 는 build 미지정 시 어떤 빌드가 올지 보장이 없어 명시 (fetch_spell_cooldowns 와 동일).
# /api/builds 실패 시 폴백으로 쓰는 마지막 확인 라이브 빌드.
_FALLBACK_BUILD = "12.0.7.68367"

_FAIL_TTL_S = 600
# (종류 "icon"/"tip", spell_id) → (실패 시각 monotonic, 사유)
_fail_cache: dict[tuple[str, int], tuple[float, str]] = {}

_lock = threading.Lock()  # spell_tips.json 읽기-수정-쓰기 보호


class SpellTipError(RuntimeError):
    """툴팁/아이콘을 만들 수 없는 이유 — 404 사유로 그대로 노출."""


# ── wago db2 CSV ─────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _build() -> str:
    try:
        builds = json.loads(_get(f"{WAGO}/api/builds", timeout=30))
        return builds["wow"][0]["version"]
    except Exception:
        return _FALLBACK_BUILD


def _csv_rows(table: str, field: str, value: int, locale: str | None = None) -> list[dict[str, str]]:
    """filter 쿼리로 행 단위 조회. filter 는 부분일치(fuzzy)라 호출부 재필터 필수."""
    url = f"{WAGO}/db2/{table}/csv?build={_build()}&filter[{field}]={value}"
    if locale:
        url += f"&locale={locale}"
    text = _get(url, timeout=30).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _rows_exact(table: str, field: str, value: int, locale: str | None = None) -> list[dict[str, str]]:
    """fuzzy 응답을 정확히 재필터 + DifficultyID 0 행 우선 정렬."""
    rows = [r for r in _csv_rows(table, field, value, locale)
            if _to_int(r.get(field)) == value]
    rows.sort(key=lambda r: _to_int(r.get("DifficultyID")))
    return rows


# ── spell_tips.json 누적 캐시 ────────────────────────────────────────────────
def _cache_read_all() -> dict[str, Any]:
    try:
        data = json.loads(TIPS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _cache_get(spell_id: int) -> dict[str, Any]:
    with _lock:
        ent = _cache_read_all().get(str(spell_id))
        return dict(ent) if isinstance(ent, dict) else {}


def _cache_set(spell_id: int, **fields: Any) -> None:
    with _lock:
        data = _cache_read_all()
        ent = data.get(str(spell_id))
        if not isinstance(ent, dict):
            ent = {}
        ent.update(fields)
        data[str(spell_id)] = ent
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        TIPS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")


def _fail_check(kind: str, spell_id: int) -> None:
    failed = _fail_cache.get((kind, spell_id))
    if failed and time.monotonic() - failed[0] < _FAIL_TTL_S:
        raise SpellTipError(f"최근 실패 캐시(10분): {failed[1]}")


# ── db2 조회 헬퍼 (달러 변수 치환용 값 포함) ────────────────────────────────
@lru_cache(maxsize=512)
def _spell_misc(spell_id: int) -> dict[str, str]:
    rows = _rows_exact("SpellMisc", "SpellID", spell_id)
    if not rows:
        raise SpellTipError(f"SpellMisc 에 spellID {spell_id} 없음")
    return rows[0]


@lru_cache(maxsize=512)
def _spell_name(spell_id: int) -> str:
    """koKR 우선, 비면 기본(enUS). 행 자체가 없으면 빈 문자열."""
    for locale in ("koKR", None):
        rows = _rows_exact("SpellName", "ID", spell_id, locale)
        name = (rows[0].get("Name_lang") or "").strip() if rows else ""
        if name:
            return name
    return ""


@lru_cache(maxsize=512)
def _spell_desc_raw(spell_id: int) -> str:
    for locale in ("koKR", None):
        rows = _rows_exact("Spell", "ID", spell_id, locale)
        desc = (rows[0].get("Description_lang") or "").strip() if rows else ""
        if desc:
            return desc
    return ""


@lru_cache(maxsize=512)
def _effect_values(spell_id: int) -> dict[int, float]:
    """SpellEffect → {1-기반 EffectIndex: EffectBasePointsF} (DifficultyID 0 우선)."""
    out: dict[int, float] = {}
    for row in reversed(_rows_exact("SpellEffect", "SpellID", spell_id)):
        try:
            idx = int(row.get("EffectIndex") or 0) + 1
            out[idx] = float(row.get("EffectBasePointsF") or 0.0)
        except ValueError:
            continue
    return out


@lru_cache(maxsize=512)
def _duration_text(spell_id: int) -> str:
    """SpellMisc.DurationIndex → SpellDuration.Duration(ms) → '40초'/'10분'."""
    di = _to_int(_spell_misc(spell_id).get("DurationIndex"))
    if di <= 0:
        return ""
    rows = _rows_exact("SpellDuration", "ID", di)
    ms = _to_int(rows[0].get("Duration")) if rows else 0
    if ms <= 0:
        return ""
    if ms % 60000 == 0:
        return f"{ms // 60000}분"
    if ms >= 60000:
        return f"{ms // 60000}분 {_fmt_num(ms % 60000 / 1000)}초"
    return f"{_fmt_num(ms / 1000)}초"


def _fmt_num(v: float) -> str:
    """치환용 숫자: 절대값, 정수면 소수점 제거. 0 은 못 구한 것으로 보고 빈칸."""
    v = abs(v)
    if v == 0:
        return ""
    return str(int(v)) if v == int(v) else str(round(v, 2))


# ── 설명 정리 (달러 변수 → 숫자/빈칸) ───────────────────────────────────────
_RE_PIPE = re.compile(r"\|c[0-9a-fA-F]{8}|\|r|\|T[^|]*\|t")
_RE_COND = re.compile(r"\$\?!?\(?[\w|&!<>=.]*\)?\[([^\[\]]*)\]\[([^\[\]]*)\]")
_RE_SPELLDESC = re.compile(r"\$@spelldesc(\d+)")
_RE_SPELLNAME = re.compile(r"\$@spellname(\d+)")
_RE_GENDER = re.compile(r"\$[lLgG]([^:;\[\]\n]{0,60}):[^;\[\]\n]{0,60};")
_RE_MATH = re.compile(r"\$\{[^{}]*\}(?:\.\d+)?")
_RE_VAR = re.compile(r"\$(\d*)([sSmMdD])(\d+)?(?![A-Za-z])")
_RE_LEFTOVER = re.compile(r"\$\d*[A-Za-z]+\d*")


def _clean_desc(raw: str, spell_id: int, depth: int = 0,
                state: dict[str, bool] | None = None) -> str:
    """툴팁 원문 → 노출 가능한 평문. 정리 실패(잔여 $/|)면 빈 문자열.

    state 플래그 (호출부가 판단용으로 읽음):
      bad       — 값을 못 구해 빈칸이 된 변수가 있음 → 문장이 깨졌으니 노출 금지
      transient — wago 조회 예외로 못 구함 → 캐시하지 말고 다음에 재시도
    """
    state = state if state is not None else {}
    text = raw.replace("\r", "")  # CSV 가 \r\n 로 옴 — \n 로 통일

    # $@spelldesc123 (다른 스킬 설명 인라인 — 보스 기믹에 흔함, 1단계만 추적)
    def _inline_desc(m: re.Match[str]) -> str:
        if depth >= 1:
            state["bad"] = True   # 2단계 참조는 안 쫓음 — 내용이 통째로 빠짐
            return ""
        try:
            return _clean_desc(_spell_desc_raw(int(m.group(1))), int(m.group(1)),
                               depth + 1, state)
        except Exception:
            state["transient"] = True
            return ""
    text = _RE_SPELLDESC.sub(_inline_desc, text)

    def _inline_name(m: re.Match[str]) -> str:
        try:
            name = _spell_name(int(m.group(1)))
            if not name:
                state["bad"] = True
            return name
        except Exception:
            state["transient"] = True
            return ""
    text = _RE_SPELLNAME.sub(_inline_name, text)

    text = _RE_PIPE.sub("", text).replace("|n", " ")

    # $?조건[참][거짓] → 거짓(기본 상태) 분기. 중첩은 안쪽부터 반복 치환.
    for _ in range(20):
        new = _RE_COND.sub(lambda m: m.group(2), text)
        if new == text:
            break
        text = new

    text = _RE_GENDER.sub(lambda m: m.group(1), text)  # $l단수:복수; → 단수
    if _RE_MATH.search(text):
        state["bad"] = True   # ${수식} 은 계산 안 함 — 지우면 문장에 구멍
    text = _RE_MATH.sub("", text)

    # $s1/$m1(자기 값), $134735s1(참조 스킬 값), $d/$57724d(지속시간) → 숫자
    def _sub_var(m: re.Match[str]) -> str:
        ref = int(m.group(1)) if m.group(1) else spell_id
        letter = m.group(2).lower()
        try:
            if letter == "d":
                out = _duration_text(ref)
            else:
                idx = int(m.group(3)) if m.group(3) else 1
                out = _fmt_num(_effect_values(ref).get(idx, 0.0))
        except Exception:
            state["transient"] = True
            return ""
        if not out:
            state["bad"] = True   # 값이 0/없음 — "가속을 %만큼" 류 깨진 문장 방지
        return out
    text = _RE_VAR.sub(_sub_var, text)

    if _RE_LEFTOVER.search(text):
        state["bad"] = True   # $t1, $u 등 못 다루는 변수 — 지우면 문장에 구멍
    text = _RE_LEFTOVER.sub("", text)

    # 공백 정돈
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # 정리 후에도 $ 나 | 가 남으면 노출 금지
    if "$" in text or "|" in text:
        state["bad"] = True
        return ""
    return text


# ── 공개 API ─────────────────────────────────────────────────────────────────
def icon_png_path(spell_id: int) -> Path:
    """spell_id → data/icons/{fdid}.png (없으면 wago 에서 BLP 받아 변환)."""
    ent = _cache_get(spell_id)
    fdid = _to_int(ent.get("icon_fdid"))
    if fdid > 0:
        path = ICONS_DIR / f"{fdid}.png"
        if path.exists():
            return path
    _fail_check("icon", spell_id)
    try:
        if fdid <= 0:
            fdid = _to_int(_spell_misc(spell_id).get("SpellIconFileDataID"))
            if fdid <= 0:
                raise SpellTipError(f"spellID {spell_id} 아이콘 FileDataID 없음")
            _cache_set(spell_id, icon_fdid=fdid)
        path = ICONS_DIR / f"{fdid}.png"
        if not path.exists():
            from PIL import Image  # 지연 import — replay_map 과 동일 (Pillow BLP 네이티브)
            blp = _get(f"{WAGO}/api/casc/{fdid}")
            ICONS_DIR.mkdir(parents=True, exist_ok=True)
            # 임시 파일 → rename: 저장 중 끊겨도 깨진 PNG 가 캐시로 남지 않게
            tmp = path.with_suffix(".png.tmp")
            Image.open(io.BytesIO(blp)).convert("RGBA").save(tmp, format="PNG")
            tmp.replace(path)
        return path
    except Exception as exc:
        # PIL 디코드 실패(BLP 변종·잘린 응답)까지 전부 네거티브 캐시 —
        # hover 반복마다 wago 체인이 재발사되는 것 방지
        _fail_cache[("icon", spell_id)] = (time.monotonic(), str(exc))
        raise SpellTipError(str(exc))


def spell_tip(spell_id: int) -> dict[str, str]:
    """spell_id → {name, desc}. 이름이 아예 없으면 SpellTipError."""
    ent = _cache_get(spell_id)
    if isinstance(ent.get("name"), str) and isinstance(ent.get("desc"), str):
        return {"name": ent["name"], "desc": ent["desc"]}
    _fail_check("tip", spell_id)
    state: dict[str, bool] = {}
    try:
        name = _spell_name(spell_id)
        if not name:
            raise SpellTipError(f"SpellName 에 spellID {spell_id} 없음")
        raw = _spell_desc_raw(spell_id)
        desc = _clean_desc(raw, spell_id, state=state) if raw else ""
    except Exception as exc:
        _fail_cache[("tip", spell_id)] = (time.monotonic(), str(exc))
        raise SpellTipError(str(exc))
    if state.get("bad") or state.get("transient"):
        desc = ""   # 깨진 문장은 노출하지 않는다 (모듈 방침)
    if state.get("transient"):
        _cache_set(spell_id, name=name)   # 일시 장애 — desc 는 다음에 재시도
    else:
        _cache_set(spell_id, name=name, desc=desc)
    return {"name": name, "desc": desc}
