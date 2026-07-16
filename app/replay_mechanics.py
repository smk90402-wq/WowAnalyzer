from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from app import replay_map


CATALOG_PATH = replay_map.DATA_DIR / "replay_spell_geometry.json"
OVERRIDES_PATH = replay_map.DATA_DIR / "replay_geometry_overrides.json"
TOOLTIP_OVERRIDES_PATH = replay_map.DATA_DIR / "replay_mechanic_overrides.json"


def normalize_name(name: str) -> str:
    """Return a locale-safe key for spell names observed in one combat log."""
    return re.sub(r"\s+", " ", (name or "").strip().casefold())


def _read_json(path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    return _read_json(CATALOG_PATH)


@lru_cache(maxsize=1)
def _overrides() -> dict[str, Any]:
    return _read_json(OVERRIDES_PATH)


@lru_cache(maxsize=1)
def _tooltip_overrides() -> dict[str, Any]:
    return _read_json(TOOLTIP_OVERRIDES_PATH)


@lru_cache(maxsize=1)
def _alias_index() -> dict[int, tuple[int, ...]]:
    roots_by_alias: dict[int, set[int]] = {}
    for key, spell in (_catalog().get("spells") or {}).items():
        try:
            root = int(key)
        except (TypeError, ValueError):
            continue
        roots_by_alias.setdefault(root, set()).add(root)
        for alias in spell.get("alias_ids") or []:
            try:
                roots_by_alias.setdefault(int(alias), set()).add(root)
            except (TypeError, ValueError):
                pass
        for variant in (spell.get("variants") or {}).values():
            for alias in variant.get("trigger_ids") or []:
                try:
                    roots_by_alias.setdefault(int(alias), set()).add(root)
                except (TypeError, ValueError):
                    pass
    return {alias: tuple(sorted(roots)) for alias, roots in roots_by_alias.items()}


@lru_cache(maxsize=1)
def _name_index() -> dict[str, tuple[int, ...]]:
    roots_by_name: dict[str, set[int]] = {}
    for key, spell in (_catalog().get("spells") or {}).items():
        try:
            root = int(key)
        except (TypeError, ValueError):
            continue
        blizzard = spell.get("blizzard") or {}
        wowhead = spell.get("wowhead") or {}
        names = {
            str(spell.get("name") or ""),
            str(blizzard.get("name_en") or ""),
            str(blizzard.get("name_ko") or ""),
            str(wowhead.get("name_ko") or ""),
        }
        names.update(str(entry.get("name_en") or "") for entry in
                     ((spell.get("mythictrap") or {}).get("entries") or []))
        for candidate in names:
            normalized = normalize_name(candidate)
            if normalized:
                roots_by_name.setdefault(normalized, set()).add(root)
    return {name: tuple(sorted(roots)) for name, roots in roots_by_name.items()}


def _root_for(spell_id: int, name: str = "", encounter_id: int = 0) -> int:
    sid = int(spell_id or 0)
    candidates = _alias_index().get(sid, ())
    spells = _catalog().get("spells") or {}
    observed_name = normalize_name(name)
    if observed_name:
        by_name = _name_index().get(observed_name, ())
        named = [root for root in by_name if not candidates or root in candidates]
        if len(named) == 1:
            return named[0]
        if named:
            candidates = tuple(named)
    if not candidates:
        return sid
    if len(candidates) == 1:
        return candidates[0]
    priority = {int(root) for root in ((_catalog().get("encounters") or {})
                                       .get(str(int(encounter_id or 0))) or [])}
    prioritized = [root for root in candidates if root in priority]
    if len(prioritized) == 1:
        return prioritized[0]
    journal = [root for root in candidates if int(encounter_id or 0) in
               set(((spells.get(str(root)) or {}).get("blizzard") or {})
                   .get("journal_encounters") or [])]
    if len(journal) == 1:
        return journal[0]
    guides = [root for root in candidates if any(
        int(entry.get("encounter_id") or 0) == int(encounter_id or 0)
        for entry in (((spells.get(str(root)) or {}).get("mythictrap") or {})
                      .get("entries") or []))]
    if len(guides) == 1:
        return guides[0]
    return sid if sid in candidates else candidates[0]


def _variant(spell: dict[str, Any], difficulty_id: int) -> dict[str, Any]:
    variants = spell.get("variants") or {}
    base = variants.get("0") or {}
    exact = variants.get(str(int(difficulty_id or 0))) or {}
    merged = dict(base)
    merged.update(exact)
    return merged


def _override(encounter_id: int, difficulty_id: int, spell_id: int) -> dict[str, Any]:
    entries = _overrides().get("entries") or {}
    keys = (
        f"{encounter_id}:{difficulty_id}:{spell_id}",
        f"{encounter_id}:*:{spell_id}",
        f"*:{difficulty_id}:{spell_id}",
        f"*:*:{spell_id}",
    )
    merged: dict[str, Any] = {}
    for key in reversed(keys):
        value = entries.get(key)
        if isinstance(value, dict):
            merged.update(value)
    return merged


def mechanic_profile(
    spell_id: int,
    name: str,
    encounter_id: int = 0,
    difficulty_id: int = 0,
) -> dict[str, Any]:
    """Resolve aliases, difficulty variants, mechanic key, and safe geometry."""
    sid = int(spell_id or 0)
    root = _root_for(sid, name, encounter_id)
    spells = _catalog().get("spells") or {}
    spell = spells.get(str(root)) or spells.get(str(sid)) or {}
    variant = _variant(spell, difficulty_id)
    override = _override(encounter_id, difficulty_id, root or sid)

    canonical_name = str(override.get("name") or spell.get("name") or name or "")
    key_name = normalize_name(canonical_name or name)
    key = f"name:{key_name}" if key_name else f"spell:{root or sid}"

    geometry: dict[str, Any] = {}
    if isinstance(variant.get("geometry"), dict):
        geometry.update(variant["geometry"])
    if isinstance(spell.get("geometry"), dict):
        geometry.update(spell["geometry"])
    if isinstance(override.get("geometry"), dict):
        geometry.update(override["geometry"])

    result = {
        "key": key,
        "root_spell_id": root or sid,
        "name": canonical_name or name,
        "types": list(override.get("types") or spell.get("types") or []),
    }
    tip = mechanic_tip(root or sid, name, encounter_id)
    if tip.get("name"):
        result["display_name"] = tip["name"]
    if geometry:
        result["geometry"] = geometry
    return result


def canonical_spell_id(spell_id: int, name: str = "", encounter_id: int = 0) -> int:
    return _root_for(int(spell_id or 0), name, int(encounter_id or 0))


def _guide_entry(spell: dict[str, Any], encounter_id: int) -> dict[str, Any]:
    entries = ((spell.get("mythictrap") or {}).get("entries") or [])
    if encounter_id:
        for entry in entries:
            if int(entry.get("encounter_id") or 0) == int(encounter_id):
                return entry
    return entries[0] if entries else {}


@lru_cache(maxsize=1024)
def mechanic_tip(spell_id: int, name: str = "", encounter_id: int = 0) -> dict[str, Any]:
    """Return one merged tooltip record for a combat-log or canonical spell ID."""
    sid = int(spell_id or 0)
    root = _root_for(sid, name, encounter_id)
    spell = (_catalog().get("spells") or {}).get(str(root)) or {}
    blizzard = spell.get("blizzard") or {}
    wowhead = spell.get("wowhead") or {}
    guide = _guide_entry(spell, encounter_id)
    manual = ((_tooltip_overrides().get("entries") or {}).get(str(root)) or {})
    manual_used = bool(
        (not (blizzard.get("name_ko") or wowhead.get("name_ko"))
         and manual.get("name_ko"))
        or (not (blizzard.get("description_ko") or wowhead.get("description_ko"))
            and manual.get("description_ko"))
    )
    shown_name = str(blizzard.get("name_ko") or wowhead.get("name_ko")
                     or manual.get("name_ko") or blizzard.get("name_en")
                     or spell.get("name") or name or "")
    notes = list(blizzard.get("role_notes_ko") or blizzard.get("role_notes_en") or [])
    desc = str(blizzard.get("description_ko") or wowhead.get("description_ko")
               or manual.get("description_ko") or (notes[0] if notes else "")
               or blizzard.get("description_en") or guide.get("description_en") or "")
    if desc in notes:
        notes.remove(desc)
    roles = sorted(set(blizzard.get("roles") or []) | set(guide.get("roles") or []))
    sources: list[str] = []
    if blizzard.get("journal_encounters"):
        sources.append("Blizzard 도감")
    if wowhead.get("name_ko") or wowhead.get("description_ko") or wowhead.get("icon"):
        sources.append("Wowhead")
    if guide:
        sources.append("Mythic Trap")
    manual_source = str(manual.get("source_label") or "")
    if manual_source and manual_used:
        sources.append(manual_source)
    sources = list(dict.fromkeys(sources))
    guide_out = {}
    if guide:
        guide_out = {
            "type": str(guide.get("type_ko") or guide.get("type_en") or ""),
            "action_en": str(guide.get("action_en") or ""),
            "phase": str(guide.get("phase") or ""),
            "url": str(guide.get("guide_url") or ""),
        }
    return {
        "root_spell_id": root or sid,
        "name": shown_name,
        "desc": desc,
        "role_notes": notes,
        "roles": roles,
        "guide": guide_out,
        "sources": sources,
        "icon": str(wowhead.get("icon") or ""),
        "wowhead_url": str(wowhead.get("url") or ""),
        "fallback_source_url": str(manual.get("source_url") or ""),
    }


def official_tip(spell_id: int) -> dict[str, str]:
    """Backwards-compatible name/description view of the merged catalog."""
    tip = mechanic_tip(int(spell_id or 0))
    return {"name": str(tip.get("name") or ""), "desc": str(tip.get("desc") or "")}


@lru_cache(maxsize=32)
def encounter_spell_ids(encounter_id: int) -> frozenset[int]:
    """Return journal and priority spell IDs, including their trigger aliases."""
    eid = int(encounter_id or 0)
    catalog = _catalog()
    priority = {int(sid) for sid in
                ((catalog.get("encounters") or {}).get(str(eid)) or [])}
    out: set[int] = set()
    for key, spell in (catalog.get("spells") or {}).items():
        try:
            root = int(key)
        except (TypeError, ValueError):
            continue
        journal_encounters = set((spell.get("blizzard") or {})
                                 .get("journal_encounters") or [])
        guide_encounters = {
            int(entry.get("encounter_id") or 0)
            for entry in ((spell.get("mythictrap") or {}).get("entries") or [])
        }
        if root not in priority and eid not in journal_encounters and eid not in guide_encounters:
            continue
        out.add(root)
        for alias in spell.get("alias_ids") or []:
            try:
                out.add(int(alias))
            except (TypeError, ValueError):
                pass
        for variant in (spell.get("variants") or {}).values():
            for alias in variant.get("trigger_ids") or []:
                try:
                    out.add(int(alias))
                except (TypeError, ValueError):
                    pass
    return frozenset(out)


def clear_cache() -> None:
    _catalog.cache_clear()
    _overrides.cache_clear()
    _tooltip_overrides.cache_clear()
    _alias_index.cache_clear()
    _name_index.cache_clear()
    mechanic_tip.cache_clear()
    encounter_spell_ids.cache_clear()
