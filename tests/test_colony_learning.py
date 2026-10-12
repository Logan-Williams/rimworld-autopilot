import unittest

import colony_learning


NORMAL_SCOPE = colony_learning.NORMAL_DEVELOPMENT_SCOPE


def snapshot(*, tick=100, meals=4, nutrition=4, downed=False, projects=0,
             food_state="secure", enemies=None):
    return {
        "game": {"tick": tick},
        "colonists": [{"id": 1, "downed": downed}],
        "map": {"resources": {"meals": meals, "nutrition": nutrition}, "enemies": enemies or []},
        "development": {
            "food_budget": {"state": food_state},
            "construction_projects": [{} for _ in range(projects)],
        },
    }


def feedback(action, changes, *, command="accepted", status="observed_changes"):
    return {"action": action, "command": command, "status": status,
            "changes": changes, "causation": "not_established"}


class RewardLearningTests(unittest.TestCase):
    def test_waiting_feedback_keeps_pending_decision_until_measured_outcome(self):
        state = {}
        colony_learning.stage_decision(
            snapshot(tick=100, projects=1), state,
            "prioritize_construction_project", ["prioritize_construction_project"],
            scope=NORMAL_SCOPE,
        )
        waiting = snapshot(tick=100, projects=1)
        waiting["development"]["outcome_feedback"] = feedback(
            "prioritize_construction_project", {}, status="awaiting_game_progress",
        )

        result = colony_learning.reconcile(waiting, state)

        self.assertEqual("awaiting_feedback", result["status"])
        self.assertIn("pending_decision", state["learning"])

        observed = snapshot(tick=120, projects=0)
        observed["development"]["outcome_feedback"] = feedback(
            "prioritize_construction_project",
            {"construction_projects": {"before": 1, "after": 0}},
        )

        result = colony_learning.reconcile(observed, state)

        self.assertEqual("recorded", result["status"])
        self.assertNotIn("pending_decision", state["learning"])
        self.assertEqual(1, next(iter(state["learning"]["profiles"].values()))["observations"])

    def test_pending_feedback_cannot_be_overwritten_by_a_second_same_tick_decision(self):
        state = {}
        original = snapshot(tick=100, projects=1)
        colony_learning.stage_decision(
            original, state, "prioritize_construction_project",
            ["prioritize_construction_project"], scope=NORMAL_SCOPE,
        )
        original["development"]["outcome_feedback"] = feedback(
            "prioritize_construction_project", {}, status="awaiting_game_progress",
        )
        colony_learning.reconcile(original, state)

        second = colony_learning.stage_decision(
            original, state, "select_research", ["select_research"], scope=NORMAL_SCOPE,
        )

        self.assertEqual("pending_feedback", second["status"])
        self.assertEqual("prioritize_construction_project",
                         state["learning"]["pending_decision"]["action"])

    def test_delayed_progress_belongs_to_original_pending_action(self):
        state = {}
        colony_learning.stage_decision(
            snapshot(tick=100, projects=2), state,
            "prioritize_construction_project", ["prioritize_construction_project"],
            scope=NORMAL_SCOPE,
        )
        # The normal outcome observer now describes a later order.  The
        # learner must retain the original action and compare its own baseline.
        later = snapshot(tick=180, projects=1)
        later["development"]["outcome_feedback"] = feedback(
            "select_research", {}, command="accepted", status="no_measured_change",
        )

        result = colony_learning.reconcile(later, state)

        self.assertEqual("recorded", result["status"])
        self.assertEqual("prioritize_construction_project", result["episode"]["action"])
        self.assertEqual(3, result["episode"]["reward"])

    def test_rejected_repeat_of_same_action_cannot_cancel_older_pending_lesson(self):
        state = {}
        colony_learning.stage_decision(
            snapshot(tick=100, projects=1), state,
            "prioritize_construction_project", ["prioritize_construction_project"],
            scope=NORMAL_SCOPE,
        )
        waiting = snapshot(tick=101, projects=1)
        waiting["development"]["outcome_feedback"] = {
            **feedback("prioritize_construction_project", {}, status="no_measured_change"),
            "command_tick": 100,
        }
        self.assertEqual("awaiting_effect", colony_learning.reconcile(waiting, state)["status"])

        # The newer retry is rejected.  It is not evidence about the already
        # accepted command at tick 100 and must not erase its pending lesson.
        rejected_repeat = snapshot(tick=102, projects=1)
        rejected_repeat["development"]["outcome_feedback"] = {
            **feedback("prioritize_construction_project", {}, command="not_applied"),
            "command_tick": 101,
        }
        result = colony_learning.reconcile(rejected_repeat, state)

        self.assertEqual("awaiting_effect", result["status"])
        self.assertIn("pending_decision", state["learning"])
        self.assertEqual(100, state["learning"]["pending_decision"]["tick"])

    def test_learning_scope_rejects_food_and_unreviewed_actions(self):
        ordinary = ["prioritize_construction_project", "select_research"]
        self.assertEqual(NORMAL_SCOPE, colony_learning.learning_scope(snapshot(projects=1), ordinary))
        self.assertEqual("survival_or_thermal_focus", colony_learning.learning_scope(
            {**snapshot(projects=1), "development": {"food_emergency_context": True}}, ordinary))
        self.assertEqual("action_not_whitelisted", colony_learning.learning_scope(
            snapshot(projects=1), ["prioritize_construction_project", "prioritize_cooking"]))

    def test_rejected_or_waiting_command_is_not_a_training_example(self):
        state = {}
        before = snapshot(food_state="critical")
        colony_learning.stage_decision(before, state, "prioritize_cooking", ["prioritize_cooking"], scope=NORMAL_SCOPE)
        later = snapshot(tick=101, food_state="critical")
        later["development"]["outcome_feedback"] = {
            **feedback("prioritize_cooking", {}, command="not_applied"),
            "command_tick": 100,
        }

        result = colony_learning.reconcile(later, state)

        self.assertEqual("not_applied", result["episode"]["verdict"])
        self.assertEqual({}, state["learning"]["profiles"])

    def test_food_gain_receives_observed_reward_not_causation_claim(self):
        state = {}
        before = snapshot(food_state="critical", meals=0, nutrition=0)
        colony_learning.stage_decision(before, state, "prioritize_cooking", ["prioritize_cooking"], scope=NORMAL_SCOPE)
        later = snapshot(tick=120, food_state="critical", meals=2, nutrition=3)
        later["development"]["outcome_feedback"] = feedback("prioritize_cooking", {
            "meals": {"before": 0, "after": 2}, "nutrition": {"before": 0, "after": 3},
        })

        result = colony_learning.reconcile(later, state)

        self.assertEqual("reward", result["episode"]["verdict"])
        self.assertEqual(3, result["episode"]["reward"])
        self.assertEqual("not_established", result["episode"]["causation"])

    def test_defensive_build_uses_defense_measurement_not_generic_construction(self):
        state = {}
        before = snapshot(enemies=[{"id": 9}])
        colony_learning.stage_decision(
            before, state, "build_killbox", ["build_killbox"], scope=NORMAL_SCOPE,
        )
        later = snapshot(tick=120, enemies=[])
        later["development"]["outcome_feedback"] = feedback("build_killbox", {
            "threats": {"before": [{"id": 9}], "after": []},
        })

        result = colony_learning.reconcile(later, state)

        self.assertEqual("defense", result["episode"]["domain"])
        self.assertEqual("reward", result["episode"]["verdict"])
        self.assertEqual(4, result["episode"]["reward"])

    def test_enemy_list_growth_is_a_safety_penalty(self):
        state = {}
        before = snapshot(enemies=[{"id": 1}])
        colony_learning.stage_decision(
            before, state, "build_fallback_defense", ["build_fallback_defense"], scope=NORMAL_SCOPE,
        )
        later = snapshot(tick=120, enemies=[{"id": 1}, {"id": 2}])
        later["development"]["outcome_feedback"] = feedback("build_fallback_defense", {
            "threats": {"before": [{"id": 1}], "after": [{"id": 1}, {"id": 2}]},
        })

        result = colony_learning.reconcile(later, state)

        self.assertEqual("penalty", result["episode"]["verdict"])
        self.assertEqual(-8, result["episode"]["reward"])
        self.assertIn("threats_increased:1", result["episode"]["penalties"])

    def test_safety_regression_is_penalty_and_blocks_promotion(self):
        state = {}
        for offset in range(3):
            before = snapshot(tick=100 + offset * 10, projects=1)
            colony_learning.stage_decision(before, state, "prioritize_construction_project", ["prioritize_construction_project"], scope=NORMAL_SCOPE)
            later = snapshot(tick=105 + offset * 10, downed=True, projects=0)
            later["development"]["outcome_feedback"] = feedback("prioritize_construction_project", {
                "construction_projects": {"before": 1, "after": 0},
                "downed": {"before": 0, "after": 1},
            })
            colony_learning.reconcile(later, state)

        profile = next(iter(state["learning"]["profiles"].values()))

        self.assertEqual(3, profile["observations"])
        self.assertEqual(3, profile["safety_regressions"])
        self.assertFalse(profile["active"])
        self.assertLess(profile["reward_total"], 0)

    def test_three_matching_rewards_promote_only_that_scenario(self):
        state = {}
        for offset in range(3):
            before = snapshot(tick=100 + offset * 10, food_state="critical", meals=0, nutrition=0)
            colony_learning.stage_decision(before, state, "prioritize_cooking", ["prioritize_cooking", "prioritize_hauling"], scope=NORMAL_SCOPE)
            later = snapshot(tick=105 + offset * 10, food_state="critical", meals=2, nutrition=2)
            later["development"]["outcome_feedback"] = feedback("prioritize_cooking", {
                "meals": {"before": 0, "after": 2}, "nutrition": {"before": 0, "after": 2},
            })
            colony_learning.reconcile(later, state)

        ranked, evidence = colony_learning.rank_candidates(
            snapshot(tick=200, food_state="critical", meals=0, nutrition=0), state,
            ["prioritize_hauling", "prioritize_cooking"], scope=NORMAL_SCOPE,
        )
        unmatched, unmatched_evidence = colony_learning.rank_candidates(
            snapshot(tick=201, food_state="secure"), state,
            ["prioritize_hauling", "prioritize_cooking"], scope=NORMAL_SCOPE,
        )

        self.assertEqual(["prioritize_cooking", "prioritize_hauling"], ranked)
        self.assertTrue(evidence["applied"])
        self.assertEqual(["prioritize_hauling", "prioritize_cooking"], unmatched)
        self.assertFalse(unmatched_evidence["applied"])

    def test_protected_candidate_is_never_reordered_or_replaced(self):
        state = {}
        signature = colony_learning.scenario_signature(snapshot(food_state="critical"))
        state["learning"] = {
            "contract": colony_learning.LEARNING_CONTRACT,
            "episodes": [],
            "profiles": {"one": {
                "signature": signature, "action": "prioritize_cooking", "observations": 3,
                "reward_total": 9, "rewarded": 3, "penalized": 0,
                "safety_regressions": 0, "active": True,
            }},
        }

        ranked, evidence = colony_learning.rank_candidates(
            snapshot(food_state="critical"), state,
            ["prioritize_cooking", "rescue_downed_colonist"], scope=NORMAL_SCOPE,
        )

        self.assertEqual(["prioritize_cooking", "rescue_downed_colonist"], ranked)
        self.assertEqual("protected_action_present", evidence["reason"])
        self.assertEqual(2, len(ranked))

    def test_real_emergency_action_ids_block_candidate_reordering(self):
        state = {}
        signature = colony_learning.scenario_signature(snapshot(food_state="critical"))
        state["learning"] = {
            "contract": colony_learning.LEARNING_CONTRACT,
            "episodes": [],
            "profiles": {"one": {
                "signature": signature, "action": "prioritize_cooking", "observations": 3,
                "reward_total": 9, "rewarded": 3, "penalized": 0,
                "safety_regressions": 0, "active": True,
            }},
        }
        candidates = ["fight_fire", "resilience_rescue", "prepare_patient_bed", "prioritize_cooking"]

        ranked, evidence = colony_learning.rank_candidates(
            snapshot(food_state="critical"), state, candidates, scope=NORMAL_SCOPE,
        )

        self.assertEqual(candidates, ranked)
        self.assertEqual("protected_action_present", evidence["reason"])

    def test_timeline_reset_discards_memory_from_old_map_timeline(self):
        state = {"learning": {"contract": colony_learning.LEARNING_CONTRACT,
                                "episodes": [{"action": "old"}], "profiles": {"old": {}}}}
        later = snapshot(tick=1)
        later["development"]["outcome_feedback"] = {"status": "timeline_reset"}

        result = colony_learning.reconcile(later, state)

        self.assertEqual("timeline_reset", result["status"])
        self.assertEqual([], state["learning"]["episodes"])
        self.assertEqual({}, state["learning"]["profiles"])

    def test_other_action_paths_never_stage_or_apply_learning(self):
        state = {}

        staged = colony_learning.stage_decision(
            snapshot(food_state="critical"), state, "prioritize_cooking",
            ["prioritize_cooking", "prioritize_hauling"], scope="critical_food_recovery",
        )
        ranked, evidence = colony_learning.rank_candidates(
            snapshot(food_state="critical"), state,
            ["prioritize_hauling", "prioritize_cooking"], scope="critical_food_recovery",
        )

        self.assertEqual("scope_not_eligible", staged["status"])
        self.assertNotIn("learning", state)
        self.assertEqual(["prioritize_hauling", "prioritize_cooking"], ranked)
        self.assertEqual("scope_not_eligible", evidence["reason"])


if __name__ == "__main__":
    unittest.main()
