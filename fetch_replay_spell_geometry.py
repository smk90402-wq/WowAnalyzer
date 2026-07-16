# -*- coding: utf-8 -*-
"""Build replay spell links and conservative geometry from client DB2 data.

SpellEffect supplies difficulty variants, trigger spell links, implicit target
types, and radius indexes. SpellRadius supplies yard values. Geometry is only
emitted when the target type makes the meaning of the radius sufficiently
clear; large target-search radii are never rendered as ground effects.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).parent
SOURCE_PATH = ROOT / "data" / "boss_spell_priority.json"
OUT_PATH = ROOT / "data" / "replay_spell_geometry.json"
WAGO = "https://wago.tools"
HEADERS = {"User-Agent": "LogAnalyze/1.0 (replay spell geometry fetch)"}

# WCL encounter ID -> Blizzard journal encounter ID. The instance/encounter
# names are also checked on every refresh so a stale mapping is visible.
BLIZZARD_JOURNALS = {
    "3159": 2711,
    "3176": 2733, "3177": 2734, "3178": 2735, "3179": 2736,
    "3180": 2737, "3181": 2738, "3182": 2739, "3183": 2740,
    "3306": 2795,
}
ARCHON_HOME = "https://www.archon.gg/wow"
WOWHEAD_TOOLTIP = "https://nether.wowhead.com/tooltip/spell/{spell_id}?dataEnv=1&locale=1"
MYTHICTRAP_GUIDES = {
    "3159": "sporefall/rotmire",
    "3176": "vs-dr-mqd/imperator-averzian",
    "3177": "vs-dr-mqd/vorasius",
    "3178": "vs-dr-mqd/vaelgor-and-ezzorak",
    "3179": "vs-dr-mqd/fallen-king-salhadaar",
    "3180": "vs-dr-mqd/lightblinded-vanguard",
    "3181": "vs-dr-mqd/crown-of-the-cosmos",
    "3182": "vs-dr-mqd/beloren-child-of-alar",
    "3183": "vs-dr-mqd/midnight-falls",
    "3306": "vs-dr-mqd/chimaerus-the-undreamt-god",
}

CONE_TARGETS = {24, 54, 59, 60, 104, 108, 109, 110, 136}
LINE_TARGETS = {133, 134, 135}
SOURCE_AREA_TARGETS = {7, 15, 22}
DEST_AREA_TARGETS = {16, 28, 31, 53, 63, 87}


def _normalize_name(value: str) -> str:
    return re.sub(r"[\W_]+", "", (value or "").casefold(), flags=re.UNICODE)


@lru_cache(maxsize=1)
def _wago_build() -> str:
    response = requests.get(f"{WAGO}/api/builds", headers=HEADERS, timeout=45)
    response.raise_for_status()
    return str(response.json()["wow"][0]["version"])


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _rows(table: str, field: str, value: int) -> list[dict[str, str]]:
    url = f"{WAGO}/db2/{table}/csv?build={_wago_build()}&filter[{field}]={value}"
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            response = requests.get(url, headers=HEADERS, timeout=45)
            response.raise_for_status()
            return list(csv.DictReader(io.StringIO(
                response.content.decode("utf-8-sig", errors="replace"))))
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 4:
                time.sleep(1.5 * (2 ** attempt))
    raise RuntimeError(f"{table} {field}={value} fetch failed: {last_error}")


def _journal_spells(sections: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    role_refs: dict[str, set[str]] = {}
    role_notes: dict[str, list[str]] = {}

    def collect_roles(nodes: list[dict[str, Any]]) -> None:
        for node in nodes or []:
            title = str(node.get("title") or "")
            role = {
                "Tanks": "tank", "Healers": "healer", "Damage Dealers": "damage",
                "방어 담당": "tank", "치유 담당": "healer", "공격 담당": "damage",
            }.get(title)
            if role:
                body = str(node.get("body_text") or "").replace("\r", "")
                for part in body.split("$bullet;"):
                    note = re.sub(r"\s+", " ", part).strip()
                    for name in re.findall(r"\[([^\]]+)\]", note):
                        key = _normalize_name(name)
                        role_refs.setdefault(key, set()).add(role)
                        if note and note not in role_notes.setdefault(key, []):
                            role_notes[key].append(note)
            collect_roles(node.get("sections") or [])

    def walk(nodes: list[dict[str, Any]], path: tuple[str, ...] = ()) -> None:
        for node in nodes or []:
            title = str(node.get("title") or "").strip()
            current_path = path + ((title,) if title else ())
            spell = node.get("spell") or {}
            sid = _int(spell.get("id"))
            if sid:
                item = out.setdefault(sid, {
                    "name_en": str(spell.get("name") or title),
                    "section_paths": set(),
                })
                item["section_paths"].add(" > ".join(current_path))
            walk(node.get("sections") or [], current_path)

    collect_roles(sections)
    walk(sections)
    for item in out.values():
        key = _normalize_name(item["name_en"])
        item["roles"] = sorted(role_refs.get(key, set()))
        item["role_notes"] = role_notes.get(key, [])
        item["section_paths"] = sorted(item["section_paths"])
    return out


class _WowheadDescriptionParser(HTMLParser):
    """Collect only the rendered spell description (`div.q`) from tooltip HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class") or ""
        if self.depth:
            if tag in {"br", "p", "li"}:
                self.parts.append("\n")
            if tag not in {"br", "img", "hr", "meta", "link", "input"}:
                self.depth += 1
        elif tag == "div" and "q" in classes.split():
            self.depth = 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.depth and tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self.depth:
            return
        if tag in {"p", "li"}:
            self.parts.append("\n")
        self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)

    def text(self) -> str:
        text = "".join(self.parts).replace("\xa0", " ").replace("\r", "")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def _decode_wowhead_ko(value: str) -> str:
    """Wowhead locale=1 currently labels CP949 bytes as UTF-8; repair when useful."""
    try:
        repaired = value.encode("latin1").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    hangul = lambda text: sum("가" <= ch <= "힣" for ch in text)
    return repaired if hangul(repaired) > hangul(value) else value


