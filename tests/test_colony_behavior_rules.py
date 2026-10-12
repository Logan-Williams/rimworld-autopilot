import unittest

import colony_behavior_rules as rules


def snapshot(*, hunger=0.8, raw_food=0, meals=10, temperature=20,
             roofed_sleeping_places=1, people=1):
    return {
        "colonists": [{"id": index + 1, "hunger": hunger} for index in range(people)],
        "map": {"resources": {"raw_food": raw_food, "meals": meals}},
        "development": {
            "weather": {"temperature": temperature},
            "roofed_sleeping_places": roofed_sleeping_places,
        },
    }


class BehaviourRuleTests(unittest.TestCase):
    def test_prepared_food_goal_prefers_existing_cooking_actions_not_raw_food(self):
        choices, audit = rules.apply(
            snapshot(raw_food=80, meals=1, people=2),
            ["select_research", "prioritize_cooking", "configure_food_bills"],
        )

        self.assertEqual(["prioritize_cooking", "configure_food_bills"], choices)
        self.assertEqual("prepared_food", audit["phase"])
        self.assertIn("prepared_food_before_raw_food_preference", audit["goals"])

    def test_food_rule_never_invents_a_missing_native_command(self):
        original = ["select_research", "prioritize_construction"]

        choices, audit = rules.apply(snapshot(raw_food=80, meals=0), original)

        self.assertEqual(original, choices)
        self.assertIn("prepared_food_action_unavailable", audit["blockers"])

    def test_shelter_goal_limits_only_to_existing_shelter_choices(self):
        choices, audit = rules.apply(
            snapshot(roofed_sleeping_places=0, people=2),
            ["select_research", "build_starter_base", "prioritize_construction_project"],
        )

        self.assertEqual(["build_starter_base", "prioritize_construction_project"], choices)
        self.assertEqual("shelter", audit["phase"])
        self.assertIn("shelter_before_optional_work", audit["goals"])

    def test_cold_weather_prefers_native_warmth_but_blocks_unverifiable_clothing(self):
        choices, audit = rules.apply(
            snapshot(temperature=-8),
            ["select_research", "build_room_heater"],
        )

        self.assertEqual(["build_room_heater"], choices)
        self.assertEqual("winter_protection", audit["phase"])
        clothing = next(item for item in audit["directives"] if item["id"] == "clothing.cold_readiness")
        self.assertEqual("blocked", clothing["state"])
        self.assertIn("worn_apparel_insulation", clothing["missing_evidence"])

    def test_cold_weather_reports_missing_protection_without_fabricating_it(self):
        original = ["select_research", "prioritize_construction"]

        choices, audit = rules.apply(snapshot(temperature=-8), original)

        self.assertEqual(original, choices)
        self.assertIn("warm_protection_action_unavailable", audit["blockers"])

    def test_native_emergency_keeps_current_safety_frontier_unchanged(self):
        original = ["rescue_downed_colonist", "select_research", "prioritize_cooking"]

        choices, audit = rules.apply(snapshot(raw_food=80, meals=0), original)

        self.assertEqual(original, choices)
        self.assertEqual("native_emergency", audit["phase"])


if __name__ == "__main__":
    unittest.main()
