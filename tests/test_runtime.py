import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_team.runtime import (add_memory, analytics, get_task, plan_task,
                                read_memory, update_memory, update_task)
from agent_team.storage import (bootstrap, discover_root, read_yaml, safe_path,
                                validate_team, write_yaml)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.team = bootstrap(self.root)

    def spec(self, score=80, items=None):
        return {'title': 'Implement a bounded change', 'scores': dict.fromkeys(
            ('independence', 'complexity', 'specialization', 'parallel_benefit'), score),
            'acceptance_criteria': ['Focused verification passes'], 'work_items': items or []}

    def item(self, identifier, scope, deps=None):
        return {'id': identifier, 'role': 'implementer', 'goal': 'Change ' + identifier,
                'deliverables': ['verified patch'], 'write_scope': [scope], 'depends_on': deps or []}

    def test_bootstrap_preserves_existing_entry_and_recovers_directories(self):
        entry = self.root / 'AGENTS.md'
        entry.write_text('User instructions', encoding='utf8')
        tasks = self.root / '.agent-team/tasks'
        tasks.rmdir()
        self.assertEqual(bootstrap(self.root), self.team)
        self.assertTrue(tasks.is_dir())
        self.assertTrue(entry.read_text().startswith('User instructions'))
        self.assertEqual(entry.read_text().count('<!-- agent-team-runtime:begin -->'), 1)
        bootstrap(self.root)
        self.assertEqual(entry.read_text().count('<!-- agent-team-runtime:begin -->'), 1)
        nested = self.root / 'nested'
        nested.mkdir()
        self.assertEqual(discover_root(nested), self.root.resolve())

    def test_corrupt_config_is_never_recreated(self):
        config = self.root / '.agent-team/team.yaml'
        config.write_text('team: [broken', encoding='utf8')
        with self.assertRaises(ValueError):
            bootstrap(self.root)
        self.assertEqual(config.read_text(), 'team: [broken')

    def test_malformed_entry_marker_is_not_overwritten(self):
        entry = self.root / 'AGENTS.md'
        original = 'User instructions\n<!-- agent-team-runtime:begin -->\nIncomplete block'
        entry.write_text(original, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'invalid runtime markers'):
            bootstrap(self.root)
        self.assertEqual(entry.read_text(encoding='utf-8'), original)

    def test_simple_plan_does_not_load_configuration_or_memory(self):
        with patch('agent_team.runtime.read_yaml', side_effect=AssertionError('unexpected read')), \
                patch('agent_team.runtime.read_memory', side_effect=AssertionError('unexpected memory read')), \
                patch('agent_team.marketplace.build_catalog', side_effect=AssertionError('unexpected role scan')):
            record = plan_task(self.root, self.spec(20))
        self.assertEqual(record['execution']['mode'], 'single_agent')
        self.assertEqual(record['execution']['agents'], [])
        self.assertTrue(all(v is None for v in record['metrics'].values()))

    def test_complex_tasks_load_only_selected_roles_without_marketplace(self):
        member = self.team['team']['members'][0]
        member['definition'] = '.agent-team/members/implementer.md'
        (self.root / member['definition']).write_text('Selected implementation guidance.', encoding='utf-8')
        # A missing definition must not be opened when its member is not selected.
        self.team['team']['members'].append({
            'id': 'unused', 'role': 'Unused role',
            'definition': '.agent-team/members/not-installed.md'})
        write_yaml(self.root / '.agent-team/team.yaml', self.team)
        with patch('agent_team.marketplace.build_catalog', side_effect=AssertionError('unexpected role scan')), \
                patch('agent_team.runtime.read_memory', side_effect=AssertionError('unexpected memory read')), \
                patch('agent_team.runtime.read_yaml', wraps=read_yaml) as reads:
            record = plan_task(self.root, self.spec(items=[self.item('a', 'src/a')]))
        self.assertEqual(record['execution']['capability_gaps'], [])
        self.assertEqual(len(record['execution']['handoffs']), 1)
        self.assertIn('Selected implementation guidance.', record['execution']['handoffs'][0]['prompt'])
        self.assertEqual({call.args[0].resolve() for call in reads.call_args_list}, {
            (self.root / '.agent-team/team.yaml').resolve(),
            (self.root / '.agent-team/orchestration.yaml').resolve()})

    def test_modes_and_conservative_execution(self):
        items = [self.item('a', 'src/a'), self.item('b', 'src/b')]
        assisted = plan_task(self.root, self.spec(50, items))
        self.assertEqual(assisted['execution']['mode'], 'assisted')
        self.assertEqual(assisted['execution']['strategy'], 'sequential_handoffs')
        host = {'native_subagents': True, 'evidence': 'active API inventory',
                'available_agents': ['implementer'], 'max_parallel_agents': 10}
        parallel = plan_task(self.root, self.spec(80, items), host)
        self.assertEqual(parallel['execution']['strategy'], 'native_subagents')
        self.assertEqual(parallel['execution']['batches'], [['a', 'b']])
        host['native_subagents'] = 'true'
        self.assertEqual(plan_task(self.root, self.spec(80, items), host)['execution']['strategy'],
                         'sequential_handoffs')

    def test_configured_limits_and_thresholds_are_used(self):
        self.team['orchestration'] = {'thresholds': {'assisted': 40, 'multi_agent': 90}, 'max_parallel_agents': 1}
        write_yaml(self.root / '.agent-team/orchestration.yaml', self.team['orchestration'])
        self.assertEqual(plan_task(self.root, self.spec(80))['execution']['mode'], 'assisted')
        host = {'native_subagents': True, 'evidence': 'tool inventory', 'available_agents': ['implementer']}
        result = plan_task(self.root, self.spec(95, [self.item('a', 'a'), self.item('b', 'b')]), host)
        self.assertEqual(result['execution']['batches'], [['a'], ['b']])

    def test_dependency_and_overlap_validation(self):
        with self.assertRaises(ValueError):
            plan_task(self.root, self.spec(items=[self.item('a', 'src'), self.item('b', 'src/x')]))
        serial = plan_task(self.root, self.spec(items=[self.item('a', 'src'), self.item('b', 'src/x', ['a'])]))
        self.assertEqual(serial['execution']['batches'], [['a'], ['b']])
        for items in ([self.item('a', 'a', ['missing'])],
                      [self.item('a', 'a', ['b']), self.item('b', 'b', ['a'])]):
            with self.assertRaises(ValueError):
                plan_task(self.root, self.spec(items=items))

    def test_no_delegation_without_deliverable_and_scope(self):
        item = self.item('a', 'src')
        item['deliverables'] = []
        result = plan_task(self.root, self.spec(items=[item]))
        self.assertEqual(result['execution']['agents'], [])
        self.assertEqual(result['execution']['strategy'], 'single_agent')

    def test_readonly_handoff_loads_selected_definition_and_agent_id(self):
        member = self.team['team']['members'][0]
        member['definition'] = '.agent-team/members/implementer.md'
        member['agent_id'] = 'native-implementation'
        definition = self.root / member['definition']
        definition.write_text('Inspect carefully; report actionable findings.', encoding='utf8')
        write_yaml(self.root / '.agent-team/team.yaml', self.team)
        item = self.item('review', 'ignored')
        item.update(read_only=True, write_scope=[])
        host = {'native_subagents': True, 'evidence': 'tool inventory', 'available_agents': ['native-implementation']}
        record = plan_task(self.root, self.spec(items=[item]), host)
        self.assertEqual(record['execution']['strategy'], 'native_subagents')
        self.assertIn('Inspect carefully', record['execution']['handoffs'][0]['prompt'])
        self.assertIn('read-only', record['execution']['handoffs'][0]['prompt'])
        member['definition'] = '../private.txt'
        write_yaml(self.root / '.agent-team/team.yaml', self.team)
        with self.assertRaises(ValueError):
            plan_task(self.root, self.spec(items=[item]), host)

    def test_corrupt_orchestration_is_not_replaced(self):
        path = self.root / '.agent-team/orchestration.yaml'
        path.write_text('thresholds: [broken', encoding='utf8')
        with self.assertRaises(ValueError):
            bootstrap(self.root)
        with self.assertRaises(ValueError):
            plan_task(self.root, self.spec())
        self.assertEqual(plan_task(self.root, self.spec(10))['execution']['mode'], 'single_agent')

    def test_safe_paths_and_identifiers(self):
        for value in ('../outside', '/tmp/outside'):
            with self.assertRaises(ValueError):
                safe_path(self.root, value)
        (self.root / 'escape').symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            safe_path(self.root, 'escape/outside')
        with self.assertRaises(ValueError):
            get_task(self.root, '../team')

    def test_state_evidence_metrics_and_isolation(self):
        record = plan_task(self.root, self.spec(10))
        identifier = record['task']['id']
        with self.assertRaises(ValueError):
            update_task(self.root, identifier, 'completed', summary='done')
        done = update_task(self.root, identifier, 'completed', 'verified',
                           metrics={'tokens': 42}, evidence={'command': 'unit tests', 'result': 'passed'})
        self.assertEqual(done['metrics']['tokens'], 42)
        self.assertIsNone(done['metrics']['cost'])
        with self.assertRaises(ValueError):
            update_task(self.root, identifier, 'running')
        other = self.root / 'other'
        other.mkdir()
        self.assertEqual(analytics(other)['total_tasks'], 0)
        self.assertEqual(analytics(self.root)['metrics']['tokens'], 42)
        plan_task(self.root, self.spec(10))
        self.assertIsNone(analytics(self.root)['metrics']['tokens'])

    def test_memory_sources_approval_and_deduplication(self):
        first = add_memory(self.root, 'experience', 'Useful fact', 'task:one')
        self.assertEqual(first, add_memory(self.root, 'experience', 'Useful fact', 'task:one'))
        add_memory(self.root, 'experience', 'Useful fact', 'task:two')
        self.assertEqual(len(read_memory(self.root, 'experience')['experience']), 2)
        with self.assertRaises(ValueError):
            add_memory(self.root, 'architecture', 'Decision', 'review')
        add_memory(self.root, 'architecture', 'Decision', 'review', approved=True)

    def test_invalid_yaml_and_duplicate_members(self):
        file = self.root / 'bad.yaml'
        file.write_text('[]', encoding='utf8')
        with self.assertRaises(ValueError):
            read_yaml(file)
        self.team['team']['members'] *= 2
        with self.assertRaises(ValueError):
            validate_team(self.team)

    def test_missing_roles_and_capabilities_are_retained_with_recommendations(self):
        unknown = self.item('a', 'src/a')
        unknown.update(role='security-specialist', capabilities=['security'])
        existing = self.item('b', 'src/b')
        existing['capabilities'] = ['database']
        record = plan_task(self.root, self.spec(items=[unknown, existing]))
        execution = record['execution']
        self.assertEqual(execution['agents'], [])
        self.assertEqual(execution['retained_by_main'], ['a', 'b'])
        self.assertEqual([gap['capabilities'] for gap in execution['capability_gaps']], [['security'], ['database']])
        self.assertTrue(all(len(gap['recommendations']) <= 3 for gap in execution['capability_gaps']))
        self.assertIn('role recommend', execution['capability_gaps'][0]['next_steps'][0])
        semantic = execution['capability_gaps'][1]['semantic_request']
        self.assertEqual(semantic['status'], 'awaiting_host_assessment')
        self.assertTrue(semantic['candidates'])
        self.assertIn(existing['goal'], semantic['query'])
        self.assertEqual(semantic['exact_fallback'], [])
        # The same unknown role does not trigger team or catalog reads for simple work.
        with patch('agent_team.runtime.read_yaml', side_effect=AssertionError('unexpected read')):
            simple = plan_task(self.root, self.spec(10, [unknown]))
        self.assertEqual(simple['execution']['retained_by_main'], ['a'])

    def test_parallel_requires_positive_scores_and_two_ready_delegations(self):
        items = [self.item('a', 'src/a'), self.item('b', 'src/b')]
        host = {'native_subagents': True, 'evidence': 'API inventory', 'available_agents': ['implementer']}
        for field in ('independence', 'parallel_benefit'):
            spec = self.spec(100, items)
            spec['scores'][field] = 0
            record = plan_task(self.root, spec, host)
            self.assertEqual(record['execution']['mode'], 'assisted')
            self.assertEqual(record['execution']['batches'], [['a'], ['b']])
        serial = [self.item('a', 'src/a'), self.item('b', 'src/b', ['a'])]
        record = plan_task(self.root, self.spec(100, serial), host)
        self.assertEqual(record['execution']['mode'], 'assisted')
        self.assertEqual(record['execution']['batches'], [['a'], ['b']])

    def test_memory_updates_keep_content_source_and_revision_history(self):
        original = add_memory(self.root, 'experience', 'Old behavior', 'task:one')
        updated = update_memory(self.root, 'experience', original['id'], 'New behavior', 'task:two')
        self.assertEqual(updated['revision'], 2)
        self.assertEqual(updated['history'][0]['text'], 'Old behavior')
        self.assertEqual(updated['history'][0]['source'], 'task:one')
        self.assertEqual(updated['created_at'], original['created_at'])
        self.assertEqual(updated, update_memory(self.root, 'experience', original['id'], 'New behavior', 'task:two'))
        third = update_memory(self.root, 'experience', original['id'], 'Latest behavior', 'task:three')
        self.assertEqual([entry['revision'] for entry in third['history']], [1, 2])
        self.assertEqual(third['revision'], 3)
        self.assertEqual(read_memory(self.root, 'experience')['experience'][0], third)
        decision = add_memory(self.root, 'decisions', 'Old decision', 'review', approved=True)
        with self.assertRaises(ValueError):
            update_memory(self.root, 'decisions', decision['id'], 'New decision', 'review-two')
        self.assertEqual(read_memory(self.root, 'decisions')['decisions'][0], decision)

    def test_analytics_retains_measured_values_and_groups_role_combinations(self):
        first = plan_task(self.root, self.spec(10))
        second = plan_task(self.root, self.spec(10))
        update_task(self.root, first['task']['id'], 'completed', 'verified',
                    {'tokens': 42}, {'command': 'focused test', 'result': 'passed'})
        update_task(self.root, second['task']['id'], 'failed', 'build failed')
        result = analytics(self.root)
        self.assertIsNone(result['metrics']['tokens'])
        self.assertEqual(result['metric_coverage']['tokens'],
                         {'known_total': 42, 'measured': 1, 'missing': 1, 'coverage': .5})
        group = result['role_combinations'][0]
        self.assertEqual(group['roles'], ['main'])
        self.assertEqual(group['task_count'], 2)
        self.assertEqual(group['statuses']['completed'], 1)
        self.assertEqual(group['statuses']['failed'], 1)
        self.assertEqual(len(group['results']), 2)
        self.assertEqual(group['metric_coverage']['tokens']['known_total'], 42)


if __name__ == '__main__':
    unittest.main()