def _clean_wowhead_text(value: str) -> str:
    text = value.replace("|n", "\n")

    def josa(match: re.Match[str]) -> str:
        before = match.string[:match.start()]
        last = next((ch for ch in reversed(before) if ch.isalnum()), "")
        has_batchim = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
        return match.group(1) if has_batchim else match.group(2)

    text = re.sub(r"\|1([^;]*);([^;]*);", josa, text)
    text = re.sub(r"\|4([^:;]*):([^;]*);", lambda m: m.group(1), text)
    text = re.sub(r"\$[lL]([^:;]*):([^;]*);", lambda m: m.group(1), text)
    text = re.sub(r"\|c[0-9a-fA-F]{8}|\|r|\|T[^|]*\|t", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return "" if "$" in text or "|" in text else text


def _wowhead_payload(spell_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    name = _decode_wowhead_ko(str(payload.get("name") or "")).strip()
    icon = str(payload.get("icon") or "").strip().lower()
    tooltip = _decode_wowhead_ko(str(payload.get("tooltip") or ""))
    parser = _WowheadDescriptionParser()
    parser.feed(tooltip)
    return {
        "name_ko": name,
        "description_ko": _clean_wowhead_text(parser.text()),
        "icon": icon,
        "url": f"https://ko.wowhead.com/spell={spell_id}",
    }


def _request_json(url: str, attempts: int = 4) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, headers=HEADERS, timeout=45)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                return data
            raise RuntimeError("response is not an object")
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.0 * (2 ** attempt))
    raise RuntimeError(f"request failed: {url}: {last_error}")


def _wowhead_sources(spell_meta: dict[int, dict[str, Any]],
                     previous: dict[str, Any]) -> dict[str, Any]:
    status: dict[str, Any] = {
        "transport": "public tooltip JSON; community metadata, no documented API",
        "available": 0, "descriptions_ko": 0, "icons": 0,
        "previous_fallbacks": 0, "errors": [],
    }

    def fetch(spell_id: int) -> tuple[int, dict[str, Any]]:
        payload = _request_json(WOWHEAD_TOOLTIP.format(spell_id=spell_id))
        return spell_id, _wowhead_payload(spell_id, payload)

    with ThreadPoolExecutor(max_workers=10) as pool:
        jobs = {pool.submit(fetch, sid): sid for sid in sorted(spell_meta)}
        for future in as_completed(jobs):
            sid = jobs[future]
            try:
                _, info = future.result()
            except Exception as exc:
                old = ((previous.get("spells") or {}).get(str(sid)) or {}).get("wowhead")
                if isinstance(old, dict) and old:
                    spell_meta[sid]["wowhead"] = old
                    status["previous_fallbacks"] += 1
                else:
                    status["errors"].append(f"{sid}: {exc}")
                continue
            spell_meta[sid]["wowhead"] = info
            status["available"] += 1
            status["descriptions_ko"] += bool(info.get("description_ko"))
            status["icons"] += bool(info.get("icon"))
    return status


