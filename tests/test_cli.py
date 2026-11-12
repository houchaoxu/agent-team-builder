import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agent_team.cli import main


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.prefix = ["--project", str(self.root), "--platform", "generic"]

    def invoke(self, *args, success=True):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(self.prefix + list(args))
        self.assertEqual(code, 0 if success else 2, err.getvalue())
        return json.loads(out.getvalue() if success else err.getvalue())

    def write(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def test_end_to_end_persistence_and_metrics(self):
        original = self.invoke("init")
        self.assertEqual(self.invoke("init"), original)
        self.assertTrue(self.invoke("doctor")["team_valid"])
        spec = self.write("spec.json", {
            "title": "small fix", "scores": {key: 5 for key in
                ("independence", "complexity", "specialization", "parallel_benefit")},
            "work_items": [],
        })
        plan = self.invoke("plan", spec)
        identifier = plan["task"]["id"]
        self.assertEqual(plan["execution"]["mode"], "single_agent")
        self.invoke("task", "update", identifier, "completed", success=False)
        self.invoke("task", "update", identifier, "running")
        evidence = self.write("evidence.json", {"checks": [{"command": "fixture-check", "result": "pass"}]})
        self.invoke("task", "update", identifier, "completed", "--summary", "fixture validated", "--evidence", evidence)
        self.assertEqual(self.invoke("task", "show", identifier)["task"]["status"], "completed")
        self.assertEqual(len(self.invoke("task", "list")), 1)
        self.assertEqual(self.invoke("analytics")["total_tasks"], 1)
        self.invoke("memory", "add", "experience", "preserve contract", "--source", identifier)
        self.invoke("memory", "add", "experience", "preserve contract", "--source", identifier)
        self.assertEqual(len(self.invoke("memory", "show")["experience"]), 1)

    def test_update_outdated_memory_keeps_history(self):
        self.invoke("init")
        entry = self.invoke("memory", "add", "experience", "old contract", "--source", "task-1")
        updated = self.invoke("memory", "update", "experience", entry["id"],
                              "current contract", "--source", "task-2")
        self.assertEqual(updated["text"], "current contract")
        self.assertEqual(updated["history"][-1]["text"], "old contract")

    def test_role_preview_then_install_and_restart(self):
        self.invoke("init")
        role = self.invoke("role", "generate", "order-expert", "--name", "Order Expert",
                           "--capability", "orders", "--deliverable", "order implementation")
        profile = self.write("profile.json", role)
        before = set(self.root.rglob("*.md"))
        self.invoke("role", "install", profile)
        self.assertEqual(before, set(self.root.rglob("*.md")))
        self.invoke("role", "install", profile, "--approve")
        self.invoke("role", "install", profile, "--approve")
        catalog = self.invoke("role", "catalog")
        self.assertTrue(any(r["id"] == "order-expert" for r in catalog))
        recommendations = self.invoke("role", "recommend", "--capability", "orders")
        self.assertTrue(recommendations)
        self.assertLessEqual(len(recommendations), 3)

    def test_errors_are_structured_and_keep_corrupt_file(self):
        self.invoke("init")
        path = self.root / ".agent-team/team.yaml"
        path.write_text("team: [invalid", encoding="utf-8")
        self.assertIn("error", self.invoke("init", success=False))
        self.assertEqual(path.read_text(), "team: [invalid")
        self.assertIn("error", self.invoke("plan", str(self.root / "missing.yaml"), success=False))

    def test_non_json_yaml_fails_before_persisting_task(self):
        self.invoke("init")
        path = self.root / "dated.yaml"
        path.write_text("title: date\ngoal: 2026-11-12\n", encoding="utf-8")
        result = self.invoke("plan", str(path), success=False)
        self.assertIn("quote dates", result["error"])
        self.assertEqual(self.invoke("task", "list"), [])

    def test_module_entrypoint_and_skill_export(self):
        completed = subprocess.run([sys.executable, "-m", "agent_team", "--version"],
                                   capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("2.4.0", completed.stdout)
        destination = self.root / "exported-skill"
        self.invoke("skill", str(destination))
        self.assertTrue((destination / "SKILL.md").is_file())
        self.assertTrue((destination / "references/orchestration.md").is_file())
        self.assertEqual(self.invoke("skill", str(destination))["status"], "unchanged")
        guide = self.invoke("guide")
        self.assertIn("scores:", guide["orchestration"])
        self.assertIn("native_subagents", guide["orchestration"])


if __name__ == "__main__":
    unittest.main()
