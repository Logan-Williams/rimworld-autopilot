"""Director boundary tests for the optional local Ornith adviser."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import colony_director as director


def snapshot() -> dict:
    return {
        "map": {"id": 1, "seed": "ornith-test", "resources": {"meals": 10, "nutrition": 10}},
        "game": {"tick": 100},
        "colonists": [{"id": 1, "downed": False, "hunger": 0.8}],
        "development": {
            "construction_projects": [{"id": "wall-1"}],
            "roofed_sleeping_places": 1,
            "weather": {"temperature": 20},
            "item_counts": {},
        },
    }


class AdvisorDirectorIntegrationTests(unittest.TestCase):
    def _run(self, adviser):
        source = snapshot()
        map_state = {
            "anchor": {"x": 10, "z": 10},
            "growing_anchor": {"x": 20, "z": 20},
            "issued": {"starter_base": 1},
            "starter_site_verified": True,
            "first_seen_tick": 100,
        }
        safe_candidates = ["prioritize_construction_project", "select_research"]
        decision = {"choice": "prioritize_construction_project", "confidence": 1.0}
        observed = {}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(director.bridge, "collect_snapshot", return_value=copy.deepcopy(source)), \
                patch.object(director, "collect_development", side_effect=lambda client, value: value), \
                patch.object(director, "map_state_for_snapshot", return_value=map_state), \
                patch.object(director.wildlife, "protected_group_actor_ids", return_value=set()), \
                patch.object(director.mental_safety, "reconcile", return_value={"active_ids": []}), \
                patch.object(director.colony_plan, "reconcile"), \
                patch.object(director, "project_expedition_readiness"), \
                patch.object(director, "retire_starter_sleeping_spots"), \
                patch.object(director, "candidate_actions", return_value=(safe_candidates, {})), \
                patch.object(director, "choose_action", return_value=decision) as choose, \
                patch.object(director, "execute_action", return_value={"applied": True, "reason": "accepted"}), \
                patch.object(director, "publish_overlay"), \
                patch.object(director.laya_preferences, "load_preferences", return_value={"technical_logging": False}), \
                patch.object(director.colony_sessions, "remember_campaign"), \
                patch.object(director.colony_modules, "signals", return_value={}), \
                patch.object(director.advisor, "prepare", side_effect=adviser) as prepare, \
                patch.object(director.advisor, "record", side_effect=lambda state, choice, result, audit: observed.update(
                    choice=choice, result=result, audit=audit)):
            record = director.run_development_cycle(
                object(), object(), {}, Path(folder) / "state.json", Path(folder) / "log.jsonl")
        return record, prepare, choose, observed, safe_candidates

    def test_adviser_receives_only_safe_frontier_and_cannot_expand_it(self):
        def adviser(agent, source, state, candidates, descriptions, ask):
            self.assertEqual(set(candidates), {"prioritize_construction_project", "select_research"})
            self.assertIn("prioritize_construction_project", descriptions)
            return ["prioritize_construction_project", "invented_action"], {
                "status": "accepted", "action": "prioritize_construction_project"}

        record, prepare, choose, observed, safe_candidates = self._run(adviser)

        self.assertTrue(prepare.called)
        self.assertEqual(["prioritize_construction_project"], choose.call_args.args[2])
        self.assertEqual(["prioritize_construction_project"], record["candidates"])
        self.assertEqual("accepted", record["advisor"]["status"])
        self.assertEqual("prioritize_construction_project", observed["choice"])
        self.assertEqual("accepted", observed["audit"]["status"])
        self.assertNotIn("invented_action", safe_candidates)

    def test_adviser_failure_keeps_laya_independent(self):
        record, prepare, choose, observed, safe_candidates = self._run(
            lambda *args: (_ for _ in ()).throw(RuntimeError("ornith unavailable")))

        self.assertTrue(prepare.called)
        self.assertEqual(safe_candidates, choose.call_args.args[2])
        self.assertEqual(safe_candidates, record["candidates"])
        self.assertEqual("unavailable", record["advisor"]["status"])
        self.assertIn("RuntimeError", record["advisor"]["error"])
        self.assertEqual("unavailable", observed["audit"]["status"])


if __name__ == "__main__":
    unittest.main()