def _guide_tag_ko(value: str) -> str:
    key = re.sub(r"\s+", " ", (value or "").strip().casefold())
    exact = {
        "mythic mechanic": "신화 기믹", "boss positioning": "보스 위치 조절",
        "platform switch": "발판 이동", "memory game": "순서 기억",
        "constellation stars": "별자리", "room management": "전장 관리",
        "damage amp": "받는 피해 증가", "damage reduction": "피해 감소",
        "healing reduction": "치유 감소", "damage absorb": "피해 흡수",
        "disorient": "방향 감각 상실", "silence": "침묵",
        "boss buffs": "보스 강화", "claims space": "공간 장악",
        "clone": "복제물", "cloned mechanics": "복제 기믹",
        "fear": "공포", "heal through": "치유로 버티기",
        "move out": "바깥으로 이동", "orb walls": "구슬 벽",
        "orbs mechanic": "구슬 기믹", "raid wipe": "전멸 기믹",
        "random damage": "무작위 대상 피해", "run away": "멀리 이동",
        "silver clone": "은빛 복제물", "tail swipe": "꼬리 휩쓸기",
        "tank apart": "탱커 이격", "void monsters": "공허 괴물",
    }
    if key in exact:
        return exact[key]
    rules = (
        (("tankbuster",), "탱커 강타"),
        (("tank dot", "tank debuff", "tank mechanic"), "탱커 디버프"),
        (("heal absorb", "healing absorb", "heal absorbs"), "치유 흡수"),
        (("interrupt",), "차단"), (("dispel",), "해제"),
        (("soak",), "같이 맞기"), (("kite",), "드리블"),
        (("raid damage", "aoe damage", "rot damage"), "공격대 피해"),
        (("dodge", "beam", "line", "planet", "ring", "arrow"), "피하기"),
        (("add", "egg", "crystal", "miniboss"), "추가 대상 처리"),
        (("puddle", "area denial"), "바닥"),
        (("memory", "match", "color"), "순서·색상 맞추기"),
        (("knockback", "pull"), "밀쳐내기"),
        (("shield", "immunity"), "보호 효과"),
        (("intermission",), "사이 페이즈"), (("tether",), "연결선"),
        (("stay", "light"), "자리 유지"), (("rot", "dot"), "지속 피해"),
    )
    for needles, label in rules:
        if any(needle in key for needle in needles):
            return label
    return value.strip()


def _mythictrap_abilities(boss: dict[str, Any]) -> list[dict[str, Any]]:
    abilities: list[dict[str, Any]] = []
    for phase in boss.get("bossPhases") or []:
        for group in ("bossAbilitiesWithVideos", "bossAbilities"):
            for ability in phase.get(group) or []:
                if "mythic" in (ability.get("difficultyIgnore") or []):
                    continue
                sid = _int(ability.get("spellID"))
                if not sid:
                    continue
                parser = _WowheadDescriptionParser()
                parser.feed(
                    f'<div class="q">{str(ability.get("descriptionHTML") or "")}</div>')
                abilities.append({
                    "spell_id": sid,
                    "name_en": str(ability.get("name") or ""),
                    "type_en": str(ability.get("subtitle") or ""),
                    "type_ko": _guide_tag_ko(str(ability.get("subtitle") or "")),
                    "action_en": str(ability.get("category") or ""),
                    "description_en": parser.text(),
                    "roles": sorted({str(role).lower() for role in
                                     (ability.get("filters") or []) if role}),
                    "phase": str(phase.get("phaseName") or ""),
                })
    return abilities


