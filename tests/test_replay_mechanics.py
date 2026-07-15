import unittest

from app import replay_mechanics
from app.local_replay import _select_boss_events
from fetch_replay_spell_geometry import _journal_spells


class ReplayMechanicTests(unittest.TestCase):
    def test_alias_uses_root_mechanic_and_difficulty_geometry(self):
        root = replay_mechanics.mechanic_profile(1280015, "Void Marked", 3181, 16)
        aura = replay_mechanics.mechanic_profile(1280023, "Void Marked", 3181, 16)
        cone = replay_mechanics.mechanic_profile(1264467, "Tail Lash", 3176, 16)

        self.assertEqual(root["key"], aura["key"])
        self.assertEqual(1280015, aura["root_spell_id"])
        self.assertEqual("cone", cone["geometry"]["shape"])
        self.assertEqual(35.0, cone["geometry"]["radius"])

    def test_blizzard_journal_metadata_is_retained_while_spell_api_is_locked(self):
        tip = replay_mechanics.official_tip(1280015)

        self.assertEqual("공허 징표", tip["name"])
        self.assertEqual("", tip["desc"])

    def test_journal_roles_and_section_paths_are_extracted(self):
        sections = [{
            "title": "Overview",
            "sections": [{
                "title": "Tanks",
                "body_text": "$bullet; Avoid [Void Marked].",
            }],
        }, {
            "title": "Phase Two",
            "sections": [{
                "title": "Void Marked",
                "spell": {"id": 1280015, "name": "Void Marked"},
            }],
        }]

        spells = _journal_spells(sections)

        self.assertEqual(["tank"], spells[1280015]["roles"])
        self.assertEqual(["Phase Two > Void Marked"], spells[1280015]["section_paths"])

    def test_shared_trigger_ids_use_observed_name_before_encounter_fallback(self):
        divine = replay_mechanics.mechanic_profile(
            1246391, "Divine Toll", 3180, 16)
        tyr = replay_mechanics.mechanic_profile(
            1246391, "Tyr's Wrath", 3180, 16)
        manifestation = replay_mechanics.mechanic_profile(
            1255763, "Midnight Manifestation", 3178, 16)

        self.assertEqual(1248644, divine["root_spell_id"])
        self.assertEqual(1248710, tyr["root_spell_id"])
        self.assertEqual(1258744, manifestation["root_spell_id"])

    def test_journal_spell_is_tracked_without_becoming_display_priority(self):
        boss = "Creature-0-0-0-0-1-0000000000"
        player = "Player-0-00000001"
        journal_spell = 1280075

        self.assertIn(journal_spell, replay_mechanics.encounter_spell_ids(3176))
        events = _select_boss_events(
            [(1.0, "SPELL_DAMAGE", journal_spell, "Lingering Darkness",
              boss, "Boss", player, "Player")],
            {boss}, {boss: "b1", player: "p1"}, frozenset(),
            tracked_ids=frozenset({journal_spell}), encounter_id=3176,
            difficulty_id=16,
        )

        self.assertEqual("impact", events[0]["kind"])
        self.assertNotIn("priority", events[0])

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
