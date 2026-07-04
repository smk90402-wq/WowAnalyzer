"""spell_id → 스킬 아이콘 PNG + 이름·설명 툴팁 (wago.tools db2 CSV).

이벤트 피드 마우스 툴팁용 백엔드. wago 체인 (2026-07 실측):
  아이콘: SpellMisc filter[SpellID] → SpellIconFileDataID → api/casc BLP → PNG
  툴팁 : SpellName.Name_lang + Spell.Description_lang
         — db2 CSV 가 locale=koKR 을 지원해(실측 확인) 한국어 우선, 비면 기본(enUS).
설명의 달러 변수($s1, $134735s1, $d, 달러중괄호 수식)는 SpellEffect/SpellDuration
값으로 치환하고(못 구하면 빈칸), 색코드(|cff...|r)는 제거. 정리 후에도 $ 나 | 가
남으면 desc 는 빈 문자열 — 지저분한 설명은 노출하지 않는다.

폴백 (원 체인이 빈손일 때만, 2026-07 실측 — 르우라/카이메루스 기믹):
  설명 : 던전 저널 JournalEncounterSection filter[SpellID] 의 BodyText_lang.
         해당 ID 가 0행이면 SpellName 역조회로 동명 spell_id 들을 재시도(보스 기믹은
         cast/hit/damage 가 다른 ID·저널엔 대표 ID 하나). 기믹 행 BodyText 가 비면
         같은 인카운터 공략(Type=3) 섹션의 $bullet; 항목 중 해당 스킬 링크가 든 줄.
         난이도 분기($[!15,16 …$])는 신화(16) 포함 분기만 유지.
  아이콘: SpellMisc 에 행이 없으면 동명 spell_id 들의 SpellMisc 에서 첫 아이콘.

캐시:
  data/spell_tips.json  spell_id → {v, icon_fdid, name, desc} 누적 (파일 하나, Lock)
      v 가 CACHE_V 와 다르면 desc 재계산(옛 로직이 저장한 깨진/빈 desc 무효화).
      name 과 icon_fdid 는 버전 무관 유효 — 재사용.
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
from urllib.parse import quote

# UA 헤더/에러 처리·BLP 디코드(Pillow 네이티브)·DATA_DIR 규칙은 replay_map 재사용
from app.replay_map import DATA_DIR, WAGO, MapError, _get, _to_int

ICONS_DIR = DATA_DIR / "icons"
TIPS_PATH = DATA_DIR / "spell_tips.json"

# db2 CSV 는 build 미지정 시 어떤 빌드가 올지 보장이 없어 명시 (fetch_spell_cooldowns 와 동일).
# /api/builds 실패 시 폴백으로 쓰는 마지막 확인 라이브 빌드.
_FALLBACK_BUILD = "12.0.7.68367"

# spell_tips.json 엔트리 버전 — desc 계산 로직이 바뀌면 올린다.
# v 가 다른(없는) 엔트리는 desc 를 다시 계산 (name/icon_fdid 는 그대로 유효).
CACHE_V = 3   # v2: 저널 폴백이 공략 불릿만 봐서 산문 문단 기믹이 빈 desc 로 저장됨

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


def _csv_rows(table: str, field: str, value: int | str,
              locale: str | None = None) -> list[dict[str, str]]:
    """filter 쿼리로 행 단위 조회. filter 는 부분일치(fuzzy)라 호출부 재필터 필수."""
    url = f"{WAGO}/db2/{table}/csv?build={_build()}&filter[{field}]={quote(str(value))}"
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


# ── 폴백: 동명 spell_id 역조회 + 던전 저널 ──────────────────────────────────
@lru_cache(maxsize=256)
def _sibling_ids(name: str) -> tuple[int, ...]:
    """SpellName 을 이름으로 역조회(정확 일치 재필터) — 동명 spell_id 전체, 오름차순."""
    for locale in ("koKR", None):
        rows = _csv_rows("SpellName", "Name_lang", name, locale)
        ids = sorted({_to_int(r.get("ID")) for r in rows
                      if (r.get("Name_lang") or "") == name and _to_int(r.get("ID")) > 0})
        if ids:
            return tuple(ids)
    return ()


def _near_siblings(name: str, spell_id: int, limit: int = 8) -> list[int]:
    """동명 spell_id 중 자기와 ID 가 가까운 순 상위 N — 보스 기믹의 cast/hit/damage
    변형은 ID 가 이웃해 있다. 오름차순 앞자르기는 흔한 이름('돌진' 317개)에서
    옛 확장팩 ID 만 남아 현행 레이드 스펠이 무조건 탈락하므로 근접순이 맞다."""
    ids = [i for i in _sibling_ids(name) if i != spell_id]
    ids.sort(key=lambda i: abs(i - spell_id))
    return ids[:limit]


@lru_cache(maxsize=512)
def _journal_rows_for(spell_id: int) -> list[dict[str, str]]:
    """JournalEncounterSection 에서 SpellID 로 기믹 섹션 행들."""
    for locale in ("koKR", None):
        rows = _rows_exact("JournalEncounterSection", "SpellID", spell_id, locale)
        if rows:
            return rows
    return []


@lru_cache(maxsize=64)
def _journal_enc_rows(enc_id: int) -> list[dict[str, str]]:
    """인카운터 하나의 저널 섹션 전체 (공략 Type=3 포함)."""
    for locale in ("koKR", None):
        rows = _rows_exact("JournalEncounterSection", "JournalEncounterID", enc_id, locale)
        if rows:
            return rows
    return []


# $[!15,16 …$] 난이도 분기 / |Hspell:123|h[이름]|h 링크 — 저널 BodyText 전용 토큰
_RE_J_COND = re.compile(r"\$\[\s*!?([\d,]*)\s*(.*?)\$\]", re.S)
_RE_J_LINK = re.compile(r"\|H[^|]*\|h\[?([^|]*?)\]?\|h")


def _journal_pre(text: str) -> str:
    """저널 토큰 정리 — 난이도 분기는 신화(16) 포함 분기만 유지. 나머지는 _clean_desc."""
    def _cond(m: re.Match[str]) -> str:
        ids = {x.strip() for x in m.group(1).split(",") if x.strip()}
        return m.group(2) if (not ids or "16" in ids) else ""
    text = _RE_J_COND.sub(_cond, text)
    text = _RE_J_LINK.sub(lambda m: m.group(1), text)
    return text.replace("$bullet;", "\n")


def _pick_body(rows: list[dict[str, str]]) -> str:
    """기믹 섹션 행들의 BodyText 중 하나 — 여럿이면 신화(16) 난이도 행 우선."""
    cands: list[tuple[int, str]] = []
    for r in rows:
        body = (r.get("BodyText_lang") or "").strip()
        if body and all(body != b for _, b in cands):
            cands.append((_to_int(r.get("ID")), body))
    if len(cands) > 1:
        for sec_id, body in cands:
            diffs = _rows_exact("JournalSectionXDifficulty", "JournalEncounterSectionID", sec_id)
            if any(_to_int(d.get("DifficultyID")) == 16 for d in diffs):
                return body
    return cands[0][1] if cands else ""


def _overview_body(enc_id: int, spell_ids: set[int]) -> str:
    """공략(Type=3) 섹션에서 해당 스킬 링크가 든 조각들 (중복 제거).

    $bullet; 항목 우선, 없으면 산문 문단(빈 줄 구분)도 후보 — 이 레이드 저널은
    기믹 설명이 불릿에만 있는 보스와 산문에만 있는 보스가 섞여 있다(실측).
    """
    if enc_id <= 0:
        return ""
    marks = [f"spell:{sid}|h" for sid in spell_ids if sid > 0]
    lines: list[str] = []
    for r in _journal_enc_rows(enc_id):
        if (r.get("Type") or "").strip() != "3":
            continue
        body = r.get("BodyText_lang") or ""
        for part in body.split("$bullet;")[1:]:
            part = part.strip()
            if part and any(m in part for m in marks) and part not in lines:
                lines.append(part)
        for part in re.split(r"(?:\r?\n){2,}", body):
            part = part.strip()
            if not part or "$bullet;" in part:
                continue   # 불릿 포함 문단은 위에서 항목 단위로 이미 처리
            if any(m in part for m in marks) and part not in lines:
                lines.append(part)
    return "\n".join(lines)


def _journal_desc(spell_id: int, name: str, state: dict[str, bool]) -> str:
    """던전 저널 폴백 desc. 실패/빈 결과는 "" — 조회 예외는 transient 로만 표시."""
    try:
        rows = _journal_rows_for(spell_id)
        if not rows:
            # 저널엔 기믹당 대표 spell_id 하나 — 동명·근접 ID 로 재시도 (최대 8개)
            for sib in _near_siblings(name, spell_id):
                rows = _journal_rows_for(sib)
                if rows:
                    break
        if not rows:
            return ""
        rep_id = _to_int(rows[0].get("SpellID"))
        enc_id = _to_int(rows[0].get("JournalEncounterID"))
        # 1순위: 기믹 행 자체 BodyText — 비어 있으면 공략 불릿 (이 레이드 저널의 실태)
        for body in (_pick_body(rows), _overview_body(enc_id, {spell_id, rep_id})):
            if not body:
                continue
            st: dict[str, bool] = {}
            text = _clean_desc(_journal_pre(body), spell_id, state=st)
            if st.get("transient"):
                state["transient"] = True
            if text and not st.get("bad"):
                return text
        return ""
    except Exception:
        state["transient"] = True   # 저널 체인 조회 실패 — 캐시하지 말고 다음에 재시도
        return ""


def _icon_fdid(spell_id: int) -> int:
    """SpellMisc 아이콘 FileDataID. 없으면 동명 spell_id 들의 SpellMisc 에서 첫 아이콘."""
    try:
        fdid = _to_int(_spell_misc(spell_id).get("SpellIconFileDataID"))
    except SpellTipError:
        fdid = 0
    if fdid > 0:
        return fdid
    name = _spell_name(spell_id)
    for sib in (_near_siblings(name, spell_id) if name else []):
        try:
            fdid = _to_int(_spell_misc(sib).get("SpellIconFileDataID"))
        except SpellTipError:
            continue
        if fdid > 0:
            return fdid
    raise SpellTipError(f"spellID {spell_id} 아이콘 FileDataID 없음(동명 폴백 포함)")


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
            fdid = _icon_fdid(spell_id)   # 원 체인 실패 시 동명 폴백 포함
            _cache_set(spell_id, icon_fdid=fdid)
        path = ICONS_DIR / f"{fdid}.png"
        if not path.exists():
            from PIL import Image  # 지연 import — replay_map 과 동일 (Pillow BLP 네이티브)
            blp = _get(f"{WAGO}/api/casc/{fdid}")
            ICONS_DIR.mkdir(parents=True, exist_ok=True)
            # 임시 파일 → rename: 저장 중 끊겨도 깨진 PNG 가 캐시로 남지 않게.
            # 스레드별 이름 — 같은 fdid 를 공유하는 스킬 둘을 동시에 hover 해도 충돌 없음
            tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
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
    if (_to_int(ent.get("v")) == CACHE_V
            and isinstance(ent.get("name"), str) and isinstance(ent.get("desc"), str)):
        return {"name": ent["name"], "desc": ent["desc"]}
    _fail_check("tip", spell_id)
    state: dict[str, bool] = {}
    try:
        cached = ent.get("name")   # 옛 버전 엔트리라도 이름은 유효 — 재사용
        name = cached if isinstance(cached, str) and cached else _spell_name(spell_id)
        if not name:
            raise SpellTipError(f"SpellName 에 spellID {spell_id} 없음")
        try:
            raw = _spell_desc_raw(spell_id)
        except Exception:
            raw = ""                       # 일반 설명 조회 장애 — 저널 폴백은 시도
            state["transient"] = True
        desc = _clean_desc(raw, spell_id, state=state) if raw else ""
        if state.get("bad") or state.get("transient"):
            desc = ""   # 깨진 문장은 노출하지 않는다 (모듈 방침)
        if not desc:
            desc = _journal_desc(spell_id, name, state)   # 원 체인 빈손 → 던전 저널
    except Exception as exc:
        _fail_cache[("tip", spell_id)] = (time.monotonic(), str(exc))
        raise SpellTipError(str(exc))
    if state.get("transient"):
        _cache_set(spell_id, name=name)   # 일시 장애 — desc 는 다음에 재시도 (v 미기록)
    else:
        _cache_set(spell_id, name=name, desc=desc, v=CACHE_V)
    return {"name": name, "desc": desc}
