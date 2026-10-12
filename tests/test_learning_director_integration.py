"""Director wiring for the bounded learning layer; no live game is started."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import colony_director as director
import colony_learning


def ordinary_snapshot() -> dict:
    return {
        "map": {"id": 1, "seed": "test", "resources": {"meals": 10, "nutrition": 10}},
        "game": {"tick": 100},
        "colonists": [{"id": 1, "downed": False, "hunger": 0.8}],
        "development": {
            "construction_projects": [{"id": "wall-1"}],
            "roofed_sleeping_places": 1,
            "weather": {"temperature": 20},
            "item_counts": {},
        },
    }


class LearningDirectorIntegrationTests(unittest.TestCase):
    def test_accepted_ordinary_command_stages_a_lesson_for_later_observation(self):
        source = ordinary_snapshot()
        map_state = {
            "anchor": {"x": 10, "z": 10},
            "growing_anchor": {"x": 20, "z": 20},
            "issued": {"starter_base": 1},
            "starter_site_verified": True,
            "first_seen_tick": 100,
        }
        decision = {"choice": "prioritize_construction_project", "confidence": 1.0}
        candidates = ["prioritize_construction_project", "select_research"]

        with tempfile.TemporaryDirectory() as folder, \
                patch.object(director.bridge, "collect_snapshot", return_value=copy.deepcopy(source)), \
                patch.object(director, "collect_development", side_effect=lambda client, snapshot: snapshot), \
                patch.object(director, "map_state_for_snapshot", return_value=map_state), \
                patch.object(director.wildlife, "protected_group_actor_ids", return_value=set()), \
                patch.object(director.mental_safety, "reconcile", return_value={"active_ids": []}), \
                patch.object(director.colony_plan, "reconcile"), \
                patch.object(director, "project_expedition_readiness"), \
                patch.object(director, "retire_starter_sleeping_spots"), \
                patch.object(director, "candidate_actions", return_value=(candidates, {})), \
                patch.object(director, "choose_action", return_value=decision), \
                patch.object(director, "execute_action", return_value={"applied": True, "reason": "accepted"}), \
                patch.object(director, "publish_overlay"), \
                patch.object(director.laya_preferences, "load_preferences", return_value={"technical_logging": False}), \
                patch.object(director.colony_sessions, "remember_campaign"), \
                patch.object(director.colony_modules, "signals", return_value={}):
            record = director.run_development_cycle(
                object(), None, {}, Path(folder) / "state.json", Path(folder) / "log.jsonl")

        self.assertEqual(colony_learning.NORMAL_DEVELOPMENT_SCOPE, record["learning"]["scope"])
        self.assertEqual("staged", record["learning"]["stage"]["status"])
        self.assertEqual("prioritize_construction_project", map_state["learning"]["pending_decision"]["action"])
        self.assertEqual("ordinary", record["behaviour_rules"]["phase"])


if __name__ == "__main__":
    unittest.main()
