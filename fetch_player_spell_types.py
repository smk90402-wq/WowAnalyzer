# -*- coding: utf-8 -*-
"""wowutils.com viserio-cooldowns 에서 플레이어 스킬 타입 분류표 수집.

동작 원리 (2026-07 실측):
  - /viserio-cooldowns/raid → RSC 페이로드의 "classesData" 에 40개 전문화
    전체의 specSpells[] 가 서버렌더로 박혀 있음. 항목 형태:
      {spell:{spellId, spellName, ...}, cooldown, duration, playerSpellType, guid}
  - RSC 가 반복 오브젝트를 $ref 로 축약할 수 있으므로 spec 별로 걷지 않고
    페이로드 전역에서 entry 를 모아 spellId 로 dedupe (첫 등장 우선).
  - 같은 스킬이 스펙에 따라 타입이 다른 경우(예: 영혼의 소집 = 조화 DPS CD /
    회복 Heal CD)는 첫 등장을 채택하고 나머지를 _meta.conflicts 에 기록.

출력: data/player_spell_types.json
  { "<spellId>": "<playerSpellType>", "_types": [타입 목록], "_meta": {...} }

사용: python fetch_player_spell_types.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import requests

from fetch_boss_spell_priority import BASE, _json_object_at, _rsc_payload

HEADERS = {"User-Agent": "Mozilla/5.0 (LogAnalyze player-spell-type fetch)"}
OUT_PATH = Path(__file__).parent / "data" / "player_spell_types.json"


def _get(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def fetch_player_spell_types() -> tuple[dict[int, str], dict[int, list[str]]]:
    """{spellId: type}, {spellId: [첫 등장과 다른 타입...]}"""
    payload = _rsc_payload(_get(f"{BASE}/raid"))
    types: dict[int, str] = {}
    conflicts: dict[int, list[str]] = {}
    for m in re.finditer(r'\{"spell":\{', payload):
        try:
            obj = _json_object_at(payload, m.start())
        except ValueError:
            continue
        ptype = obj.get("playerSpellType")
        if not isinstance(ptype, str):
            # talentModifiers 내부 spell / gameData 라벨 사전 등은 타입이 없음
            continue
        sid = int((obj.get("spell") or {}).get("spellId") or 0)
        if not sid:
            continue
        if sid not in types:
            types[sid] = ptype
        elif ptype != types[sid] and ptype not in conflicts.get(sid, []):
            conflicts.setdefault(sid, []).append(ptype)
    return types, conflicts


def main() -> int:
    types, conflicts = fetch_player_spell_types()
    if not types:
        print("playerSpellType 항목을 찾지 못함 — 페이지 구조 변경 여부 확인 필요")
        return 1
    counts = Counter(types.values())
    out: dict = {str(sid): t for sid, t in sorted(types.items())}
    out["_types"] = sorted(counts)
    out["_meta"] = {
        "source": "wowutils.com viserio-cooldowns /raid (RSC classesData.specSpells)",
        "fetched": date.today().isoformat(),
        "total_spells": len(types),
        "type_counts": dict(counts.most_common()),
        "conflicts": {str(sid): alts for sid, alts in sorted(conflicts.items())},
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"스킬 {len(types)}개 / 타입 {len(counts)}종")
    for t, n in counts.most_common():
        print(f"  {t}: {n}")
    if conflicts:
        print(f"스펙별 타입 상이 {len(conflicts)}건 (_meta.conflicts 기록)")
    print(f"저장: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
