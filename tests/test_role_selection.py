"""User choices and installation previews stay separate from approval and invocation."""
import json
from pathlib import Path
from unittest.mock import patch

from agent_team.cli import main
from agent_team.marketplace import generate_role
from agent_team.runtime import plan_task
from agent_team.storage import read_yaml


def invoke(root, capsys, *args):
    assert main(['--project', str(root), '--platform', 'generic', *args]) == 0
    output = capsys.readouterr()
    return json.loads(output.out)


def recommend(root, capsys):
    flags = ['role', 'recommend', '--query', '优化界面 UI UX', '--library', 'agency']
    request = invoke(root, capsys, *flags)
    candidates = request['candidates'][:2]
    assert len(candidates) == 2
    assessment = root / 'assessment.json'
    assessment.write_text(json.dumps({'request_id': request['request_id'], 'matches': [
        {'id': role['id'], 'relevance': .8 + i * .1, 'reason': 'UI design specialist for this task.',
         'evidence': [{'field': 'name', 'quote': role['name']}]}
        for i, role in enumerate(candidates)]}), encoding='utf-8')
    return flags, invoke(root, capsys, *flags, '--assessment', str(assessment))


def test_library_choices_and_cached_judgment_do_not_install(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'empty-home')
    invoke(tmp_path, capsys, 'init')
    team = (tmp_path / '.agent-team/team.yaml').read_bytes()
    with patch('agent_team.agency.fetch_role', side_effect=AssertionError('No selected profile yet')):
        flags, result = recommend(tmp_path, capsys)
        choice = result['selection']
        assert choice['requires_user_response'] and choice['default_selection'] is None
        assert choice['selection_grants_installation'] is False
        assert [item['role_id'] for item in choice['options'][:-1]] == [
            role['id'] for role in result['recommendations']]
        assert all(item['action'] == 'preview_install' and item['installation_required']
                   and not item['native_available'] for item in choice['options'][:-1])
        assert choice['options'][-1]['action'] == 'skip'
        cached = invoke(tmp_path, capsys, *flags)
        assert cached['cache_hit'] and cached['selection'] == choice
    assert (tmp_path / '.agent-team/team.yaml').read_bytes() == team
    assert not list((tmp_path / '.agent-team/roles').glob('*'))


def test_chosen_preview_requires_confirmation_then_only_that_role_is_installed(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'empty-home')
    invoke(tmp_path, capsys, 'init')
    _, result = recommend(tmp_path, capsys)
    chosen, other = result['selection']['options'][:2]
    profile = dict(generate_role(chosen['role_id'], chosen['label'], ['ui-design']), source='agency')
    team = (tmp_path / '.agent-team/team.yaml').read_bytes()
    with patch('agent_team.agency.fetch_role', return_value=profile):
        preview = invoke(tmp_path, capsys, 'role', 'install', '--agency', chosen['role_id'])
        confirmation = preview['confirmation']
        assert confirmation['role_id'] == chosen['role_id']
        assert confirmation['target'] == preview['target']
        assert confirmation['permissions'] == preview['permissions']
        assert confirmation['requires_user_response'] and confirmation['default_selection'] is None
        assert [item['id'] for item in confirmation['options']] == ['install', 'cancel']
        assert not preview['installed'] and not (tmp_path / preview['target']).exists()
        assert (tmp_path / '.agent-team/team.yaml').read_bytes() == team
        # No approval (including cancellation) leaves project definitions unchanged.
        assert not invoke(tmp_path, capsys, 'role', 'install', '--agency', chosen['role_id'])['installed']
        installed = invoke(tmp_path, capsys, 'role', 'install', '--agency', chosen['role_id'], '--approve')
    assert installed['installed'] and installed['status'] == 'unavailable'
    members = read_yaml(tmp_path / '.agent-team/team.yaml')['team']['members']
    assert sum(member['id'] == chosen['role_id'] for member in members) == 1
    assert all(member['id'] != other['role_id'] for member in members)
    # Installation supplies real specialist instructions even before native discovery.
    spec = {'title': 'Improve UI', 'scores': dict.fromkeys(
        ['independence', 'complexity', 'specialization', 'parallel_benefit'], 50),
        'work_items': [{'id': 'ui', 'role': profile['id'], 'goal': 'Improve UI',
                        'capabilities': ['ui-design'], 'deliverables': ['UI changes'],
                        'write_scope': ['public/']}]}
    planned = plan_task(tmp_path, spec, host={'native_subagents': True,
        'evidence': 'Actual tool inventory', 'available_agents': ['Implementation Engineer']})
    assert planned['execution']['strategy'] == 'sequential_handoffs'
    assert not planned['execution']['capability_gaps']
    assert profile['prompt'] in planned['execution']['handoffs'][0]['prompt']


def test_existing_role_is_offered_for_reuse_and_no_match_has_no_selection(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'empty-home')
    invoke(tmp_path, capsys, 'init')
    flags = ['role', 'recommend', '--query', 'implementation']
    request = invoke(tmp_path, capsys, *flags)
    role = request['candidates'][0]
    assessment = tmp_path / 'assessment.json'
    data = {'request_id': request['request_id'], 'matches': [
        {'id': role['id'], 'relevance': .9, 'reason': 'Existing member covers this work.',
         'evidence': [{'field': 'name', 'quote': role['name']}]}]}
    assessment.write_text(json.dumps(data), encoding='utf-8')
    result = invoke(tmp_path, capsys, *flags, '--assessment', str(assessment))
    option = result['selection']['options'][0]
    assert option['action'] == 'reuse' and not option['installation_required']
    data['matches'] = []
    assessment.write_text(json.dumps(data), encoding='utf-8')
    result = invoke(tmp_path, capsys, *flags, '--assessment', str(assessment))
    assert result['recommendations'] == [] and result['selection'] is None
