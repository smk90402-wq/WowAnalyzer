"""전사 가이드용 스킬 영문명 → 공식 한글명 검증 (spell_db 1차, 미검출은 목록 출력)."""
from __future__ import annotations
import json, sys
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

NAMES = [
    # Fury
    "Rampage", "Bloodthirst", "Bloodbath", "Raging Blow", "Crushing Blow",
    "Execute", "Odyn's Fury", "Recklessness", "Avatar", "Bladestorm",
    "Whirlwind", "Thunder Clap", "Thunder Blast", "Rend", "Wrecking Throw",
    "Storm Bolt", "Charge", "Sudden Death", "Enrage", "Battle Shout",
    "Onslaught", "Reckless Abandon", "Anger Management", "Reap the Storm",
    "Unhinged", "Imminent Demise", "Improved Whirlwind", "Massacre",
    "Deft Experience", "Burst of Power", "Lightning Strikes", "Thorim's Might",
    # Arms
    "Mortal Strike", "Overpower", "Colossus Smash", "Warbreaker", "Demolish",
    "Ravager", "Cleave", "Slam", "Heroic Strike", "Sweeping Strikes",
    "Die by the Sword", "Spell Reflection", "Heroic Leap", "Champion's Spear",
    "Thunderous Roar", "Executioner's Precision", "Colossal Might",
    "Broad Strokes", "Crushing Combo", "Fervor of Battle", "Collateral Damage",
    "Mass Execution", "Deep Wounds", "Cut to the Bone", "Master of Warfare",
    "Dominance", "Tactician", "Dreadnought", "Battlelord", "Fatality",
    "Skullsplitter", "Piercing Howl", "Pummel", "Second Wind",
    "Mortal Wounds", "Blood Surge", "Opportunist", "Fierce Follow-Through",
    "Culling Cyclone", "Violent Euphoria", "Unrelenting Assault",
    "Improved Sweeping Strikes", "Powerful Momentum", "One Against Many",
    "Merciless Bonegrinder", "Executioner", "Marked for Execution",
]

db = json.load(open(Path("data/spell_db.json"), encoding="utf-8"))
by_en = {}
for sid, v in db.items():
    en = (v.get("name_en") or "").lower()
    if en:
        by_en.setdefault(en, []).append((sid, v.get("name_ko")))

missing = []
for n in NAMES:
    hits = by_en.get(n.lower())
    if hits:
        uniq_ko = sorted({ko for _, ko in hits})
        ids = ",".join(sid for sid, _ in hits[:4])
        print(f"{n:28s} -> {' / '.join(uniq_ko)}  (id {ids})")
    else:
        missing.append(n)

print("\n=== spell_db 미검출 (Blizzard API 확인 필요) ===")
for n in missing:
    print(" -", n)
