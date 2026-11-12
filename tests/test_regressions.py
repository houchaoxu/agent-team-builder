"""Regression cases from independent review."""

import datetime
from pathlib import Path
import tempfile
import unittest

from agent_team.runtime import plan_task
from agent_team.storage import bootstrap, read_yaml, write_yaml


class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.team = bootstrap(self.root)

    def spec(self):
        return {"title": "review", "goal": "inspect behavior", "scores": {
            "independence": 50, "complexity": 50, "specialization": 50, "parallel_benefit": 50},
            "work_items": [{"id": "review", "role": "implementer", "goal": "inspect",
                            "read_only": True, "write_scope": [], "deliverables": ["report"]}]}

    def test_native_plan_outputs_the_verified_host_id(self):
        self.team["team"]["members"][0]["agent_id"] = "not-in-host"
        write_yaml(self.root / ".agent-team/team.yaml", self.team)
        plan = plan_task(self.root, self.spec(), {"native_subagents": True,
                          "evidence": "current tools", "available_agents": ["implementer"]})
        self.assertEqual(plan["execution"]["strategy"], "native_subagents")
        self.assertEqual(plan["execution"]["agents"][0]["agent_id"], "implementer")

    def test_non_text_goal_does_not_create_a_task(self):
        spec = self.spec()
        spec["goal"] = datetime.date(2026, 11, 12)
        with self.assertRaisesRegex(ValueError, "goal must be text"):
            plan_task(self.root, spec)
        self.assertEqual(list((self.root / ".agent-team/tasks").glob("*.yaml")), [])

    def test_non_json_write_preserves_previous_data(self):
        path = self.root / "state.yaml"
        write_yaml(path, {"valid": True})
        for value in (datetime.date(2026, 11, 12), float("nan"), {1, 2}):
            with self.assertRaises(ValueError):
                write_yaml(path, {"value": value})
            self.assertEqual(read_yaml(path), {"valid": True})


if __name__ == "__main__":
    unittest.main()