def _mythictrap_sources(spell_meta: dict[int, dict[str, Any]],
                        boss_meta: dict[str, Any]) -> dict[str, Any]:
    status: dict[str, Any] = {
        "transport": "public Next.js page data linked by Archon Boss Guides",
        "guides": {}, "ability_entries": 0, "unique_spell_ids": 0,
    }
    unique_ids: set[int] = set()
    for encounter_id, path in MYTHICTRAP_GUIDES.items():
        url = f"https://www.mythictrap.com/en/{path}/mythic"
        try:
            response = requests.get(url, headers=HEADERS, timeout=45)
            response.raise_for_status()
            match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                response.text, re.S)
            if not match:
                raise RuntimeError("__NEXT_DATA__ missing")
            page = json.loads(match.group(1))
            boss = (((page.get("props") or {}).get("pageProps") or {}).get("boss") or {})
            abilities = _mythictrap_abilities(boss)
            expected = str((boss_meta.get(encounter_id) or {}).get("name") or "")
            actual = str(boss.get("name") or "")
            status["guides"][encounter_id] = {
                "url": url, "name_en": actual,
                "name_matches": _normalize_name(expected) == _normalize_name(actual),
                "ability_count": len(abilities),
            }
            for ability in abilities:
                sid = ability.pop("spell_id")
                unique_ids.add(sid)
                entry = {"encounter_id": int(encounter_id), "guide_url": url, **ability}
                meta = spell_meta.setdefault(sid, {
                    "name": entry["name_en"], "types": []})
                guide = meta.setdefault("mythictrap", {"entries": []})
                entries = guide.setdefault("entries", [])
                marker = (entry["encounter_id"], entry["name_en"], entry["action_en"])
                if marker not in {(e.get("encounter_id"), e.get("name_en"), e.get("action_en"))
                                  for e in entries}:
                    entries.append(entry)
                    status["ability_entries"] += 1
        except Exception as exc:
            status["guides"][encounter_id] = {"url": url, "error": str(exc)}
    status["unique_spell_ids"] = len(unique_ids)
    return status


