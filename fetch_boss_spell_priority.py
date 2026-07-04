# -*- coding: utf-8 -*-
"""wowutils.com viserio-cooldowns 에서 네임드별 '중요 보스 주문' 목록 수집.

리플레이 boss_events 의 priority 플래그 소스 (app/local_replay.py 가 읽음).

동작 원리 (2026-07 실측):
  - /viserio-cooldowns/raid            → RSC 페이로드에 raids[].bosses[]
    (bossSlug + encounterId) 가 서버렌더로 박혀 있음.
  - /viserio-cooldowns/raid/{slug}/mythic/{아무문자열} → 플랜 ID 가 유효하지
    않아도 200 + bossData(phases[].bossSpellsUsed[].spell.spellId) 를 내려줌.
  - 별도 공개 API 는 없음 (플랜 CRUD API 는 인증 필요) — HTML 임베드 파싱이 정공법.

출력: data/boss_spell_priority.json  { "<encounterID>": [spell_id...], "_meta": {...} }

사용: python fetch_boss_spell_priority.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

BASE = "https://wowutils.com/viserio-cooldowns"
HEADERS = {"User-Agent": "Mozilla/5.0 (LogAnalyze replay boss-spell fetch)"}
OUT_PATH = Path(__file__).parent / "data" / "boss_spell_priority.json"


def _get(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def _rsc_payload(html: str) -> str:
    """self.__next_f.push([1,"..."]) 조각 전부 이어붙여 JS 문자열 이스케이프 해제."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    joined = "".join(chunks)
    # JSON 문자열 규칙과 동일한 이스케이프 → json.loads 로 한 번에 해제
    try:
        return json.loads(f'"{joined}"')
    except ValueError:
        # 조각 경계가 이스케이프를 쪼갠 극단 케이스 — 최소한의 수동 해제
        return joined.replace('\\"', '"').replace("\\\\", "\\")


def _json_object_at(text: str, start: int) -> dict:
    """text[start] == '{' 에서 중괄호 짝을 맞춰 JSON 오브젝트 하나 파싱."""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unbalanced braces")


def fetch_boss_list() -> list[dict]:
    payload = _rsc_payload(_get(f"{BASE}/raid"))
    bosses = []
    for m in re.finditer(r'"bossSlug":"([a-z0-9-]+)"', payload):
        obj_start = payload.rfind("{", 0, m.start())
        try:
            obj = _json_object_at(payload, obj_start)
        except ValueError:
            continue
        if obj.get("encounterId"):
            bosses.append({
                "slug": obj["bossSlug"],
                "encounter_id": int(obj["encounterId"]),
                "name": obj.get("bossName", ""),
            })
    return bosses


def fetch_boss_spells(slug: str) -> list[dict]:
    """[{spell_id, name, types:[...]}] — mythic 우선, 없으면 heroic."""
    for diff in ("mythic", "heroic"):
        # 마지막 세그먼트는 아무 문자열이나 통과 (플랜 검증 없이 bossData 렌더)
        html = _get(f"{BASE}/raid/{slug}/{diff}/overview")
        if "bossSpellsUsed" not in html:
            continue
        payload = _rsc_payload(html)
        i = payload.find('"bossData":')
        if i < 0:
            continue
        boss_data = _json_object_at(payload, payload.index("{", i))
        spells: list[dict] = []
        seen: set[int] = set()
        for phase in boss_data.get("phases") or []:
            for used in phase.get("bossSpellsUsed") or []:
                sp = (used or {}).get("spell") or {}
                sid = int(sp.get("spellId") or 0)
                if not sid or sid in seen:
                    continue
                seen.add(sid)
                spells.append({
                    "spell_id": sid,
                    "name": sp.get("spellName", ""),
                    "types": used.get("bossSpellType") or [],
                })
        if spells:
            return spells
    return []


def main() -> int:
    bosses = fetch_boss_list()
    print(f"보스 {len(bosses)}개 발견")
    out: dict = {}
    meta_bosses: dict = {}
    for boss in bosses:
        try:
            spells = fetch_boss_spells(boss["slug"])
        except requests.RequestException as exc:
            print(f"  {boss['slug']}: 실패 ({exc})")
            continue
        eid = str(boss["encounter_id"])
        out[eid] = [s["spell_id"] for s in spells]
        meta_bosses[eid] = {
            "name": boss["name"], "slug": boss["slug"],
            "spells": {str(s["spell_id"]): {"name": s["name"], "types": s["types"]}
                       for s in spells},
        }
        print(f"  {eid} {boss['name']}: {len(spells)}개 주문")
        time.sleep(0.5)
    out["_meta"] = {
        "source": "wowutils.com viserio-cooldowns (RSC 임베드 파싱)",
        "fetched": date.today().isoformat(),
        "bosses": meta_bosses,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
