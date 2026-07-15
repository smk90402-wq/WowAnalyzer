from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from app import replay_map


CATALOG_PATH = replay_map.DATA_DIR / "replay_spell_geometry.json"
OVERRIDES_PATH = replay_map.DATA_DIR / "replay_geometry_overrides.json"


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
def _alias_index() -> dict[int, int]:
    out: dict[int, int] = {}
    for key, spell in (_catalog().get("spells") or {}).items():
        try:
            root = int(key)
        except (TypeError, ValueError):
            continue
        out[root] = root
        for alias in spell.get("alias_ids") or []:
            try:
                out[int(alias)] = root
            except (TypeError, ValueError):
                pass
        for variant in (spell.get("variants") or {}).values():
            for alias in variant.get("trigger_ids") or []:
                try:
                    out[int(alias)] = root
                except (TypeError, ValueError):
                    pass
    return out


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
    root = _alias_index().get(sid, sid)
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
    if geometry:
        result["geometry"] = geometry
    return result


def clear_cache() -> None:
    _catalog.cache_clear()
    _overrides.cache_clear()
    _alias_index.cache_clear()