def _blizzard_sources(spell_meta: dict[int, dict[str, Any]],
                      boss_meta: dict[str, Any]) -> dict[str, Any]:
    status: dict[str, Any] = {
        "enabled": False,
        "journal_encounters": {},
        "spell_api_available": 0,
        "spell_api_restricted_or_unpublished": 0,
        "spell_api_errors": [],
    }
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass
    if not os.environ.get("BLIZZARD_CLIENT_ID") or not os.environ.get("BLIZZARD_CLIENT_SECRET"):
        status["reason"] = "BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET missing"
        return status
    try:
        from blizzard import Blizzard
        client = Blizzard()
    except Exception as exc:
        status["reason"] = f"client init failed: {exc}"
        return status

    status["enabled"] = True
    namespace = ""
    journal_ids: set[int] = set()
    for encounter_id, journal_id in BLIZZARD_JOURNALS.items():
        try:
            data_en = client.get(
                f"/data/wow/journal-encounter/{journal_id}", locale="en_US", retry=2)
            data_ko = client.get(
                f"/data/wow/journal-encounter/{journal_id}", locale="ko_KR", retry=2)
        except Exception as exc:
            status["journal_encounters"][encounter_id] = {
                "journal_id": journal_id, "error": str(exc)}
            continue
        if not data_en:
            status["journal_encounters"][encounter_id] = {
                "journal_id": journal_id, "available": False}
            continue
        href = (((data_en.get("_links") or {}).get("self") or {}).get("href") or "")
        match = re.search(r"[?&]namespace=([^&]+)", href)
        if match:
            namespace = match.group(1)
        spells_en = _journal_spells(data_en.get("sections") or [])
        spells_ko = _journal_spells((data_ko or {}).get("sections") or [])
        expected = str((boss_meta.get(encounter_id) or {}).get("name") or "")
        actual = str(data_en.get("name") or "")
        status["journal_encounters"][encounter_id] = {
            "journal_id": journal_id,
            "available": True,
            "name_en": actual,
            "name_ko": str((data_ko or {}).get("name") or ""),
            "description_en": str(data_en.get("description") or ""),
            "description_ko": str((data_ko or {}).get("description") or ""),
            "name_matches": _normalize_name(expected) == _normalize_name(actual),
            "spell_count": len(spells_en),
        }
        for sid, journal in spells_en.items():
            journal_ids.add(sid)
            ko = spells_ko.get(sid) or {}
            blizzard = {
                "name_en": str(journal.get("name_en") or ""),
                "name_ko": str(ko.get("name_en") or ""),
                "journal_encounters": [int(encounter_id)],
                "section_paths": list(journal.get("section_paths") or []),
                "section_paths_ko": list(ko.get("section_paths") or []),
                "roles": sorted(set(journal.get("roles") or []) |
                                set(ko.get("roles") or [])),
                "role_notes_en": list(journal.get("role_notes") or []),
                "role_notes_ko": list(ko.get("role_notes") or []),
            }
            meta = spell_meta.setdefault(sid, {"name": journal["name_en"], "types": []})
            existing = meta.get("blizzard")
            if isinstance(existing, dict):
                blizzard["journal_encounters"] = sorted(set(
                    existing.get("journal_encounters") or []) | {int(encounter_id)})
                blizzard["section_paths"] = sorted(set(
                    existing.get("section_paths") or []) | set(journal["section_paths"]))
                blizzard["roles"] = sorted(set(
                    existing.get("roles") or []) | set(journal["roles"]))
                for field in ("section_paths_ko", "role_notes_en", "role_notes_ko"):
                    blizzard[field] = list(dict.fromkeys(
                        list(existing.get(field) or []) + list(blizzard.get(field) or [])))
            meta["blizzard"] = blizzard

    def fetch_spell(spell_id: int) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None]:
        en = client.get(f"/data/wow/spell/{spell_id}", locale="en_US", retry=2)
        ko = client.get(f"/data/wow/spell/{spell_id}", locale="ko_KR", retry=2) if en else None
        return spell_id, en, ko

    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(fetch_spell, sid): sid for sid in sorted(spell_meta)}
        for future in as_completed(jobs):
            sid = jobs[future]
            try:
                _, en, ko = future.result()
            except Exception as exc:
                status["spell_api_errors"].append(f"{sid}: {exc}")
                continue
            meta = spell_meta[sid]
            blizzard = meta.setdefault("blizzard", {})
            if en:
                status["spell_api_available"] += 1
                blizzard["spell_api"] = "available"
                blizzard["name_en"] = str(en.get("name") or blizzard.get("name_en") or "")
                blizzard["name_ko"] = str((ko or {}).get("name") or blizzard.get("name_ko") or "")
                blizzard["description_en"] = str(en.get("description") or "")
                blizzard["description_ko"] = str((ko or {}).get("description") or "")
            else:
                status["spell_api_restricted_or_unpublished"] += 1
                blizzard["spell_api"] = "restricted_or_unpublished"
    if namespace:
        status["namespace"] = namespace
    status["journal_spell_ids"] = len(journal_ids)
    return status


def _archon_sources() -> dict[str, Any]:
    status: dict[str, Any] = {
        "transport": "public Next.js page data; no documented Archon public API",
        "pages": [],
    }
    try:
        home = requests.get(ARCHON_HOME, headers=HEADERS, timeout=45)
        home.raise_for_status()
        paths = set(re.findall(
            r'href=["\'](/wow/tier-list/dps-rankings/[^"\']+/mythic/[^"\']+)["\']',
            home.text))
        paths.update({
            "/wow/tier-list/dps-rankings/raid/mythic/all-bosses",
            "/wow/tier-list/dps-rankings/sporefall/mythic/rotmire",
        })
        for path in sorted(paths):
            response = requests.get(f"https://www.archon.gg{path}", headers=HEADERS, timeout=45)
            response.raise_for_status()
            match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                response.text)
            if not match:
                continue
            page = ((json.loads(match.group(1)).get("props") or {}).get("pageProps") or {}).get("page") or {}
            description = str((page.get("seo") or {}).get("description") or page.get("description") or "")
            patches = sorted(set(re.findall(r"\b\d+\.\d+\.\d+\b", description)))
            encounter_ids = []
            for option in page.get("encounterOptions") or []:
                found = re.search(r"EncounterIcon id=['\"](\d+)", str(option.get("label") or ""))
                if found:
                    encounter_ids.append(int(found.group(1)))
            status["pages"].append({
                "url": f"https://www.archon.gg{path}",
                "last_updated": page.get("lastUpdated"),
                "total_parses": page.get("totalParses"),
                "patches": patches,
                "encounter_ids": sorted(set(encounter_ids)),
            })
    except Exception as exc:
        status["error"] = str(exc)
    return status


