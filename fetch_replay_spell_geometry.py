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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).parent
SOURCE_PATH = ROOT / "data" / "boss_spell_priority.json"
OUT_PATH = ROOT / "data" / "replay_spell_geometry.json"
WAGO = "https://wago.tools"
HEADERS = {"User-Agent": "LogAnalyze/1.0 (replay spell geometry fetch)"}

CONE_TARGETS = {24, 54, 59, 60, 104, 108, 109, 110, 136}
LINE_TARGETS = {133, 134, 135}
SOURCE_AREA_TARGETS = {7, 15, 22}
DEST_AREA_TARGETS = {16, 28, 31, 53, 63, 87}


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
    url = f"{WAGO}/db2/{table}/csv?filter[{field}]={value}"
    response = requests.get(url, headers=HEADERS, timeout=45)
    response.raise_for_status()
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig", errors="replace"))))


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
    return spell_id, {"name": meta.get("name", ""), "types": meta.get("types") or [],
                      "effects": effects}, radius_ids


def main() -> int:
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
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

    fetched: dict[int, dict[str, Any]] = {}
    radius_ids: set[int] = set()
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(_spell_record, sid, meta): sid for sid, meta in spell_meta.items()}
        for future in as_completed(jobs):
            sid, record, ids = future.result()
            fetched[sid] = record
            radius_ids.update(ids)

    radii: dict[int, float] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(_radius_rows, rid): rid for rid in radius_ids}
        for future in as_completed(jobs):
            rid = jobs[future]
            rows = future.result()
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

    out = {
        "_meta": {
            "source": "wago.tools DB2 SpellEffect/SpellRadius + boss_spell_priority metadata",
            "fetched": date.today().isoformat(),
            "geometry_policy": "Only plausible local radii with recognized target shapes are rendered",
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
