"""Observable retrieval/assessment/install behavior across module boundaries."""
import copy
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from agent_team.cli import main
from agent_team.installer import export_bundle
from agent_team.marketplace import build_catalog, generate_role, install_role
from agent_team.recommendation import compact_request, assessed_request
from agent_team.storage import bootstrap, read_yaml


def invoke(root, capsys, *args):
    code = main(['--project', str(root), '--platform', 'generic', *args])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    return json.loads(captured.out)


def judgment(request, role):
    return {'request_id': request['request_id'], 'matches': [
        {'id': role['id'], 'relevance': .9, 'reason': 'Role responsibilities cover the requested work.',
         'evidence': [{'field': 'name', 'quote': role['name']}]}]}


def test_compact_request_binds_unselected_inventory_and_omits_prompts():
    roles = [dict(generate_role('role-%s' % i, 'Specialist %s' % i, ['security']),
                  status='installable', platform_compatible=True) for i in range(30)]
    roles[0]['prompt'] = 'PRIVATE FULL PROMPT ' * 4000
    request = compact_request(roles, 'security')
    assert len(request['candidates']) == 6
    assert 'PRIVATE FULL PROMPT' not in json.dumps(request)
    assert all(not card['prompt'] for card in request['candidates'])
    selected = {card['id'] for card in request['candidates']}
    other = next(role for role in roles if role['id'] not in selected)
    other['prompt'] += ' changed'
    current = compact_request(roles, 'security')
    assert current['request_id'] != request['request_id']
    assert {card['id'] for card in current['candidates']} == selected
    assert compact_request(roles, 'unknown topic')['retrieval']['lexical_fallback_page']
    assert {card['id'] for card in compact_request(roles, 'security', offset=6)['candidates']}.isdisjoint(selected)


def test_cache_reuses_only_validated_same_inventory_judgments(tmp_path):
    role = dict(generate_role('audit', 'Auditor', ['security']), status='installable')
    request = compact_request([role], 'audit security')
    assert assessed_request(tmp_path, [role], request) == request
    assert not list(tmp_path.iterdir())
    result = assessed_request(tmp_path, [role], request, judgment(request, role))
    assert not result['cache_hit'] and result['recommendations'][0]['prompt'] == ''
    assert assessed_request(tmp_path, [role], request)['cache_hit']
    changed = dict(role, prompt='different instructions')
    current = compact_request([changed], 'audit security')
    assert assessed_request(tmp_path, [changed], current)['status'] == 'awaiting_host_assessment'
    cached = next((tmp_path / '.agent-team/cache/recommendations').glob('*.json'))
    cached.write_text('{malformed')
    assert assessed_request(tmp_path, [role], request)['status'] == 'awaiting_host_assessment'
    bad = judgment(request, role)
    bad['matches'][0]['id'] = 'invented'
    with pytest.raises(ValueError, match='Unknown'):
        assessed_request(tmp_path, [role], request, bad)


def test_cli_existing_first_then_library_and_cache(tmp_path, capsys, monkeypatch):
    # Isolate the host inventory from this developer's existing personal roles.
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'empty-home')
    invoke(tmp_path, capsys, 'init')
    request = invoke(tmp_path, capsys, 'role', 'recommend', '--query', 'database performance')
    assert all(card['source'] not in ('builtin', 'generated', 'agency') for card in request['candidates'])
    assert not (tmp_path / '.agent-team/cache/agency').exists()
    flags = ['role', 'recommend', '--query', '帮我排查慢 SQL', '--library', 'agency']
    request = invoke(tmp_path, capsys, *flags)
    assert 1 <= len(request['candidates']) <= 6
    assert all(card['prompt'] == '' for card in request['candidates'])
    assert request['candidates'][0]['id'] == 'agency-engineering-database-optimizer'
    data = judgment(request, request['candidates'][0])
    assessment = tmp_path / 'assessment.json'
    assessment.write_text(json.dumps(data))
    result = invoke(tmp_path, capsys, *flags, '--assessment', str(assessment))
    assert result['recommendations'][0]['score'] == 90
    assert invoke(tmp_path, capsys, *flags)['cache_hit']
    assert invoke(tmp_path, capsys, *flags, '--term', 'indexing')['status'] == 'awaiting_host_assessment'
    install_role(tmp_path, generate_role('local-db', 'Database Optimizer', ['database']), approved=True)
    fresh = invoke(tmp_path, capsys, *flags)
    assert fresh['status'] == 'awaiting_host_assessment'
    assert 'agency-engineering-database-optimizer' not in {card['id'] for card in fresh['candidates']}