def _effect_rows(spell_id: int) -> list[dict[str, str]]:
    return [row for row in _rows("SpellEffect", "SpellID", spell_id)
            if _int(row.get("SpellID")) == spell_id]


def _radius_rows(radius_id: int) -> list[dict[str, str]]:
    return [row for row in _rows("SpellRadius", "ID", radius_id)
            if _int(row.get("ID")) == radius_id]


def _pick_radius(effect: dict[str, Any], radii: dict[int, float]) -> float:
    # RadiusIndex_0 is the effect area. RadiusIndex_1 is often a 300yd search
    # range, so only accept it when it is a plausible local mechanic radius.
    r0 = radii.get(effect["radius_0"], 0.0)
    r1 = radii.get(effect["radius_1"], 0.0)
    if 0.5 <= r0 <= 80:
        return r0
    if 0.5 <= r1 <= 80:
        return r1
    return 0.0


def _geometry(effects: list[dict[str, Any]], radii: dict[int, float], types: list[str]) -> dict[str, Any] | None:
    for effect in effects:
        target = effect["target_0"] or effect["target_1"]
        radius = _pick_radius(effect, radii)
        if target in CONE_TARGETS and radius:
            return {"shape": "cone", "anchor": "source", "radius": radius,
                    "angle": 90, "source": "SpellEffect/SpellRadius", "confidence": "db2"}
        if target in LINE_TARGETS and radius:
            return {"shape": "line", "anchor": "source", "length": radius,
                    "width": max(2.0, min(8.0, radius * 0.15)),
                    "source": "SpellEffect/SpellRadius", "confidence": "db2"}
        if target in SOURCE_AREA_TARGETS and radius:
            return {"shape": "circle", "anchor": "source", "radius": radius,
                    "source": "SpellEffect/SpellRadius", "confidence": "db2"}
        if target in DEST_AREA_TARGETS and radius:
            return {"shape": "circle", "anchor": "target", "radius": radius,
                    "source": "SpellEffect/SpellRadius", "confidence": "db2"}

    # These are useful semantic fallbacks, not claims about exact dimensions.
    if "Group Soak" in types:
        return {"shape": "target", "anchor": "target", "source": "Viserio type",
                "confidence": "semantic"}
    if "Debuffs" in types or "Tankbuster" in types:
        return {"shape": "target", "anchor": "target", "source": "Viserio type",
                "confidence": "semantic"}
    return None


def _spell_record(spell_id: int, meta: dict[str, Any]) -> tuple[int, dict[str, Any], set[int]]:
    raw = _effect_rows(spell_id)
    radius_ids = {_int(row.get("EffectRadiusIndex_0")) for row in raw}
    radius_ids.update(_int(row.get("EffectRadiusIndex_1")) for row in raw)
    radius_ids.discard(0)
    effects = []
    for row in raw:
        effects.append({
            "difficulty_id": _int(row.get("DifficultyID")),
            "effect": _int(row.get("Effect")),
            "aura": _int(row.get("EffectAura")),
            "trigger_spell": _int(row.get("EffectTriggerSpell")),
            "radius_0": _int(row.get("EffectRadiusIndex_0")),
            "radius_1": _int(row.get("EffectRadiusIndex_1")),
            "target_0": _int(row.get("ImplicitTarget_0")),
            "target_1": _int(row.get("ImplicitTarget_1")),
        })
    return spell_id, {
        "name": meta.get("name", ""),
        "types": meta.get("types") or [],
        "blizzard": meta.get("blizzard") or {},
        "wowhead": meta.get("wowhead") or {},
        "mythictrap": meta.get("mythictrap") or {},
        "effects": effects,
    }, radius_ids


