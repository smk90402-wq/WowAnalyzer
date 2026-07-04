# -*- coding: utf-8 -*-
"""wago.tools db2 CSV 에서 스킬별 재사용 대기시간(쿨다운) 수집.

리플레이 이벤트 분류용 — SPELL_CAST_SUCCESS 중 "쿨기(공격 쿨다운)·생존기"
후보를 골라내는 기준 데이터 (쿨다운 45초 이상 스킬만).

동작 원리 (2026-07 실측):
  - /api/builds → product "wow" 최신 = Midnight 라이브 빌드 (예: 12.0.7.68367).
    db2 CSV 에 build 미지정 시 어떤 빌드가 올지 보장이 없어 명시 지정.
  - /db2/SpellCooldowns/csv?build=... : SpellID → RecoveryTime/CategoryRecoveryTime (ms).
    DifficultyID 별 행이 있을 수 있음 → 0(기본) 우선.
  - 차지 스킬은 RecoveryTime=0 이고 실제 쿨다운이 SpellCategory 에 있음:
    SpellCategories.ChargeCategory → SpellCategory.ChargeRecoveryTime (ms).
    (예: 얼음 방패 45438 — SpellCooldowns 는 0, 차지 카테고리 1560 → 240s)
  - 스킬 쿨다운 = max(RecoveryTime, CategoryRecoveryTime, ChargeRecoveryTime).
    SpellCooldowns 에 아예 없고 차지 카테고리만 있는 스킬도 포함.
  - ⚠ wago.tools 는 파이썬 기본 UA 를 403 차단 → UA 헤더 필수 (replay_map 과 동일).

출력: data/spell_cooldowns.json  { "<spellID>": 쿨다운초(int) }  (45s 이상만)

사용: python fetch_spell_cooldowns.py
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import requests

WAGO = "https://wago.tools"
HEADERS = {"User-Agent": "LogAnalyze/1.0 (spell cooldown fetch)"}
OUT_PATH = Path(__file__).parent / "data" / "spell_cooldowns.json"
MIN_COOLDOWN_MS = 45_000


def _get(url: str) -> bytes:
    resp = requests.get(url, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    return resp.content


def live_build() -> str:
    """product 'wow' (라이브) 의 최신 버전 문자열."""
    builds = json.loads(_get(f"{WAGO}/api/builds"))
    return builds["wow"][0]["version"]


def _table_rows(table: str, build: str) -> list[dict[str, str]]:
    text = _get(f"{WAGO}/db2/{table}/csv?build={build}").decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _to_int(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def build_cooldown_map(build: str) -> dict[str, int]:
    """SpellID(str) → 쿨다운 ms. 차지 카테고리 반영, DifficultyID 0 우선."""
    # 1) 차지 카테고리 → ChargeRecoveryTime (ms)
    charge_ms = {r["ID"]: _to_int(r.get("ChargeRecoveryTime"))
                 for r in _table_rows("SpellCategory", build)}

    # 2) SpellID → ChargeCategory (DifficultyID 0 우선)
    charge_cat: dict[str, str] = {}
    charge_cat_diff0: set[str] = set()
    for r in _table_rows("SpellCategories", build):
        cat = r.get("ChargeCategory") or "0"
        if cat == "0":
            continue
        sid = r["SpellID"]
        diff0 = _to_int(r.get("DifficultyID")) == 0
        if sid not in charge_cat or (diff0 and sid not in charge_cat_diff0):
            charge_cat[sid] = cat
            if diff0:
                charge_cat_diff0.add(sid)

    # 3) SpellCooldowns: max(RecoveryTime, CategoryRecoveryTime), DifficultyID 0 우선
    base_ms: dict[str, int] = {}
    base_diff0: set[str] = set()
    for r in _table_rows("SpellCooldowns", build):
        sid = r["SpellID"]
        ms = max(_to_int(r.get("RecoveryTime")), _to_int(r.get("CategoryRecoveryTime")))
        diff0 = _to_int(r.get("DifficultyID")) == 0
        if sid not in base_ms or (diff0 and sid not in base_diff0):
            base_ms[sid] = ms
            if diff0:
                base_diff0.add(sid)

    # 4) 병합 — 차지만 있는 스킬(SpellCooldowns 에 행 없음)도 포함
    out: dict[str, int] = dict(base_ms)
    for sid, cat in charge_cat.items():
        ms = charge_ms.get(cat, 0)
        if ms > out.get(sid, 0):
            out[sid] = ms
    return out


def main() -> int:
    build = live_build()
    print(f"라이브 빌드: {build}")
    cooldown_ms = build_cooldown_map(build)
    print(f"쿨다운 보유 스킬: {len(cooldown_ms)}개")

    kept = {sid: round(ms / 1000)
            for sid, ms in cooldown_ms.items() if ms >= MIN_COOLDOWN_MS}
    out = {sid: kept[sid] for sid in sorted(kept, key=int)}
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"45초 이상: {len(out)}개 → {OUT_PATH} ({OUT_PATH.stat().st_size / 1024:.0f}KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