def test_cli_agency_preview_install_and_provenance(tmp_path, capsys):
    invoke(tmp_path, capsys, 'init')
    profile = dict(generate_role('agency-test', 'Library Specialist', ['specialty']), source='agency',
                   upstream={'repository': 'msitarzewski/agency-agents', 'revision': 'a' * 40,
                             'path': 'engineering/test.md', 'sha256': 'b' * 64, 'license': 'MIT'})
    with patch('agent_team.agency.fetch_role', return_value=profile) as fetch:
        preview = invoke(tmp_path, capsys, 'role', 'install', '--agency', 'agency-test')
        assert not preview['installed'] and not (tmp_path / preview['target']).exists()
        result = invoke(tmp_path, capsys, 'role', 'install', '--agency', 'agency-test', '--approve', '--offline')
        fetch.assert_called_with(tmp_path, 'agency-test', platform='generic', offline=True)
    assert result['installed'] and result['status'] == 'unavailable'
    member = next(role for role in read_yaml(tmp_path / '.agent-team/team.yaml')['team']['members'] if role['id'] == profile['id'])
    assert member['upstream'] == profile['upstream']
    restored = next(role for role in build_catalog(tmp_path, sources=[]) if role['id'] == profile['id'])
    assert restored['upstream'] == profile['upstream']


def test_exported_bundle_retrieves_offline_from_unrelated_cwd(tmp_path):
    skill = tmp_path / 'skill'
    export_bundle(skill)
    package = skill / 'scripts/runtime/agent_team'
    assert (package / 'data/agency-index.json').is_file()
    assert (package / 'data/AGENCY-LICENSE.txt').is_file()
    project = tmp_path / 'project'
    project.mkdir()
    result = subprocess.run([sys.executable, str(skill / 'scripts/run.py'), '--project', str(project),
                             'role', 'recommend', '--query', '小红书营销', '--library', 'agency'],
                            cwd=str(tmp_path), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload['candidates'][0]['id'] == 'agency-marketing-xiaohongshu-specialist'
    # Exporting the exported bundle retains runtime data and never copies caches.
    second = tmp_path / 'second'
    export_bundle(second, package)
    assert (second / 'scripts/runtime/agent_team/data/agency-index.json').read_bytes() == (package / 'data/agency-index.json').read_bytes()


def test_library_excludes_installed_before_pagination(tmp_path, capsys, monkeypatch):
    from agent_team.agency import search_roles
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'empty-home')
    invoke(tmp_path, capsys, 'init')
    top = search_roles('marketing', limit=6)
    assert len(top) == 6
    for i, card in enumerate(top):
        install_role(tmp_path, generate_role('already-%s' % i, card['name'], ['marketing']), approved=True)
    request = invoke(tmp_path, capsys, 'role', 'recommend', '--query', 'marketing', '--library', 'agency')
    assert len(request['candidates']) == 6
    assert {card['id'] for card in request['candidates']}.isdisjoint({card['id'] for card in top})


def test_request_cache_binds_platform_and_host_even_if_profiles_equal(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'empty-home')
    flags = ['role', 'recommend', '--query', 'unrelated']
    generic = invoke(tmp_path, capsys, *flags)
    assert main(['--project', str(tmp_path), '--platform', 'codex', *flags]) == 0
    codex = json.loads(capsys.readouterr().out)
    assert generic['request_id'] != codex['request_id']
    host = tmp_path / 'host.json'
    host.write_text(json.dumps({'native_subagents': True, 'evidence': 'actual tools inventory', 'available_agents': []}))
    assert main(['--project', str(tmp_path), '--platform', 'generic', '--host', str(host), *flags]) == 0
    with_host = json.loads(capsys.readouterr().out)
    assert generic['request_id'] != with_host['request_id']


def test_incompatible_local_role_does_not_hide_compatible_library_role(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'empty-home')
    bootstrap(tmp_path, 'claude-code')
    role = generate_role('claude-db', 'Database Optimizer', ['database optimization'])
    role['platforms'] = ['claude-code']
    install_role(tmp_path, role, 'claude-code', approved=True)
    flags = ['--project', str(tmp_path), '--platform', 'codex', 'role', 'recommend',
             '--query', 'database optimization', '--library', 'agency']
    assert main(flags) == 0
    request = json.loads(capsys.readouterr().out)
    assert 'agency-engineering-database-optimizer' in {card['id'] for card in request['candidates']}
