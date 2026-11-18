"""Update safety tests runnable with unittest and without runtime dependencies."""
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from agent_team import updates as u


def install(root, version="2.6.0", timestamp=None):
    root.mkdir(parents=True, exist_ok=True)
    files = {"SKILL.md": b"Skill content", "scripts/run.py": ("print(" + repr(version) + ")\n").encode()}
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = {"schema_version": 1, "repository": u.REPOSITORY, "version": version,
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    if timestamp is not None:
        manifest["installed_at"] = timestamp
    (root / u.MANIFEST_NAME).write_text(json.dumps(manifest))
    return manifest


def bundle(root, version="2.7.0"):
    install(root, version)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, "agent-team-runtime/" + path.relative_to(root).as_posix())
    return buffer.getvalue()


def release(version="2.7.0"):
    tag = "v" + version
    base = "https://github.com/" + u.REPOSITORY + "/releases/download/" + tag + "/"
    return {"version": version, "url": "https://github.com/" + u.REPOSITORY + "/releases/tag/" + tag,
            "assets": {name: base + name for name in (u.ASSET_NAME, u.ASSET_NAME + ".sha256")}, "release_notes": "Release notes"}


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.skill = self.root / "agent-team-runtime"
        install(self.skill)

    def download(self, payload, bad_digest=False):
        def fetch(url, limit, assets=False):
            if url.endswith(".sha256"):
                digest = "0" * 64 if bad_digest else hashlib.sha256(payload).hexdigest()
                return (digest + "  " + u.ASSET_NAME + "\n").encode()
            return payload
        return fetch

    def test_weekly_interval_and_once_per_version(self):
        with patch.object(u, "_release", return_value=release()) as fetch:
            first = u.check_updates(self.skill, now=100)
            self.assertEqual(first["status"], "update_available")
            self.assertTrue(first["notify"])
            self.assertEqual(u.check_updates(self.skill, now=101)["status"], "skipped")
            self.assertFalse(u.check_updates(self.skill, now=100 + u.INTERVAL)["notify"])
            self.assertEqual(fetch.call_count, 2)
        with patch.object(u, "_release", return_value=release("2.8.0")):
            self.assertTrue(u.check_updates(self.skill, force=True, now=200)["notify"])

    def test_new_install_waits_one_week(self):
        install(self.skill, timestamp=1000)
        with patch.object(u, "_release", return_value=release()) as fetch:
            self.assertEqual(u.check_updates(self.skill, now=1001)["status"], "skipped")
            self.assertFalse(fetch.called)
            self.assertEqual(u.check_updates(self.skill, now=1001, force=True)["status"], "update_available")

    def test_network_failure_cools_down_and_does_not_raise(self):
        with patch.object(u, "_release", side_effect=OSError("offline")) as fetch:
            self.assertEqual(u.check_updates(self.skill, now=100)["status"], "unavailable")
            self.assertEqual(u.check_updates(self.skill, now=101)["status"], "skipped")
            self.assertEqual(fetch.call_count, 1)

    def test_preferences_force_and_no_network_status(self):
        with patch.object(u, "_release", return_value=release()) as fetch:
            self.assertEqual(u.configure_updates(self.skill, enabled=False)["status"], "disabled")
            self.assertEqual(u.check_updates(self.skill)["status"], "disabled")
            self.assertEqual(u.update_status(self.skill)["status"], "disabled")
            self.assertFalse(fetch.called)
            self.assertEqual(u.check_updates(self.skill, force=True)["status"], "update_available")
            u.configure_updates(self.skill, enabled=True, snooze_days=2, now=100)
            self.assertEqual(u.check_updates(self.skill, now=101)["status"], "snoozed")
            self.assertEqual(u.configure_updates(self.skill, snooze_days=0, now=101)["status"], "current")
        for value in (-1, 366, True, 1.2):
            with self.assertRaises(ValueError):
                u.configure_updates(self.skill, snooze_days=value)

    def test_corrupt_state_is_rebuilt(self):
        (self.skill / ".cache").mkdir()
        (self.skill / ".cache/update-state.json").write_text("not json")
        with patch.object(u, "_release", return_value=release()):
            self.assertEqual(u.check_updates(self.skill, now=100)["status"], "update_available")
        self.assertTrue(json.loads((self.skill / ".cache/update-state.json").read_text())["enabled"])

    def test_unmanaged_install_is_not_modified(self):
        (self.skill / u.MANIFEST_NAME).unlink()
        with patch.object(u, "_release") as fetch:
            self.assertEqual(u.check_updates(self.skill)["status"], "unmanaged")
            self.assertFalse(fetch.called)
        with self.assertRaises(ValueError):
            u.configure_updates(self.skill, enabled=False)
        self.assertFalse((self.skill / ".cache").exists())

    def test_version_validation(self):
        for value in ("2.6", "2.6.0-beta", "02.6.0", "v2.6.0", "2.6.0+meta", None):
            with self.assertRaises(ValueError):
                u._version(value)
        self.assertGreater(u._version("2.10.0"), u._version("2.9.0"))

    def test_release_sources_and_stable_only(self):
        base = release()
        data = {"tag_name": "v2.7.0", "draft": False, "prerelease": False,
                "html_url": base["url"], "body": "x" * 3000,
                "assets": [{"name": name, "browser_download_url": url} for name, url in base["assets"].items()]}
        with patch.object(u, "_download", return_value=json.dumps(data).encode()):
            self.assertEqual(len(u._release()["release_notes"]), 2000)
        for key, value in (("draft", True), ("prerelease", True), ("html_url", "https://evil.test/release"), ("tag_name", "v2.7.0-rc1")):
            changed = dict(data, **{key: value})
            with patch.object(u, "_download", return_value=json.dumps(changed).encode()):
                with self.assertRaises(ValueError):
                    u._release()
        data["assets"][0]["browser_download_url"] = "https://github.com/attacker/repo/releases/download/v2.7.0/" + u.ASSET_NAME
        with patch.object(u, "_download", return_value=json.dumps(data).encode()):
            with self.assertRaises(ValueError):
                u._release()

    def test_preview_only_fetches_metadata(self):
        before = sorted(p.relative_to(self.skill).as_posix() for p in self.skill.rglob("*"))
        with patch.object(u, "_release", return_value=release()), patch.object(u, "_download") as download:
            result = u.upgrade(self.skill)
        self.assertEqual(result["status"], "preview")
        self.assertFalse(download.called)
        self.assertEqual(before, sorted(p.relative_to(self.skill).as_posix() for p in self.skill.rglob("*")))
        self.assertFalse((self.root / ".agent-team-runtime.backups").exists())

    def test_local_changes_missing_and_extra_files_are_protected(self):
        cases = (lambda: (self.skill / "SKILL.md").write_text("custom"),
                 lambda: (self.skill / "SKILL.md").unlink(),
                 lambda: (self.skill / "extra.txt").write_text("custom"))
        for change in cases:
            with self.subTest(change=change):
                shutil.rmtree(self.skill)
                install(self.skill)
                change()
                with patch.object(u, "_release") as fetch:
                    with self.assertRaises(ValueError):
                        u.upgrade(self.skill, approved=True)
                    self.assertFalse(fetch.called)

    def test_upgrade_rollback_preserves_cache_and_links(self):
        cache = self.skill / ".cache"
        cache.mkdir()
        (cache / "preferences").write_text("original")
        (cache / "python").symlink_to(Path(__file__).absolute())
        payload = bundle(self.root / "new")
        with patch.object(u, "_release", return_value=release()), patch.object(u, "_download", side_effect=self.download(payload)):
            result = u.upgrade(self.skill, approved=True)
        self.assertEqual(result["status"], "upgraded")
        self.assertEqual(u._verify(self.skill)["version"], "2.7.0")
        self.assertTrue((cache / "python").is_symlink())
        (cache / "preferences").write_text("new preference")
        self.assertEqual(u.rollback(self.skill, result["backup_id"])["status"], "preview")
        restored = u.rollback(self.skill, result["backup_id"], approved=True)
        self.assertEqual(restored["status"], "rolled_back")
        self.assertEqual(u._verify(self.skill)["version"], "2.6.0")
        self.assertEqual((cache / "preferences").read_text(), "new preference")
        self.assertTrue((cache / "python").is_symlink())

    def test_bad_digest_preserves_old_install(self):
        payload = bundle(self.root / "new")
        with patch.object(u, "_release", return_value=release()), patch.object(u, "_download", side_effect=self.download(payload, True)):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                u.upgrade(self.skill, approved=True)
        self.assertEqual(u._verify(self.skill)["version"], "2.6.0")

    def test_real_probe_rejects_wrong_reported_version(self):
        stage = self.root / "probe"
        install(stage, "2.6.0")
        with self.assertRaisesRegex(ValueError, "version check failed"):
            u._probe(stage, "2.7.0")

    def test_probe_failure_preserves_old_install(self):
        payload = bundle(self.root / "new")
        with patch.object(u, "_release", return_value=release()), patch.object(u, "_download", side_effect=self.download(payload)), patch.object(u, "_probe", side_effect=ValueError("dependencies missing")):
            with self.assertRaises(ValueError):
                u.upgrade(self.skill, approved=True)
        self.assertEqual(u._verify(self.skill)["version"], "2.6.0")

    def test_replacement_failure_restores_old_install(self):
        payload = bundle(self.root / "new")
        rename = Path.rename
        def fail_activation(path, target):
            if ".stage-" in path.name:
                raise OSError("replace blocked")
            return rename(path, target)
        with patch.object(u, "_release", return_value=release()), patch.object(u, "_download", side_effect=self.download(payload)), patch.object(Path, "rename", fail_activation):
            with self.assertRaisesRegex(OSError, "replace blocked"):
                u.upgrade(self.skill, approved=True)
        self.assertEqual(u._verify(self.skill)["version"], "2.6.0")
        # A persistent inode is safe; the OS lock itself has been released.
        with u._lock(self.skill):
            pass

    def test_terminated_lock_owner_does_not_block_future_updates(self):
        code = ('from pathlib import Path\nfrom agent_team.updates import _lock\n'
                'import sys,time\nwith _lock(Path(sys.argv[1])):\n'
                ' print("locked",flush=True)\n time.sleep(30)\n')
        process = subprocess.Popen([sys.executable, '-c', code, str(self.skill)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'locked')
            with self.assertRaises(ValueError):
                u.configure_updates(self.skill, enabled=False)
            process.kill()
            process.wait(timeout=5)
            self.assertEqual(u.configure_updates(self.skill, enabled=False)['status'], 'disabled')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()

    def test_zip_traversal_symlink_duplicate_and_bomb_are_rejected(self):
        for name, mode, duplicate in (("agent-team-runtime/../escape", 0, False),
                                      ("/absolute", 0, False),
                                      ("agent-team-runtime/link", stat.S_IFLNK | 0o777, False),
                                      ("agent-team-runtime/a", 0, True)):
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as archive:
                entry = zipfile.ZipInfo(name)
                entry.external_attr = mode << 16
                archive.writestr(entry, "evil")
                if duplicate:
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        archive.writestr(name, "again")
            stage = self.root / "stage"
            stage.mkdir(exist_ok=True)
            try:
                with self.assertRaises(ValueError):
                    u._extract(output.getvalue(), stage, "2.7.0")
            finally:
                shutil.rmtree(stage)
        payload = bundle(self.root / "new")
        with patch.object(u, "MAX_BYTES", 10):
            with self.assertRaises(ValueError):
                u._extract(payload, self.root / "stage", "2.7.0")

    def test_manifest_hash_and_version_are_required(self):
        root = self.root / "new"
        payload = bundle(root)
        with self.assertRaisesRegex(ValueError, "version"):
            u._extract(payload, self.root / "stage", "2.8.0")
        (root / "SKILL.md").write_text("tampered")
        with self.assertRaises(ValueError):
            u._verify(root)

    def test_bad_manifest_and_backup_traversal(self):
        for backup_id in ("../escape", "/tmp/a", "bad", "f" * 33):
            with self.assertRaises(ValueError):
                u.rollback(self.skill, backup_id, approved=True)
        data = json.loads((self.skill / u.MANIFEST_NAME).read_text())
        data["repository"] = "attacker/repo"
        (self.skill / u.MANIFEST_NAME).write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            u.upgrade(self.skill)

    def test_lock_and_cache_root_symlink_are_rejected(self):
        lock = self.root / ".agent-team-runtime.update.lock"
        lock.mkdir()
        with self.assertRaises(ValueError):
            u.configure_updates(self.skill, enabled=False)
        lock.rmdir()
        (self.skill / ".cache").symlink_to(self.root)
        self.assertEqual(u.check_updates(self.skill)["status"], "unavailable")
        with self.assertRaises(ValueError):
            u._verify(self.skill)

    def test_redirect_restrictions(self):
        initial = release()["assets"][u.ASSET_NAME]
        handler = u._Redirects(initial, True)
        for target in ("http://github.com/a", "https://evil.test/a", "https://github.com/attacker/repo", "https://github.com:444/a", "https://user@github.com/a"):
            with self.assertRaises(ValueError):
                handler.redirect_request(None, None, 302, "redirect", {}, target)

    def test_current_version_and_no_downgrade(self):
        with patch.object(u, "_release", return_value=release("2.5.0")):
            self.assertEqual(u.check_updates(self.skill, now=100)["status"], "current")
            self.assertEqual(u.upgrade(self.skill, approved=True)["status"], "current")
        self.assertEqual(u._verify(self.skill)["version"], "2.6.0")

    def test_preview_does_not_acquire_writing_lock(self):
        with patch.object(u, "_release", return_value=release()), patch.object(u, "_lock", side_effect=AssertionError("write lock")):
            self.assertEqual(u.upgrade(self.skill)["status"], "preview")

    def test_automatic_check_complete_timeout(self):
        class StuckThread:
            def __init__(self, target, daemon):
                self.daemon = daemon
            def start(self):
                pass
            def join(self, timeout):
                self.timeout = timeout
        with patch.object(u.threading, "Thread", StuckThread):
            result = u.check_updates(self.skill, now=100)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("five seconds", result["error"])
        self.assertEqual(u.check_updates(self.skill, now=101)["status"], "skipped")

    def test_rollback_rejects_modified_current_and_backup(self):
        payload = bundle(self.root / "new")
        with patch.object(u, "_release", return_value=release()), patch.object(u, "_download", side_effect=self.download(payload)):
            result = u.upgrade(self.skill, approved=True)
        current = self.skill / "SKILL.md"
        original = current.read_bytes()
        current.write_text("local changes")
        with self.assertRaises(ValueError):
            u.rollback(self.skill, result["backup_id"], approved=True)
        current.write_bytes(original)
        backup = self.root / ".agent-team-runtime.backups" / result["backup_id"]
        (backup / "SKILL.md").write_text("backup changes")
        with self.assertRaises(ValueError):
            u.rollback(self.skill, result["backup_id"], approved=True)
        self.assertEqual(u._verify(self.skill)["version"], "2.7.0")

    def test_manifest_duplicate_and_unsafe_paths(self):
        manifest_path = self.skill / u.MANIFEST_NAME
        original = manifest_path.read_text()
        manifest_path.write_text(original[:-1] + ', "version": "2.6.0"}')
        with self.assertRaises(ValueError):
            u._manifest(self.skill)
        for path in ("../evil", "/evil", "scripts/../evil", "C:/evil", ".cache/a", "scripts\\a"):
            data = json.loads(original)
            data["files"][path] = "a" * 64
            manifest_path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                u._manifest(self.skill)

    def test_outside_cache_symlink_is_rejected(self):
        (self.skill / "link").symlink_to(self.root / "outside")
        with self.assertRaises(ValueError):
            u.upgrade(self.skill, approved=True)

    def test_excessive_archive_entries(self):
        payload = bundle(self.root / "new")
        with patch.object(u, "MAX_FILES", 1):
            with self.assertRaisesRegex(ValueError, "too many"):
                u._extract(payload, self.root / "stage", "2.7.0")

    def test_cli_status_and_error(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(u.main(["status"], skill=self.skill), 0)
        self.assertEqual(json.loads(output.getvalue())["installed_version"], "2.6.0")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(u.main(["configure", "--snooze-days", "-1"], skill=self.skill), 2)


if __name__ == "__main__":
    unittest.main()
