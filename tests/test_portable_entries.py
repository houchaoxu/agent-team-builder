"""Project instructions must remain usable after a checkout changes machines."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from agent_team.adapters import PLATFORMS, entry_path, entry_text
from agent_team.installer import export_bundle
from agent_team.storage import bootstrap


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
    assert '.agents/skills/agent-team-runtime/SKILL.md' in expected
    assert 'agent_team/skill/SKILL.md' in expected
    bootstrap(tmp_path, platform)
    assert (tmp_path / entry_path(platform)).read_text(encoding='utf-8') == expected


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
