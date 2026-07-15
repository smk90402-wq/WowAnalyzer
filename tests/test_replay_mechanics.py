import unittest

from app import replay_mechanics
from app.local_replay import _select_boss_events


class ReplayMechanicTests(unittest.TestCase):
    def test_alias_uses_root_mechanic_and_difficulty_geometry(self):
        root = replay_mechanics.mechanic_profile(1280015, "Void Marked", 3181, 16)
        aura = replay_mechanics.mechanic_profile(1280023, "Void Marked", 3181, 16)
        cone = replay_mechanics.mechanic_profile(1264467, "Tail Lash", 3176, 16)

        self.assertEqual(root["key"], aura["key"])
        self.assertEqual(1280015, aura["root_spell_id"])
        self.assertEqual("cone", cone["geometry"]["shape"])
        self.assertEqual(35.0, cone["geometry"]["radius"])

    def test_cast_aura_impact_and_stacks_are_one_mechanic(self):
        boss = "Creature-0-0-0-0-1-0000000000"
        player = "Player-0-00000001"
        raw = [
            (1.0, "SPELL_CAST_START", 1280015, "Void Marked",
             boss, "Boss", player, "Tank"),
            (2.0, "SPELL_AURA_APPLIED", 1280023, "Void Marked",
             boss, "Boss", player, "Tank"),
            (3.0, "SPELL_DAMAGE", 1280023, "Void Marked",
             boss, "Boss", player, "Tank"),
        ]
        aura_updates = [
            (2.0, "SPELL_AURA_APPLIED", 1280023, player, boss, 0),
            (3.5, "SPELL_AURA_APPLIED_DOSE", 1280023, player, boss, 2),
            (4.5, "SPELL_AURA_REFRESH", 1280023, player, boss, 3),
            (7.0, "SPELL_AURA_REMOVED", 1280023, player, boss, 0),
        ]

        events = _select_boss_events(
            raw, {boss}, {boss: "b1", player: "p1"}, frozenset({1280015}),
            aura_updates=aura_updates, duration_s=10,
            encounter_id=3181, difficulty_id=16,
            guid_to_role={player: "tank"},
        )

        self.assertEqual({"cast", "hit", "impact"}, {event["kind"] for event in events})
        self.assertEqual(1, len({event["mechanic_key"] for event in events}))
        hit = next(event for event in events if event["kind"] == "hit")
        self.assertEqual(7.0, hit["end"])
        self.assertEqual(3, hit["max_stacks"])
        self.assertEqual("tank", hit["dest_role"])
        self.assertEqual("target", hit["geometry"]["shape"])


if __name__ == "__main__":
    unittest.main()
