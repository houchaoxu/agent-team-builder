"""Deterministic planning and records; execution remains a host responsibility."""
from datetime import datetime, timezone
import math
from pathlib import Path
import uuid

from .storage import (_strings, project_lock, read_yaml, safe_path,
                      validate_team, write_yaml)

WEIGHTS = {'independence': .30, 'complexity': .25, 'specialization': .25, 'parallel_benefit': .20}
STATUSES = {'planned', 'running', 'completed', 'failed', 'cancelled'}
METRICS = {'tokens': None, 'cost': None, 'duration_seconds': None,
           'subagent_calls': None, 'tool_calls': None, 'rework_rounds': None}
MEMORY_CATEGORIES = ('project-context', 'architecture', 'decisions', 'experience')
COLLABORATION_MODES = ('solo', 'smart', 'team')


def _now():
    return datetime.now(timezone.utc).isoformat()


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _task_path(root, task_id):
    try:
        if str(uuid.UUID(str(task_id))) != task_id:
            raise ValueError('Task id must be a canonical UUID')
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('Invalid task id') from exc
    return safe_path(root, '.agent-team/tasks/' + task_id + '.yaml')


def _scope(root, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Write scope must be a nonempty path')
    # Directory scopes are preferred; globs cannot safely establish ownership.
    if any(char in value for char in '*?['):
        raise ValueError('Write scope must be an explicit file or directory')
    return safe_path(root, value).resolve()


def _work_items(root, items):
    if not isinstance(items, list):
        raise ValueError('work_items must be a list')
    result, seen = [], set()
    for original in items:
        if not isinstance(original, dict):
            raise ValueError('Work item must be a mapping')
        item = dict(original)
        for field in ('id', 'role', 'goal'):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError('Work item {} required'.format(field))
        if item['id'] in seen:
            raise ValueError('Duplicate work item id')
        seen.add(item['id'])
        for field in ('deliverables', 'write_scope', 'depends_on', 'capabilities'):
            item[field] = _strings(item.get(field, []), field)
        for path in item['write_scope']:
            _scope(root, path)
        if type(item.get('read_only', False)) is not bool:
            raise ValueError('read_only must be a boolean')
        if item.get('read_only') and item['write_scope']:
            raise ValueError('Read-only work cannot have write scopes')
        result.append(item)
    for item in result:
        if any(dep not in seen or dep == item['id'] for dep in item['depends_on']):
            raise ValueError('Unknown or self dependency')
    ancestors = {}
    def visit(identifier, visiting):
        if identifier in visiting:
            raise ValueError('Dependency cycle')
        if identifier not in ancestors:
            item = next(i for i in result if i['id'] == identifier)
            inherited = set(item['depends_on'])
            for dep in item['depends_on']:
                inherited.update(visit(dep, visiting | {identifier}))
            ancestors[identifier] = inherited
        return ancestors[identifier]
    for item in result:
        visit(item['id'], set())
    for index, left in enumerate(result):
        for right in result[index + 1:]:
            overlap = any(a == b or a in b.parents or b in a.parents
                          for a in [_scope(root, p) for p in left['write_scope']]
                          for b in [_scope(root, p) for p in right['write_scope']])
            if overlap and left['id'] not in ancestors[right['id']] and right['id'] not in ancestors[left['id']]:
                raise ValueError('Overlapping write scopes require a dependency: {} / {}'.format(left['id'], right['id']))
    return result


def plan_task(root, spec, host=None, platform=None, collaboration_mode=None):
    if host is not None and not isinstance(host, dict):
        raise ValueError('host must be a mapping')
    if not isinstance(spec, dict) or not isinstance(spec.get('title'), str) or not spec['title'].strip():
        raise ValueError('Task title is required')
    if not isinstance(spec.get('goal', spec['title']), str):
        raise ValueError('Task goal must be text')
    scores = spec.get('scores', {})
    if not isinstance(scores, dict) or any(not _number(scores.get(key)) or not 0 <= scores[key] <= 100 for key in WEIGHTS):
        raise ValueError('All four scores must be finite numbers between 0 and 100')
    score = round(sum(scores[key] * weight for key, weight in WEIGHTS.items()), 6)
    criteria = _strings(spec.get('acceptance_criteria', []), 'acceptance_criteria')
    items = _work_items(root, spec.get('work_items', []))
    requested_mode = spec.get('collaboration_mode', 'smart') if collaboration_mode is None else collaboration_mode
    if requested_mode not in COLLABORATION_MODES:
        raise ValueError('collaboration_mode must be one of: ' + ', '.join(COLLABORATION_MODES))
    from .hosts import execution_route, negotiate
    mode, members, limit, warnings = 'single_agent', [], 1, []
    if requested_mode == 'solo':
        warnings.append('Solo mode selected; team configuration and role discovery are skipped')
    active_platform = platform or (host or {}).get('platform')
    if requested_mode != 'solo' and (score >= 40 or requested_mode == 'team'):
        config = validate_team(read_yaml(safe_path(root, '.agent-team/team.yaml')))
        active_platform = active_platform or config.get('platform', 'generic')
        members = config.get('team', {}).get('members', config.get('members', []))
        orchestration = config.get('orchestration', {})
        orchestration_path = safe_path(root, '.agent-team/orchestration.yaml')
        if orchestration_path.exists():
            orchestration = read_yaml(orchestration_path)
            validate_team(dict(config, orchestration=orchestration))
        if not isinstance(orchestration, dict):
            raise ValueError('orchestration must be a mapping')
        thresholds = orchestration.get('thresholds', {})
        if not isinstance(thresholds, dict):
            raise ValueError('thresholds must be a mapping')
        assisted, multi = thresholds.get('assisted', 40), thresholds.get('multi_agent', 70)
        if not _number(assisted) or not _number(multi) or not 40 <= assisted < multi <= 100:
            raise ValueError('Thresholds must satisfy 40 <= assisted < multi_agent <= 100')
        limit = orchestration.get('max_parallel_agents', 2)
        if type(limit) is not int or limit < 1:
            raise ValueError('max_parallel_agents must be a positive integer')
        if requested_mode == 'team':
            mode = 'multi_agent'
            warnings.append('Team mode selected; collaboration is enabled for this plan when work boundaries allow it')
        else:
            mode = 'multi_agent' if score >= multi else 'assisted' if score >= assisted else 'single_agent'
    agents, eligible, handoffs, gaps, retained = [], [], [], [], []
    for item in items:
        member = next((m for m in members if item['role'] in (m['id'], m['role'])), None)
        if member is None and mode != 'single_agent':
            # Reuse only the selected managed user role, without reinstallation
            # or an implicit scan of all roles. Keep it ephemeral to this task;
            # host invocation still requires current capability evidence.
            from .agency_install import installed_user_roles
            try:
                reused = next(installed_user_roles(active_platform, [item['role']]), None)
                if reused is not None:
                    member = dict(reused, role=reused['name'])
            except (OSError, ValueError) as exc:
                warnings.append('Selected user role could not be reused: ' + str(exc))
        missing = item['capabilities'] if member is None else sorted(set(item['capabilities']) - set(member.get('capabilities', [])))
        if mode != 'single_agent' and (member is None or missing):
            gap = {'work_item_id': item['id'], 'role': item['role'],
                   'capabilities': missing, 'recommendations': [],
                   'next_steps': ['Use CLI role recommend --query <task goal>, then submit host --assessment',
                                  'If existing agents do not fit, use role recommend --library agency --query <task goal>',
                                  'Present assessed matches for user selection; preview the selected role and obtain manual installation confirmation before --approve',
                                  'After installation, replan with the real member ID; unverified native invocation can use explicit role handoffs',
                                  'Use role generate only if no suitable existing or library role can be found']}
            # Role discovery is loaded only when the task has an actual capability gap.
            from .marketplace import build_catalog, recommend_roles
            from .recommendation import capability_card, compact_request
            try:
                catalog = build_catalog(root, active_platform, host=host)
                gap['recommendations'] = [capability_card(role) for role in
                                          recommend_roles(catalog, missing or [item['role']], item['deliverables'], limit=3)]
                gap['semantic_request'] = compact_request(
                    [role for role in catalog if role.get('source') not in ('builtin', 'generated')],
                    '{}\n{}\n{}'.format(spec.get('goal', spec['title']), item['goal'], item['role']),
                    missing or [item['role']], item['deliverables'])
            except (OSError, ValueError) as exc:
                warnings.append('Role recommendations unavailable: ' + str(exc))
            gaps.append(gap)
            retained.append(item['id'])
            warnings.append('Capability gap for {}; main agent retains this work item'.format(item['id']))
            continue
        if mode != 'single_agent' and item['deliverables'] and (item['write_scope'] or item.get('read_only') is True):
            agent_kinds = member.get('agent_kinds', {})
            agent_kind = agent_kinds.get(active_platform) if isinstance(agent_kinds, dict) else None
            # Older Agent Team Builder installs did not record the distinction
            # between a generated Skill and a callable host agent. Recognize
            # those records by their managed Agency provenance and target.
            if (agent_kind is None and active_platform in ('trae', 'pi', 'workbuddy')
                    and active_platform in member.get('platforms', []) and member.get('upstream')):
                agent_kind = 'skill'
            eligible.append(item)
            agents.append({'work_item_id': item['id'], 'role': item['role'], 'member_id': member['id'],
                           'agent_id': member.get('agent_ids', {}).get(active_platform,
                                                                    member.get('agent_id', member['id'])),
                           'agent_kind': agent_kind or 'agent'})
            instructions = member.get('prompt', '')
            if member.get('definition'):
                instructions = safe_path(root, member['definition']).read_text(encoding='utf-8')
            aliases = (agents[-1]['agent_id'], member['id'], member.get('name'), member['role'])
            # Another host's registered ID is not invocation evidence for this host.
            if active_platform not in member.get('platforms', [active_platform]):
                aliases = (member.get('agent_ids', {}).get(active_platform),)
            route = execution_route(active_platform, host, aliases,
                                    role_instructions=bool(str(instructions).strip()), kind=agent_kind or 'agent')
            current_cap = negotiate(active_platform, host)
            if current_cap['shared_workspace'] is False:
                route.update(mode='sequential_handoff', agent_id=None,
                             reason='Host workspaces are isolated; prepare and verify project transfer and result integration before delegation')
                warnings.append('Work item {} needs an isolated workspace transfer contract; worktree support alone does not prepare a workspace'.format(item['id']))
            agents[-1].update(configured_agent_id=agents[-1]['agent_id'], agent_id=route['agent_id'],
                              execution_mode=route['mode'])
            handoffs.append({'work_item_id': item['id'], 'prompt':
                'Goal: {}\nDeliverables: {}\nWrite only: {}\nDependencies: {}\nAcceptance: {}\n'
                'Read access: project files needed for this assignment; do not access unrelated private files.\n'
                'Use the host-assigned project workspace; confirm project files are accessible before working. '
                'Preserve other changes. Return changed paths, actual validation and risks. '
                'Do not claim execution without evidence.'.format(item['goal'], ', '.join(item['deliverables']),
                ', '.join(item['write_scope']) or 'none (read-only)', ', '.join(item['depends_on']) or 'none', '; '.join(criteria))
                + '\nRole instructions:\n' + str(instructions), 'transport': route})
        elif mode != 'single_agent':
            warnings.append('Work item {} lacks deliverables or an independent write boundary; main agent retains it'.format(item['id']))
            retained.append(item['id'])
        else:
            retained.append(item['id'])
    if mode == 'multi_agent':
        eligible_ids = {item['id'] for item in eligible}
        done, pending, independent_ready = set(), list(items), False
        while pending:
            ready = [item for item in pending if set(item['depends_on']) <= done]
            independent_ready = independent_ready or sum(item['id'] in eligible_ids for item in ready) >= 2
            done.update(item['id'] for item in ready)
            pending = [item for item in pending if item['id'] not in done]
        if scores['parallel_benefit'] <= 0 or scores['independence'] <= 0 or not independent_ready:
            mode = 'assisted'
            warnings.append('Parallel execution requires positive independence and parallel benefit plus two independently ready delegated items')
    active_platform = active_platform or 'generic'
    cap = negotiate(active_platform, host)
    limit = min(limit, cap['max_parallel_agents'] or 1)
    delegated = [a for a in agents if a['execution_mode'] != 'sequential_handoff']
    all_delegated = bool(agents) and len(delegated) == len(agents)
    if mode == 'single_agent' or not eligible:
        strategy = 'single_agent'
    elif all_delegated:
        strategy = 'native_subagents' if all(a['execution_mode'] == 'native_role' for a in agents) else 'host_subagents'
    else:
        strategy = 'mixed_handoffs' if delegated else 'sequential_handoffs'
        warnings.append('Some role transports are unverified; execute those explicit handoffs sequentially')
    if mode == 'assisted' or not all_delegated or retained:
        limit = 1
    writers = {item['id'] for item in items if item['write_scope']}
    if writers and cap['parallel_writes'] is not True:
        limit = 1
        warnings.append('Parallel writes are not verified for this session; serializing write work')
    batches, done, pending = [], set(), list(items)
    while pending:
        ready = [item for item in pending if set(item['depends_on']) <= done][:limit]
        batches.append([item['id'] for item in ready])
        done.update(item['id'] for item in ready)
        pending = [item for item in pending if item['id'] not in done]
    if mode == 'multi_agent' and all_delegated:
        eligible_ids = {item['id'] for item in eligible}
        if not any(sum(identifier in eligible_ids for identifier in batch) >= 2 for batch in batches):
            mode = 'assisted'
            batches = [[identifier] for batch in batches for identifier in batch]
            warnings.append('Effective concurrency permits no parallel delegated batch; using assisted execution')
    identifier, now = str(uuid.uuid4()), _now()
    delegated_agents = [agent for agent in agents if agent['execution_mode'] != 'sequential_handoff']
    delegated_count = len(delegated_agents)
    if delegated_count == 0:
        cost_impact = 'none'
    elif delegated_count == 1:
        cost_impact = 'low'
    else:
        cost_impact = 'moderate'
    cost_estimate = {
        'additional_agents': delegated_count,
        'token_estimate': None,
        'token_estimate_reason': 'No reliable pre-execution token estimate was supplied',
        'impact': cost_impact,
        'impact_basis': 'Agent call count only; not a token or monetary estimate',
        'requires_user_confirmation': delegated_count > 0,
        'context_policy': 'task_scope_and_selected_role_only',
    }
    record = {'task': {'id': identifier, 'title': spec['title'], 'goal': spec.get('goal', spec['title']),
                       'scores': dict(scores), 'score': score, 'status': 'planned',
                       'acceptance_criteria': criteria, 'created_at': now, 'updated_at': now},
              'execution': {'mode': mode, 'requested_mode': requested_mode, 'strategy': strategy, 'agents': agents,
                            'cost_estimate': cost_estimate,
                            'delegation_approval': {'status': 'pending' if delegated_count else 'not_required'},
                            'work_items': items,
                            'batches': batches, 'handoffs': handoffs, 'warnings': warnings,
                            'platform': active_platform, 'host': cap, 'max_parallel_agents': limit,
                            'execution_verified': False,
                            'capability_gaps': gaps, 'retained_by_main': retained},
              'metrics': dict(METRICS), 'result': {'summary': '', 'evidence': None}}
    with project_lock(root):
        write_yaml(_task_path(root, identifier), record)
    return record


def get_task(root, task_id):
    path = _task_path(root, task_id)
    if not path.exists():
        raise ValueError('Unknown task: ' + task_id)
    record = read_yaml(path)
    if not isinstance(record.get('task'), dict) or record['task'].get('id') != task_id:
        raise ValueError('Invalid task record: ' + task_id)
    return record


def list_tasks(root):
    directory = safe_path(root, '.agent-team/tasks')
    return [get_task(root, path.stem) for path in sorted(directory.glob('*.yaml'))]


def update_task(root, task_id, status, summary='', metrics=None, evidence=None, approve_delegation=False):
    if status not in STATUSES:
        raise ValueError('Unknown task status')
    if not isinstance(summary, str):
        raise ValueError('summary must be text')
    if evidence is not None and (not isinstance(evidence, (str, list, dict)) or not evidence):
        raise ValueError('Evidence must be nonempty text, list or mapping')
    if status == 'completed' and (not summary.strip() or not evidence or isinstance(evidence, str) and not evidence.strip()):
        raise ValueError('Completion requires summary and actual acceptance evidence')
    if metrics is not None and (not isinstance(metrics, dict) or any(v is not None and (not _number(v) or v < 0) for v in metrics.values())):
        raise ValueError('Metrics must be nonnegative finite numbers or null')
    for key in ('subagent_calls', 'tool_calls', 'rework_rounds'):
        value = (metrics or {}).get(key)
        if value is not None and type(value) is not int:
            raise ValueError(key + ' must be a nonnegative integer or null')
    if type(approve_delegation) is not bool:
        raise ValueError('approve_delegation must be a boolean')
    with project_lock(root):
        record = get_task(root, task_id)
        previous = record['task']['status']
        if previous in ('completed', 'failed', 'cancelled') and status != previous:
            raise ValueError('Terminal task cannot change status')
        approval = record['execution'].get('delegation_approval', {})
        if approval.get('status') == 'pending':
            if approve_delegation:
                record['execution']['delegation_approval'] = {'status': 'approved', 'recorded_at': _now()}
            elif status in ('running', 'completed'):
                raise ValueError('Delegation cost preview requires task authorization; use --approve-delegation only after user approval')
        record['task'].update(status=status, updated_at=_now())
        record['result'] = {'summary': summary, 'evidence': evidence}
        if metrics is not None:
            record['metrics'].update(metrics)
        write_yaml(_task_path(root, task_id), record)
        return record


def add_memory(root, category, text, source, approved=False):
    if not all(isinstance(v, str) and v.strip() for v in (category, text, source)):
        raise ValueError('Memory category, text and source are required')
    if category not in MEMORY_CATEGORIES:
        raise ValueError('Unknown memory category')
    if category in ('architecture', 'decisions') and approved is not True:
        raise ValueError('Architecture and decision memories require explicit approval')
    with project_lock(root):
        path = safe_path(root, '.agent-team/memory/' + category + '.yaml')
        data = read_yaml(path) if path.exists() else {'entries': []}
        if not isinstance(data.get('entries'), list):
            raise ValueError('Invalid memory entries')
        for entry in data['entries']:
            if entry.get('text') == text.strip() and entry.get('source') == source.strip():
                return entry
        now = _now()
        entry = {'id': str(uuid.uuid4()), 'category': category, 'text': text.strip(), 'source': source.strip(),
                 'approved': approved is True, 'created_at': now, 'updated_at': now,
                 'revision': 1, 'history': []}
        data['entries'].append(entry)
        write_yaml(path, data)
        return entry


def update_memory(root, category, entry_id, text, source, approved=False):
    """Replace stale knowledge while retaining every previous content revision."""
    if not all(isinstance(value, str) and value.strip() for value in (category, entry_id, text, source)):
        raise ValueError('Memory category, id, text and source are required')
    if category not in MEMORY_CATEGORIES:
        raise ValueError('Unknown memory category')
    if category in ('architecture', 'decisions') and approved is not True:
        raise ValueError('Architecture and decision memories require explicit approval')
    with project_lock(root):
        path = safe_path(root, '.agent-team/memory/' + category + '.yaml')
        if not path.exists():
            raise ValueError('Unknown memory entry: ' + entry_id)
        data = read_yaml(path)
        if not isinstance(data.get('entries'), list) or any(not isinstance(entry, dict) for entry in data['entries']):
            raise ValueError('Invalid memory entries')
        entry = next((entry for entry in data['entries'] if entry.get('id') == entry_id), None)
        if entry is None:
            raise ValueError('Unknown memory entry: ' + entry_id)
        if entry.get('text') == text.strip() and entry.get('source') == source.strip() and entry.get('approved') is (approved is True):
            return entry
        history = entry.get('history', [])
        revision = entry.get('revision', 1)
        if not isinstance(history, list) or type(revision) is not int or revision < 1:
            raise ValueError('Invalid memory revision history')
        previous = {key: value for key, value in entry.items() if key != 'history'}
        previous.setdefault('revision', revision)
        history.append(previous)
        entry.update(text=text.strip(), source=source.strip(), approved=approved is True,
                     updated_at=_now(), revision=revision + 1, history=history)
        write_yaml(path, data)
        return entry


def read_memory(root, category=None):
    categories = MEMORY_CATEGORIES if category is None else [category]
    result = {}
    for name in categories:
        if name not in MEMORY_CATEGORIES:
            raise ValueError('Unknown memory category')
        path = safe_path(root, '.agent-team/memory/' + name + '.yaml')
        data = read_yaml(path) if path.exists() else {'entries': []}
        if not isinstance(data.get('entries'), list):
            raise ValueError('Invalid memory entries')
        result[name] = data['entries']
    return result


def _metric_summary(records):
    totals, coverage = {}, {}
    keys = set(METRICS).union(*(r.get('metrics', {}).keys() for r in records))
    for key in sorted(keys):
        values = [r.get('metrics', {}).get(key) for r in records]
        measured = [value for value in values if value is not None]
        if any(not _number(value) or value < 0 for value in measured):
            raise ValueError('Invalid persisted metric: ' + str(key))
        totals[key] = sum(measured) if values and len(measured) == len(values) else None
        coverage[key] = {'known_total': sum(measured) if measured else None,
                         'measured': len(measured), 'missing': len(values) - len(measured),
                         'coverage': len(measured) / len(values) if values else None}
    return totals, coverage


def analytics(root):
    records = list_tasks(root)
    statuses = {status: sum(r['task']['status'] == status for r in records) for status in sorted(STATUSES)}
    totals, coverage = _metric_summary(records)
    groups = {}
    for record in records:
        roles = {agent['role'] for agent in record['execution'].get('agents', [])}
        if not roles or record['execution'].get('retained_by_main'):
            roles.add('main')
        groups.setdefault(tuple(sorted(roles)), []).append(record)
    combinations = []
    for roles, group in sorted(groups.items()):
        group_totals, group_coverage = _metric_summary(group)
        combinations.append({'roles': list(roles), 'task_count': len(group),
                             'statuses': {status: sum(r['task']['status'] == status for r in group) for status in sorted(STATUSES)},
                             'results': [{'task_id': r['task']['id'], 'status': r['task']['status'],
                                          'summary': r.get('result', {}).get('summary', ''),
                                          'evidence': r.get('result', {}).get('evidence')} for r in group],
                             'metrics': group_totals, 'metric_coverage': group_coverage})
    mode_comparison = []
    for mode in ('single_agent', 'with_subagents', 'unmeasured'):
        group = []
        for record in records:
            calls = record.get('metrics', {}).get('subagent_calls')
            measured_mode = 'unmeasured' if calls is None else 'with_subagents' if calls > 0 else 'single_agent'
            if measured_mode == mode:
                group.append(record)
        mode_metrics, mode_coverage = _metric_summary(group)
        mode_comparison.append({'mode': mode, 'task_count': len(group),
                                'completed_tasks': sum(r['task']['status'] == 'completed' for r in group),
                                'metrics': mode_metrics, 'metric_coverage': mode_coverage})
    return {'total_tasks': len(records), 'statuses': statuses, 'metrics': totals,
            'metric_coverage': coverage, 'role_combinations': combinations,
            'mode_comparison': mode_comparison,
            'comparison_basis': 'Host-reported subagent_calls; observational groups, not matched benchmarks or savings claims',
            'modes': {mode: sum(r['execution']['mode'] == mode for r in records)
                      for mode in ('single_agent', 'assisted', 'multi_agent')}}
