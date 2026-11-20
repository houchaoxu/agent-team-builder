import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from agent_team import __version__
from agent_team.installer import export_bundle, main, skill_source


REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("skill_runner", REPO / "agent_team/skill/scripts/run.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.destination = self.root / "skill"

    def test_bundle_is_complete_idempotent_and_reexportable(self):
        result = export_bundle(self.destination)
        self.assertEqual(result["status"], "installed")
        self.assertTrue((self.destination / "scripts/run.py").is_file())
        package = self.destination / "scripts/runtime/agent_team"
        self.assertTrue((package / "cli.py").is_file())
        self.assertFalse((package / "skill").exists())
        self.assertEqual(skill_source(package), self.destination)
        (self.destination / ".cache").mkdir()
        (self.destination / ".cache/ignored").write_text("runtime cache")
        (self.destination / ".cache/python").symlink_to(sys.executable)
        self.assertEqual(export_bundle(self.destination)["status"], "unchanged")
        second = self.root / "second"
        export_bundle(second, package)
        self.assertFalse((second / ".cache").exists())
        self.assertEqual((second / "SKILL.md").read_bytes(), (self.destination / "SKILL.md").read_bytes())

    def test_different_destination_preserved(self):
        self.destination.mkdir()
        existing = self.destination / "keep"
        existing.write_text("user content")
        with self.assertRaises(ValueError):
            export_bundle(self.destination)
        self.assertEqual(existing.read_text(), "user content")

    def test_symlink_destination_and_parent_rejected(self):
        actual = self.root / "actual"
        actual.mkdir()
        self.destination.symlink_to(actual, target_is_directory=True)
        for path in (self.destination, self.destination / "nested"):
            with self.assertRaises(ValueError):
                export_bundle(path)
        self.assertEqual(list(actual.iterdir()), [])

    def test_atomic_failure_removes_stage(self):
        with patch("agent_team.installer.Path.write_bytes", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                export_bundle(self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_preview_needs_neither_dependencies_nor_writes(self):
        result = subprocess.run([sys.executable, "-S", str(REPO / "install.py"),
                                 "--destination", str(self.destination), "--platform", "codex"],
                                cwd=str(self.root), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "preview")
        self.assertFalse(self.destination.exists())

    def test_default_project_and_explicit_non_codex_destination(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--project", str(self.root), "--platform", "codex"]), 0)
        self.assertEqual(json.loads(out.getvalue())["path"],
                         str(self.root / ".agents/skills/agent-team-runtime"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--project", str(self.root), "--platform", "claude-code"]), 0)
        self.assertEqual(json.loads(out.getvalue())["path"],
                         str(self.root / ".claude/skills/agent-team-runtime"))
        self.assertFalse((self.root / ".agents").exists())

    def test_auto_selects_codex_or_claude_native_installer(self):
        for platform, marker, relative in (
                ("codex", "CODEX_THREAD_ID", ".agents/skills/agent-team-runtime"),
                ("claude-code", "CLAUDE_CODE_ENTRYPOINT", ".claude/skills/agent-team-runtime")):
            destination = self.root / platform
            output = io.StringIO()
            with patch.dict(os.environ, {marker: "active"}, clear=True), \
                    patch("agent_team.installer._files", return_value={"SKILL.md": b"fixture"}), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(main(["--project", str(destination)]), 0)
            preview = json.loads(output.getvalue())
            self.assertEqual(preview["platform"], platform)
            self.assertEqual(preview["installer"], {"id": platform, "mechanism": "native-skill-directory"})
            self.assertEqual(preview["path"], str(destination / relative))
            self.assertFalse((destination / relative).exists())

    def test_auto_does_not_guess_codex_when_host_is_unknown(self):
        with patch.dict(os.environ, {"AGENT_TEAM_PLATFORM": "generic"}, clear=True):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--project", str(self.root)]), 2)
        self.assertFalse((self.root / ".agents").exists())

    def test_native_adapter_installs_shared_bundle_and_records_host(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"CLAUDE_CODE_ENTRYPOINT": "active"}, clear=True), \
                patch("agent_team.host_installers.SkillDirectoryInstaller.install",
                      return_value={"status": "installed", "path": str(self.root / ".claude/skills/agent-team-runtime"),
                                    "files": ["SKILL.md"]}), \
                contextlib.redirect_stdout(output):
            self.assertEqual(main(["--project", str(self.root), "--approve"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "installed")
        self.assertEqual(result["platform"], "claude-code")
        self.assertEqual(result["installer"]["id"], "claude-code")
        self.assertEqual(result["activation"]["state"], "host_native_discovery")

    def test_host_specific_skill_paths_and_workbuddy_import_archive(self):
        trae = json.loads(subprocess.run([sys.executable, str(REPO / "install.py"),
                                          "--project", str(self.root), "--platform", "trae"],
                                         capture_output=True, text=True).stdout)
        self.assertEqual(trae["path"], str(self.root / ".trae/skills/agent-team-runtime"))
        pi = json.loads(subprocess.run([sys.executable, str(REPO / "install.py"),
                                        "--project", str(self.root), "--platform", "pi"],
                                       capture_output=True, text=True).stdout)
        self.assertEqual(pi["path"], str(self.root / ".agents/skills/agent-team-runtime"))
        result = subprocess.run([sys.executable, str(REPO / "install.py"), "--project", str(self.root),
                                 "--platform", "workbuddy", "--approve"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        archive_result = json.loads(result.stdout)
        self.assertEqual(archive_result["status"], "prepared_for_import")
        self.assertEqual(archive_result["activation"]["state"], "manual_import_required")
        self.assertFalse(archive_result["installed_globally"])
        with zipfile.ZipFile(archive_result["path"]) as archive:
            self.assertIn("SKILL.md", archive.namelist())
            self.assertIn("scripts/run.py", archive.namelist())
        repeated = subprocess.run([sys.executable, str(REPO / "install.py"), "--project", str(self.root),
                                   "--platform", "workbuddy", "--approve"],
                                  capture_output=True, text=True)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(json.loads(repeated.stdout)["status"], "prepared_for_import")

    def test_cold_bundle_runner_without_site_packages(self):
        export_bundle(self.destination)
        script = self.destination / "scripts/run.py"
        # -S is only for bootstrap: runner's isolated child checks actual dependencies.
        result = subprocess.run([sys.executable, "-S", str(script), "--check"],
                                cwd=str(self.root), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(json.loads(result.stdout)["status"], ("ready", "setup_required"))
        self.assertFalse((self.destination / ".cache").exists())

    def test_cold_bundle_runs_from_unrelated_directory(self):
        if not runner.available(sys.executable):
            self.skipTest("Current interpreter lacks optional runtime dependencies")
        export_bundle(self.destination)
        result = subprocess.run([sys.executable, str(self.destination / "scripts/run.py"),
                                 "--version"], cwd=str(self.root), capture_output=True, text=True, encoding="utf-8",
                                env=dict(os.environ, PYTHONPATH=str(self.root / "invalid")))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(__version__, result.stdout.strip())

    def test_missing_dependencies_are_structured_without_setup(self):
        with patch.object(runner, "locations", return_value=(self.destination, self.root)), \
                patch.object(runner, "available", return_value=False), \
                patch.object(runner.venv, "EnvBuilder") as builder, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(runner.main(["--check"]), 0)
            self.assertEqual(json.loads(out.getvalue())["status"], "setup_required")
            self.assertEqual(runner.main(["--version"]), 3)
            builder.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_setup_failure_is_finite_and_releases_lock(self):
        self.destination.mkdir()
        failure = subprocess.CompletedProcess([], 1, "", "network denied")
        with patch.object(runner, "available", return_value=False), \
                patch.object(runner.venv, "EnvBuilder") as builder, \
                patch.object(runner.subprocess, "run", return_value=failure) as run:
            with self.assertRaisesRegex(ValueError, "network denied"):
                runner.setup(self.destination)
            builder.return_value.create.assert_called_once()
            run.assert_called_once()
        self.assertFalse((self.destination / ".cache/setup.lock").exists())

    def test_setup_reuses_available_interpreter_without_writes(self):
        with patch.object(runner, "available", return_value=True), \
                patch.object(runner.venv, "EnvBuilder") as builder:
            self.assertEqual(runner.setup(self.destination), Path(sys.executable))
            builder.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_cached_environment_reused_without_network(self):
        executable = "Scripts/python.exe" if os.name == "nt" else "bin/python"
        python = self.destination / ".cache/env" / executable
        python.parent.mkdir(parents=True)
        python.write_text("fixture")
        with patch.object(runner, "available", side_effect=lambda path: Path(path) == python), \
                patch.object(runner.venv, "EnvBuilder") as builder:
            self.assertEqual(runner.setup(self.destination), python)
            builder.assert_not_called()

    def test_cache_symlink_cannot_escape_skill(self):
        self.destination.mkdir()
        (self.destination / ".cache").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            runner.cached_python(self.destination)

    def test_runner_initializes_and_recovers_project_without_global_cli(self):
        if not runner.available(sys.executable):
            self.skipTest("Current interpreter lacks optional runtime dependencies")
        export_bundle(self.destination)
        project = self.root / "project"
        project.mkdir()
        entry = project / "AGENTS.md"
        entry.write_text("User prefix\n<!-- agent-team-runtime:begin -->\nUse obsolete global CLI\n"
                         + "Skill workflow: " + json.dumps(str(self.destination / "SKILL.md")) + "\n"
                         + "<!-- agent-team-runtime:end -->\nUser suffix\n", encoding="utf-8")
        script = self.destination / "scripts/run.py"
        args = [sys.executable, str(script), "--project", str(project), "--platform", "codex"]
        result = subprocess.run(args + ["init"], cwd=str(self.root), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        first = json.loads(result.stdout)
        content = entry.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("User prefix\n"))
        self.assertTrue(content.endswith("User suffix\n"))
        self.assertIn(".agents/skills/agent-team-runtime/SKILL.md", content)
        self.assertIn("agent_team/skill/SKILL.md", content)
        self.assertNotIn(str(self.destination), content)
        self.assertNotIn("Skill workflow:", content)
        self.assertNotIn("obsolete global CLI", content)
        result = subprocess.run(args + ["init"], cwd=str(self.root), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(json.loads(result.stdout), first)
        self.assertEqual(entry.read_text(encoding="utf-8"), content)


if __name__ == "__main__":
    unittest.main()
