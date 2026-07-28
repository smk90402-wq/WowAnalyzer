import json
import unittest
from pathlib import Path

import analyze_lura_spec_compare as compare


DATA = Path(__file__).resolve().parents[1] / "data"


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


class LuraSpecCompareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aug_top = load("lura_top_aug_mining.json")
        cls.own = load("lura_own_pair_mining.json")
        cls.output = load("lura_spec_compare.json")

    def test_breath_reference_uses_exact_ranked_aug_sources(self):
        ref = compare._clean_breath_reference(self.aug_top)

        self.assertEqual(ref["n_top_reports"], 25)
        self.assertTrue(ref["all_kills"])
        self.assertTrue(all(row["source_id"] is not None for row in ref["sources"]))
        self.assertEqual(ref["first_cast_med_s"], 2.7)
        self.assertEqual(
            ref["gap_med_by_index"],
            {1: 73.6, 2: 78.9, 3: 118.3, 4: 80.2, 5: 86.1, 6: 114.4},
        )

    def test_breath_delay_separates_overlap_from_actual_carry_cast(self):
        ref = compare._clean_breath_reference(self.aug_top)
        summary = compare._breath_summary(self.own, ref)

        self.assertEqual(len(summary["delayed"]), 27)
        self.assertEqual(summary["delayed_with_carry_overlap"], 27)
        self.assertEqual(summary["delayed_during_cast"], 10)
        self.assertTrue(all("cast_index" in row for row in summary["delayed"]))
        self.assertEqual(summary["p3_breaths"], 0)

    def test_early_deaths_exclude_wipe_tail(self):
        latest_code = self.own["reports"][-1]["code"]
        latest = [p for p in self.own["pulls"] if p.get("report_code") == latest_code]

        aug = compare._early_death_summary(self.own["pulls"], "aug")
        udk = compare._early_death_summary(self.own["pulls"], "udk")
        self.assertEqual((aug["total"], aug["without_response"]), (27, 20))
        self.assertEqual((udk["total"], udk["without_response"]), (27, 19))
        self.assertEqual(compare._early_death_summary(latest, "aug")["total"], 0)
        self.assertEqual(compare._early_death_summary(latest, "udk")["total"], 2)

    def test_output_has_evidence_first_coaching_and_plans(self):
        for key in ("aug", "udk"):
            tab = self.output["tabs"][key]
            self.assertGreaterEqual(len(tab["problems"]), 5)
            self.assertGreaterEqual(len(tab["plan"]["items"]), 5)
            for card in tab["problems"]:
                self.assertTrue(
                    {"good", "loss", "cause", "next_pull", "evidence"}.issubset(card)
                )

        self.assertIn("이디라아", self.output["tabs"]["udk"]["title"])
        rendered = json.dumps(self.output, ensure_ascii=False)
        self.assertNotIn("죽은 횟수 (풀마다)", rendered)
        self.assertNotIn("괴사 코일", rendered)
        self.assertNotIn("죽음의 군대", rendered)


if __name__ == "__main__":
    unittest.main()
