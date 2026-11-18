"""Real exported runners expose updates without changing business protocols."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from agent_team import __version__
from agent_team.installer import export_bundle, MANIFEST_NAME, _files
from agent_team import updates

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('update_runner', ROOT / 'agent_team/skill/scripts/run.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class UpdateIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.skill = self.root / 'skill'
        export_bundle(self.skill)

    def invoke(self, *args):
        return subprocess.run([sys.executable, '-S', str(self.skill / 'scripts/run.py'), *args],
                              cwd=str(self.root), capture_output=True, encoding='utf-8', timeout=15)

    def test_manifest_matches_export_and_reexport(self):
        manifest = updates._verify(self.skill)
        self.assertEqual(manifest['version'], __version__)
        self.assertEqual(manifest['channel'], 'stable')
        self.assertEqual(manifest['files'], {name: hashlib.sha256(content).hexdigest()
                                          for name, content in _files().items()})
        second = self.root / 'second'
        export_bundle(second, self.skill / 'scripts/runtime/agent_team')
        self.assertEqual(updates._verify(second)['files'], manifest['files'])

    def test_standard_library_runner_controls_without_dependencies(self):
        result = self.invoke('update', 'status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['installed_version'], __version__)
        self.assertFalse((self.skill / '.cache').exists())
        result = self.invoke('update', 'configure', '--enabled', 'false')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'disabled')
        result = self.invoke('update', 'check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'disabled')
        result = self.invoke('update', 'configure', '--enabled', 'true', '--snooze-days', '30')
        self.assertEqual(json.loads(result.stdout)['status'], 'snoozed')

    def test_source_cli_updates_do_not_need_a_project(self):
        result = subprocess.run([sys.executable, '-m', 'agent_team', '--project', str(self.root / 'absent'),
                                 'update', '--skill', str(self.skill), 'status'],
                                cwd=str(ROOT), capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['installed_version'], __version__)

    def test_update_notice_keeps_stdout_clean(self):
        notice = {'status': 'update_available', 'notify': True, 'latest_version': '9.0.0'}
        response = subprocess.CompletedProcess([], 0, json.dumps(notice), '')
        with patch.object(runner.subprocess, 'run', return_value=response) as run, \
                patch('sys.stderr', new_callable=io.StringIO) as stderr, \
                patch('sys.stdout', new_callable=io.StringIO) as stdout:
            runner.notify_update(self.skill)
        self.assertEqual(stdout.getvalue(), '')
        self.assertEqual(json.loads(stderr.getvalue())['agent_team_update'], notice)
        self.assertEqual(run.call_args.kwargs['timeout'], 8)

    def test_update_notice_failure_cannot_fail_business(self):
        with patch.object(runner.subprocess, 'run', side_effect=subprocess.TimeoutExpired('check', 8)), \
                patch('sys.stderr', new_callable=io.StringIO) as stderr:
            runner.notify_update(self.skill)
        self.assertEqual(stderr.getvalue(), '')

    def test_only_successful_business_commands_check_updates(self):
        with patch.object(runner, 'locations', return_value=(self.skill, ROOT)), \
                patch.object(runner, 'select_python', return_value=Path(sys.executable)), \
                patch.object(runner.subprocess, 'run') as run, \
                patch.object(runner, 'notify_update') as notify:
            for args, result_code, expected in [(['status'], 0, True), (['status'], 2, False),
                                                 (['--version'], 0, False), (['guide'], 0, False),
                                                 (['--help'], 0, False)]:
                run.return_value = subprocess.CompletedProcess([], result_code)
                notify.reset_mock()
                self.assertEqual(runner.main(args), result_code)
                self.assertEqual(notify.called, expected)

    def test_new_install_check_stays_offline_until_due(self):
        with patch.object(updates, '_release', side_effect=AssertionError('must stay offline')):
            self.assertEqual(updates.check_updates(self.skill)['status'], 'skipped')

    def test_real_runtime_upgrade_and_rollback_preserve_project(self):
        project = self.root / 'project'
        project.mkdir()
        (project / 'AGENTS.md').write_text('User instructions', encoding='utf-8')
        from agent_team.storage import bootstrap
        bootstrap(project, 'codex')
        protected = {p: p.read_bytes() for p in project.rglob('*') if p.is_file()}
        current = updates._manifest(self.skill)
        current.update(scope='user', platform='codex')
        (self.skill / MANIFEST_NAME).write_text(json.dumps(current), encoding='utf-8')
        future = self.root / 'future'
        export_bundle(future)
        major, minor, patch_version = map(int, __version__.split('.'))
        future_version = '{}.{}.{}'.format(major, minor, patch_version + 1)
        version_file = future / 'scripts/runtime/agent_team/__init__.py'
        version_file.write_text(version_file.read_text().replace(__version__, future_version), encoding='utf-8')
        metadata = updates._manifest(future)
        metadata['version'] = future_version
        metadata['files']['scripts/runtime/agent_team/__init__.py'] = hashlib.sha256(version_file.read_bytes()).hexdigest()
        (future / MANIFEST_NAME).write_text(json.dumps(metadata), encoding='utf-8')
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            for path in future.rglob('*'):
                if path.is_file():
                    archive.write(path, 'agent-team-runtime/' + path.relative_to(future).as_posix())
        payload = output.getvalue()
        release = {'version': future_version, 'url': 'https://github.com/' + updates.REPOSITORY + '/releases/tag/v' + future_version,
                   'release_notes': '', 'assets': {updates.ASSET_NAME: 'archive', updates.ASSET_NAME + '.sha256': 'digest'}}
        def download(url, limit, assets=False):
            return (hashlib.sha256(payload).hexdigest() + '  ' + updates.ASSET_NAME).encode() if url == 'digest' else payload
        with patch.object(updates, '_release', return_value=release), \
                patch.object(updates, '_download', side_effect=download):
            result = updates.upgrade(self.skill, approved=True)
        self.assertEqual(result['status'], 'upgraded')
        self.assertEqual(updates._manifest(self.skill)['scope'], 'user')
        self.assertEqual(self.invoke('--version').stdout.strip(), future_version)
        updates.rollback(self.skill, result['backup_id'], approved=True)
        self.assertEqual(self.invoke('--version').stdout.strip(), __version__)
        self.assertEqual(updates._manifest(self.skill)['platform'], 'codex')
        self.assertEqual({p: p.read_bytes() for p in project.rglob('*') if p.is_file()}, protected)


if __name__ == '__main__':
    unittest.main()
