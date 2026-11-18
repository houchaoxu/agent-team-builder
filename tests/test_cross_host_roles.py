"""Other hosts' personal roles are importable material, not installed members."""
import json
from pathlib import Path

import pytest

from agent_team.adapters import render_role
from agent_team.cli import main
from agent_team.marketplace import build_catalog, generate_role
from agent_team.recommendation import apply_assessment, compact_request
from agent_team.storage import bootstrap, read_yaml


def write_personal(home, role, platform):
    rendered = render_role(role, platform)
    path = home / rendered['path']
    path.parent.mkdir(parents=True, exist_ok=True)
    # Real upstream/personal profiles use human names rather than rendered IDs.
    content = rendered['content'].replace('name: ' + role['id'] + '\n', 'name: ' + role['name'] + '\n')
    content = content.replace('name = ' + json.dumps(role['id']), 'name = ' + json.dumps(role['name']))
    path.write_text(content, encoding='utf-8')
    return path


def invoke(root, capsys, *args):
    assert main(['--project', str(root), '--platform', 'codex', *args]) == 0
    captured = capsys.readouterr()
    return json.loads(captured.out)


@pytest.mark.parametrize('platform', ['codex', 'claude-code', 'cursor', 'gemini-cli', 'generic'])
def test_other_host_material_remains_installable(tmp_path, monkeypatch, platform):
    home, root = tmp_path / 'home', tmp_path / 'project'
    root.mkdir()
    monkeypatch.setattr(Path, 'home', lambda: home)
    origin = 'claude-code' if platform != 'claude-code' else 'codex'
    profile = generate_role('ui-designer', 'UI Designer', ['ui design'])
    original = write_personal(home, profile, origin)
    source = original.read_bytes()
    role = next(item for item in build_catalog(root, platform) if item['id'] == profile['id'])
    assert role['status'] == 'installable'
    assert role['source_platform'] == origin
    assert role['installation_required'] and not role['installed_for_platform']
    assert not role['native_available']
    request = compact_request([role], 'UI design')
    card = request['candidates'][0]
    assert card['installation_required'] and card['source_platform'] == origin
    result = apply_assessment([role], request, {'request_id': request['request_id'], 'matches': [
        {'id': role['id'], 'relevance': .9, 'reason': 'UI expertise fits this task.',
         'evidence': [{'field': 'name', 'quote': role['name']}]}]})
    option = result['selection']['options'][0]
    assert option['action'] == 'preview_install' and option['source_platform'] == origin
    assert original.read_bytes() == source and not list(root.iterdir())


@pytest.mark.parametrize('platform,other', [('codex', 'claude-code'), ('claude-code', 'codex')])
def test_current_host_definition_wins_over_duplicate_other_host(tmp_path, monkeypatch, platform, other):
    home, root = tmp_path / 'home', tmp_path / 'project'
    root.mkdir()
    monkeypatch.setattr(Path, 'home', lambda: home)
    role = generate_role('ui-designer', 'UI Designer', ['ui design'])
    write_personal(home, dict(role, prompt='Other host instructions'), other)
    write_personal(home, dict(role, prompt='Current host instructions'), platform)
    chosen = next(item for item in build_catalog(root, platform) if item['id'] == role['id'])
    assert chosen['prompt'] == 'Current host instructions'
    assert chosen['source_platform'] == platform
    assert chosen['status'] == 'unavailable' and not chosen['native_available']
    assert chosen['installed_for_platform'] and not chosen['installation_required']


def test_other_host_names_do_not_hide_agency_candidates(tmp_path, monkeypatch, capsys):
    home, root = tmp_path / 'home', tmp_path / 'project'
    root.mkdir()
    monkeypatch.setattr(Path, 'home', lambda: home)
    profile = generate_role('design-ui-designer', 'UI Designer', ['ui design'])
    write_personal(home, profile, 'claude-code')
    flags = ['role', 'recommend', '--query', 'UI Designer', '--library', 'agency']
    result = invoke(root, capsys, *flags)
    assert 'agency-design-ui-designer' in {card['id'] for card in result['candidates']}
    # A definition installed for the target host is still deduplicated.
    write_personal(home, profile, 'codex')
    result = invoke(root, capsys, *flags)
    assert 'agency-design-ui-designer' not in {card['id'] for card in result['candidates']}


def test_import_preview_confirm_and_reuse_preserve_other_host(tmp_path, monkeypatch, capsys):
    home, root = tmp_path / 'home', tmp_path / 'project'
    root.mkdir()
    monkeypatch.setattr(Path, 'home', lambda: home)
    bootstrap(root, 'codex')
    role = generate_role('design-ui-designer', 'UI Designer', ['ui design'])
    original = write_personal(home, role, 'claude-code')
    source = original.read_bytes()
    shown = invoke(root, capsys, 'role', 'show', role['id'])
    profile = tmp_path / 'import.json'
    profile.write_text(json.dumps(shown), encoding='utf-8')
    team = (root / '.agent-team/team.yaml').read_bytes()
    preview = invoke(root, capsys, 'role', 'install', str(profile))
    assert not preview['installed'] and preview['confirmation']['role_id'] == role['id']
    assert not (root / preview['target']).exists()
    assert (root / '.agent-team/team.yaml').read_bytes() == team
    installed = invoke(root, capsys, 'role', 'install', str(profile), '--approve')
    assert installed['installed'] and installed['status'] == 'unavailable'
    assert (root / installed['target']).is_file() and original.read_bytes() == source
    selected = next(item for item in build_catalog(root, 'codex') if item['id'] == role['id'])
    assert selected['installed_for_platform'] and not selected['installation_required']
    assert selected['prompt'] == role['prompt']
    member = next(item for item in read_yaml(root / '.agent-team/team.yaml')['team']['members'] if item['id'] == role['id'])
    assert member['definition'] == installed['target']
