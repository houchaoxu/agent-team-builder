"""Deterministic planning and records; execution remains a host responsibility."""
from datetime import datetime, timezone
import math
from pathlib import Path
import uuid

from .storage import (_strings, project_lock, read_yaml, safe_path,
                      validate_team, write_yaml)

WEIGHTS = {'independence': .30, 'complexity': .25, 'specialization': .25, 'parallel_benefit': .20}
STATUSES = {'planned', 'running', 'completed', 'failed', 'cancelled'}
METRICS = {'tokens': None, 'cost': None, 'duration_seconds': None}
MEMORY_CATEGORIES = ('project-context', 'architecture', 'decisions', 'experience')


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


def plan_task(root, spec, host=None):
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
    mode, members, limit, warnings = 'single_agent', [], 1, []
    if score >= 40:
        config = validate_team(read_yaml(safe_path(root, '.agent-team/team.yaml')))
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
        limit = orchestration.get('max_parallel_agents', 3)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 3:
            raise ValueError('max_parallel_agents must be 1 through 3')
        mode = 'multi_agent' if score >= multi else 'assisted' if score >= assisted else 'single_agent'
    agents, eligible, handoffs, gaps, retained = [], [], [], [], []
    for item in items:
        member = next((m for m in members if item['role'] in (m['id'], m['role'])), None)
        missing = item['capabilities'] if member is None else sorted(set(item['capabilities']) - set(member.get('capabilities', [])))
        if mode != 'single_agent' and (member is None or missing):
            gap = {'work_item_id': item['id'], 'role': item['role'],
                   'capabilities': missing, 'recommendations': [],
                   'next_steps': ['Use CLI role recommend --capability <required capability>',
                                  'Use CLI role generate <id> --name <name> --capability <required capability>']}
            # Role discovery is loaded only when the task has an actual capability gap.
            from .marketplace import build_catalog, recommend_roles
            try:
                catalog = build_catalog(root, config.get('platform', 'generic'), host=host)
                gap['recommendations'] = recommend_roles(catalog, missing or [item['role']], item['deliverables'], limit=3)
            except (OSError, ValueError) as exc:
                warnings.append('Role recommendations unavailable: ' + str(exc))
            gaps.append(gap)
            retained.append(item['id'])
            warnings.append('Capability gap for {}; main agent retains this work item'.format(item['id']))
            continue
        if mode != 'single_agent' and item['deliverables'] and (item['write_scope'] or item.get('read_only') is True):
            eligible.append(item)
            agents.append({'work_item_id': item['id'], 'role': item['role'], 'member_id': member['id'],
                           'agent_id': member.get('agent_id', member['id'])})
            instructions = member.get('prompt', '')
            if member.get('definition'):
                instructions = safe_path(root, member['definition']).read_text(encoding='utf-8')
            handoffs.append({'work_item_id': item['id'], 'prompt':
                'Goal: {}\nDeliverables: {}\nWrite only: {}\nDependencies: {}\nAcceptance: {}\n'
                'Read access: project files needed for this assignment; do not access unrelated private files.\n'
                'You share the workspace. Preserve other changes. Return changed paths, actual validation and risks. '
                'Do not claim execution without evidence.'.format(item['goal'], ', '.join(item['deliverables']),
                ', '.join(item['write_scope']) or 'none (read-only)', ', '.join(item['depends_on']) or 'none', '; '.join(criteria))
                + '\nRole instructions:\n' + str(instructions)})
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
    host = host if isinstance(host, dict) else {}
    native = host.get('native_subagents') is True and isinstance(host.get('evidence'), str) and bool(host['evidence'].strip())
    available = host.get('available_agents', [])
    if not isinstance(available, list):
        raise ValueError('available_agents must be a list')
    host_limit = host.get('max_parallel_agents', limit)
    if not isinstance(host_limit, int) or isinstance(host_limit, bool) or host_limit < 1:
        raise ValueError('Host max_parallel_agents must be a positive integer')
    limit = min(limit, host_limit, 3)
    # Resolve the exact host identifier that will actually be passed to spawn.
    for agent in agents:
        matched = next((identifier for identifier in
                        (agent['agent_id'], agent['member_id'], agent['role'])
                        if identifier in available), None)
        agent['configured_agent_id'] = agent['agent_id']
        agent['agent_id'] = matched if native else agent['agent_id']
    callable_agents = native and all(a['agent_id'] is not None for a in agents)
    strategy = 'single_agent' if mode == 'single_agent' or not eligible else 'native_subagents' if callable_agents else 'sequential_handoffs'
    if mode != 'single_agent' and not callable_agents:
        warnings.append('Native agent capability is unverified or roles unavailable; use explicit handoffs')
    if mode == 'assisted' or strategy != 'native_subagents':
        limit = 1
    batches, done, pending = [], set(), list(items)
    while pending:
        ready = [item for item in pending if set(item['depends_on']) <= done][:limit]
        batches.append([item['id'] for item in ready])
        done.update(item['id'] for item in ready)
        pending = [item for item in pending if item['id'] not in done]
    if mode == 'multi_agent' and strategy == 'native_subagents':
        eligible_ids = {item['id'] for item in eligible}
        if not any(sum(identifier in eligible_ids for identifier in batch) >= 2 for batch in batches):
            mode = 'assisted'
            batches = [[identifier] for batch in batches for identifier in batch]
            warnings.append('Effective concurrency permits no parallel delegated batch; using assisted execution')
    identifier, now = str(uuid.uuid4()), _now()
    record = {'task': {'id': identifier, 'title': spec['title'], 'goal': spec.get('goal', spec['title']),
                       'scores': dict(scores), 'score': score, 'status': 'planned',
                       'acceptance_criteria': criteria, 'created_at': now, 'updated_at': now},
              'execution': {'mode': mode, 'strategy': strategy, 'agents': agents, 'work_items': items,
                            'batches': batches, 'handoffs': handoffs, 'warnings': warnings,
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


def update_task(root, task_id, status, summary='', metrics=None, evidence=None):
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
    with project_lock(root):
        record = get_task(root, task_id)
        previous = record['task']['status']
        if previous in ('completed', 'failed', 'cancelled') and status != previous:
            raise ValueError('Terminal task cannot change status')
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
    return {'total_tasks': len(records), 'statuses': statuses, 'metrics': totals,
            'metric_coverage': coverage, 'role_combinations': combinations,
            'modes': {mode: sum(r['execution']['mode'] == mode for r in records)
                      for mode in ('single_agent', 'assisted', 'multi_agent')}}
