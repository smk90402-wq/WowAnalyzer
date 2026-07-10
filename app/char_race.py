"""캐릭터 이름-서버 → 종족/성별 (Blizzard KR 프로필 API + 디스크 캐시).

리플레이 3D 종족 모델용. 전투로그에는 종족이 없어서 프로필 API 로 1회 조회 후
data/char_race_cache.json 에 영구 캐시 (종족 변경은 유료 서비스라 사실상 불변).

- 이름 형식: "이름-서버" (로컬 전투로그 표기). 서버명은 한글 → realm index 로 slug 변환.
- 실패(탈퇴/개명/전서버 미표기)는 네거티브 캐시 (7일 TTL) — 뷰어는 구체로 폴백.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

DATA = Path(__file__).resolve().parent.parent / "data"
CACHE = DATA / "char_race_cache.json"
REALMS = DATA / "kr_realm_slugs.json"
_NEG_TTL = 7 * 86400

_cache: dict[str, Any] | None = None
_realms: dict[str, str] | None = None


def _blizzard_token() -> str | None:
    try:
        import sys
        sys.path.insert(0, str(DATA.parent))
        from blizzard import Blizzard
        return Blizzard()._ensure_token()
    except Exception:
        return None


def _load_cache() -> dict[str, Any]:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def _save_cache() -> None:
    if _cache is not None:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")


def _realm_slugs(token: str) -> dict[str, str]:
    """한글 서버명 → slug. 1회 페치 후 디스크 캐시."""
    global _realms
    if _realms is not None:
        return _realms
    try:
        _realms = json.loads(REALMS.read_text(encoding="utf-8"))
        return _realms
    except Exception:
        pass
    try:
        r = requests.get(
            "https://kr.api.blizzard.com/data/wow/realm/index",
            params={"namespace": "dynamic-kr", "locale": "ko_KR"},
            headers={"Authorization": f"Bearer {token}"}, timeout=20)
        r.raise_for_status()
        _realms = {re["name"]: re["slug"] for re in r.json().get("realms", [])}
        REALMS.write_text(json.dumps(_realms, ensure_ascii=False), encoding="utf-8")
    except Exception:
        _realms = {}
    return _realms


def _fetch_profile(token: str, slug: str, char_name: str) -> dict[str, Any] | None:
    try:
        r = requests.get(
            f"https://kr.api.blizzard.com/profile/wow/character/{slug}/{char_name.lower()}",
            params={"namespace": "profile-kr", "locale": "ko_KR"},
            headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if r.status_code != 200:
            return None
        d = r.json()
        race = (d.get("race") or {}).get("id")
        sex = 0 if (d.get("gender") or {}).get("type") == "MALE" else 1
        if race:
            return {"race": int(race), "sex": sex}
    except Exception:
        pass
    return None


def resolve_races(names: list[str]) -> dict[str, dict[str, int]]:
    """["이름-서버", ...] → {이름-서버: {race, sex}}. 실패 항목은 결과에서 제외.

    캐시 우선 — 미스만 API. 토큰 없으면 캐시 히트만 반환.
    """
    cache = _load_cache()
    out: dict[str, dict[str, int]] = {}
    misses: list[str] = []
    now = time.time()
    for n in names:
        hit = cache.get(n)
        if isinstance(hit, dict) and "race" in hit:
            out[n] = {"race": hit["race"], "sex": hit["sex"]}
        elif isinstance(hit, dict) and hit.get("neg", 0) > now - _NEG_TTL:
            continue
        else:
            misses.append(n)
    if not misses:
        return out
    token = _blizzard_token()
    if not token:
        return out
    slugs = _realm_slugs(token)
    changed = False
    for n in misses:
        if "-" not in n:
            cache[n] = {"neg": now}; changed = True
            continue
        char, realm = n.rsplit("-", 1)
        slug = slugs.get(realm)
        if not slug:
            cache[n] = {"neg": now}; changed = True
            continue
        info = _fetch_profile(token, slug, char)
        if info:
            cache[n] = info
            out[n] = info
        else:
            cache[n] = {"neg": now}
        changed = True
    if changed:
        _save_cache()
    return out
