"""Project instructions must remain usable after a checkout changes machines."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from agent_team.adapters import PLATFORMS, entry_path, entry_text, render_role
from agent_team.installer import export_bundle
from agent_team.marketplace import build_catalog
from agent_team.storage import bootstrap, write_yaml


@pytest.mark.parametrize('platform', PLATFORMS)
def test_entry_never_embeds_installed_skill_location(tmp_path, monkeypatch, platform):
    monkeypatch.delenv('AGENT_TEAM_SKILL_ROOT', raising=False)
    expected = entry_text(platform)
    skill = tmp_path / 'personal-installation'
    skill.mkdir()
    (skill / 'SKILL.md').write_text('Installed workflow', encoding='utf-8')
    monkeypatch.setenv('AGENT_TEAM_SKILL_ROOT', str(skill))
    assert entry_text(platform) == expected
    assert str(skill) not in expected
    expected_skill = {
        'claude-code': '.claude/skills/agent-team-runtime/SKILL.md',
        'trae': '.trae/skills/agent-team-runtime/SKILL.md',
    }.get(platform, '.agents/skills/agent-team-runtime/SKILL.md')
    assert expected_skill in expected
    assert 'agent_team/skill/SKILL.md' in expected
    bootstrap(tmp_path, platform)
    assert (tmp_path / entry_path(platform)).read_text(encoding='utf-8') == expected


@pytest.mark.parametrize('platform,skill_dir', [
    ('trae', '.trae/skills'), ('pi', '.agents/skills'),
])
def test_skill_host_entry_and_role_use_official_project_directories(tmp_path, platform, skill_dir):
    entry = entry_text(platform)
    profile = {'id': 'ui-designer', 'name': 'UI Designer',
               'description': 'Design accessible interfaces',
               'capabilities': ['interaction-design', 'accessibility'],
               'deliverables': ['design system', 'usability review'],
               'prompt': 'Produce a design system and review the UI.'}
    rendered = render_role(profile, platform)
    assert entry.startswith('---\nalwaysApply: true\n---') if platform == 'trae' else entry.startswith('<!--')
    assert skill_dir + '/agent-team-runtime/SKILL.md' in entry
    assert rendered['path'] == skill_dir + '/ui-designer/SKILL.md'
    assert 'agent_team_role_id: ui-designer' in rendered['content']
    assert 'Produce a design system' in rendered['content']
    skill_path = tmp_path / rendered['path']
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(rendered['content'], encoding='utf-8')
    installed = next(role for role in build_catalog(tmp_path, platform, sources=[])
                     if role['id'] == 'ui-designer')
    assert installed['capabilities'] == profile['capabilities']
    assert installed['deliverables'] == profile['deliverables']


def test_workbuddy_is_explicitly_an_import_skill_not_a_native_rule():
    entry = entry_text('workbuddy')
    rendered = render_role({'id': 'ui-designer', 'name': 'UI Designer',
                            'description': 'Design accessible interfaces',
                            'prompt': 'Produce a design system and review the UI.'}, 'workbuddy')
    assert 'Skills UI' in entry
    assert rendered['path'] == '.agent-team/workbuddy-imports/ui-designer/SKILL.md'
    assert 'agent_team_role_id: ui-designer' in rendered['content']


def test_runner_entries_are_identical_across_installations(tmp_path):
    entries = []
    for name in ('first-machine', 'second-machine'):
        base = tmp_path / name
        skill = base / 'skill'
        export_bundle(skill)
        project = base / 'project'
        project.mkdir()
        # Preserve required system environment while exercising the legacy hint.
        env = dict(os.environ, AGENT_TEAM_SKILL_ROOT=str(skill))
        result = subprocess.run([sys.executable, str(skill / 'scripts/run.py'),
                                 '--project', str(project), '--platform', 'codex', 'init'],
                                cwd=str(tmp_path), env=env, capture_output=True, encoding='utf-8')
        assert result.returncode == 0, result.stderr
        content = (project / 'AGENTS.md').read_text(encoding='utf-8')
        assert str(base) not in content
        entries.append(content)
    assert entries[0] == entries[1]


def test_repository_entry_matches_portable_template():
    root = Path(__file__).resolve().parents[1]
    assert (root / 'AGENTS.md').read_text(encoding='utf-8') == entry_text('codex')


@pytest.mark.parametrize('platform', PLATFORMS)
def test_explicit_entry_upgrade_preserves_team_and_records(tmp_path, platform):
    team = bootstrap(tmp_path, platform)
    entry = tmp_path / entry_path(platform)
    original = entry.read_text(encoding='utf-8')
    begin, end = '<!-- agent-team-runtime:begin -->', '<!-- agent-team-runtime:end -->'
    # Simulate an older entry without changing the host-specific frontmatter.
    prefix = original[:original.index(begin)] + 'User-owned instructions\n'
    suffix = '\nUser-owned footer\n'
    entry.write_text(prefix + begin + '\nOld routing\n' + end + suffix, encoding='utf-8')
    paths = [tmp_path / '.agent-team' / path for path in (
        'team.yaml', 'orchestration.yaml', 'members/custom.md', 'tasks/history.md', 'memory/fact.md')]
    for path in paths[2:]:
        path.write_text('Preserved project data: ' + path.name, encoding='utf-8')
    snapshot = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    managed = begin + entry_text(platform).split(begin, 1)[1].rstrip('\n')
    for _ in range(2):
        assert bootstrap(tmp_path, platform) == team
        assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths} == snapshot
        assert entry.read_text(encoding='utf-8') == prefix + managed + suffix


def test_fresh_processes_plan_with_existing_team_without_reinitializing(tmp_path):
    skill = tmp_path / 'skill'
    export_bundle(skill)
    project = tmp_path / 'project'
    project.mkdir()
    team = bootstrap(project, 'codex')
    member = team['team']['members'][0]
    member['definition'] = '.agent-team/members/implementer.md'
    (project / member['definition']).write_text('Existing specialist instructions.', encoding='utf-8')
    write_yaml(project / '.agent-team/team.yaml', team)
    protected = [project / 'AGENTS.md', project / '.agent-team/team.yaml',
                 project / '.agent-team/orchestration.yaml', project / member['definition']]
    snapshot = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in protected}
    spec = tmp_path / 'task.yaml'
    write_yaml(spec, {'title': 'Implement a bounded API change',
                     'scores': dict.fromkeys(('independence', 'complexity', 'specialization', 'parallel_benefit'), 60),
                     'work_items': [{'id': 'api', 'role': 'implementer', 'goal': 'Implement API',
                                     'deliverables': ['verified patch'], 'write_scope': ['src/']}]})
    records = []
    for _ in range(2):
        # Each runner invocation is a separate process, with no preceding init/status/doctor.
        result = subprocess.run([sys.executable, str(skill / 'scripts/run.py'), '--project', str(project),
                                 'plan', str(spec)], cwd=str(tmp_path), capture_output=True, encoding='utf-8')
        assert result.returncode == 0, result.stderr
        record = json.loads(result.stdout)
        assert record['execution']['capability_gaps'] == []
        assert 'Existing specialist instructions.' in record['execution']['handoffs'][0]['prompt']
        records.append(record['task']['id'])
        assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in protected} == snapshot
    assert records[0] != records[1]
    assert all((project / '.agent-team/tasks' / (identifier + '.yaml')).exists() for identifier in records)