def main() -> int:
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    try:
        previous = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except Exception:
        previous = {}
    bosses = (source.get("_meta") or {}).get("bosses") or {}
    spell_meta: dict[int, dict[str, Any]] = {}
    encounters: dict[str, list[int]] = {}
    for encounter_id, ids in source.items():
        if encounter_id.startswith("_") or not isinstance(ids, list):
            continue
        encounters[encounter_id] = [_int(sid) for sid in ids if _int(sid)]
        meta_spells = (bosses.get(encounter_id) or {}).get("spells") or {}
        for sid in encounters[encounter_id]:
            spell_meta.setdefault(sid, meta_spells.get(str(sid)) or {})

    mythictrap_status = _mythictrap_sources(spell_meta, bosses)
    blizzard_status = _blizzard_sources(spell_meta, bosses)
    wowhead_status = _wowhead_sources(spell_meta, previous)
    archon_status = _archon_sources()
    print(
        "Blizzard: journal spells "
        f"{blizzard_status.get('journal_spell_ids', 0)}, direct spell API "
        f"{blizzard_status.get('spell_api_available', 0)} available / "
        f"{blizzard_status.get('spell_api_restricted_or_unpublished', 0)} restricted")
    print(
        "Wowhead: "
        f"{wowhead_status.get('descriptions_ko', 0)} Korean descriptions / "
        f"{wowhead_status.get('icons', 0)} icons")
    print(
        "Mythic Trap: "
        f"{len(mythictrap_status.get('guides') or {})} guides / "
        f"{mythictrap_status.get('ability_entries', 0)} ability entries")
    print(f"Archon: {len(archon_status.get('pages') or [])} public data pages checked")

    fetched: dict[int, dict[str, Any]] = {}
    radius_ids: set[int] = set()
    fetch_errors: list[str] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(_spell_record, sid, meta): sid for sid, meta in spell_meta.items()}
        for future in as_completed(jobs):
            try:
                sid, record, ids = future.result()
            except Exception as exc:
                sid = jobs[future]
                fetch_errors.append(f"SpellEffect {sid}: {exc}")
                continue
            fetched[sid] = record
            radius_ids.update(ids)

    radii: dict[int, float] = {
        _int(rid): _float(value)
        for rid, value in (previous.get("radii") or {}).items()
        if _int(rid) and _float(value)
    }
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(_radius_rows, rid): rid for rid in radius_ids}
        for future in as_completed(jobs):
            rid = jobs[future]
            try:
                rows = future.result()
            except Exception as exc:
                fetch_errors.append(f"SpellRadius {rid}: {exc}")
                continue
            if rows:
                radii[rid] = _float(rows[0].get("Radius"))

    spells: dict[str, Any] = {}
    for sid, record in sorted(fetched.items()):
        variants: dict[str, Any] = {}
        alias_ids: set[int] = set()
        by_diff: dict[int, list[dict[str, Any]]] = {}
        for effect in record.pop("effects"):
            by_diff.setdefault(effect["difficulty_id"], []).append(effect)
            if effect["trigger_spell"]:
                alias_ids.add(effect["trigger_spell"])
        for difficulty_id, effects in sorted(by_diff.items()):
            variant: dict[str, Any] = {
                "trigger_ids": sorted({e["trigger_spell"] for e in effects if e["trigger_spell"]}),
                "effects": effects,
            }
            geometry = _geometry(effects, radii, record["types"])
            if geometry:
                variant["geometry"] = geometry
            variants[str(difficulty_id)] = variant
        spells[str(sid)] = {**record, "alias_ids": sorted(alias_ids), "variants": variants}
    for sid, meta in spell_meta.items():
        if sid in fetched:
            continue
        old = (previous.get("spells") or {}).get(str(sid))
        if not isinstance(old, dict):
            continue
        spells[str(sid)] = {
            **old,
            "name": meta.get("name") or old.get("name") or "",
            "types": meta.get("types") or old.get("types") or [],
            "blizzard": meta.get("blizzard") or old.get("blizzard") or {},
            "wowhead": meta.get("wowhead") or old.get("wowhead") or {},
            "mythictrap": meta.get("mythictrap") or old.get("mythictrap") or {},
        }

    out = {
        "_meta": {
            "source": "Wago DB2 geometry + Blizzard journal/spell audit + Wowhead tooltip metadata + Archon/Mythic Trap guide audit",
            "fetched": date.today().isoformat(),
            "wago_build": _wago_build(),
            "geometry_policy": "Only plausible local radii with recognized target shapes are rendered",
            "blizzard": blizzard_status,
            "wowhead": wowhead_status,
            "mythictrap": mythictrap_status,
            "archon": archon_status,
            "fetch_errors": fetch_errors,
        },
        "encounters": encounters,
        "radii": {str(k): v for k, v in sorted(radii.items())},
        "spells": spells,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved {OUT_PATH}: {len(spells)} spells, {len(radii)} radii")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
