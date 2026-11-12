"""Project-local, validated and atomic persistence."""
import os
import math
import json
from pathlib import Path
import tempfile
import uuid
from contextlib import contextmanager

import yaml

if os.name == 'nt':
    import msvcrt
else:
    import fcntl


def discover_root(start):
    start = Path(start).resolve()
    if start.is_file():
        start = start.parent
    for candidate in (start, *start.parents):
        if (candidate / '.agent-team' / 'team.yaml').exists():
            return candidate
        if any((candidate / marker).exists() for marker in
               ('.git', 'pyproject.toml', 'package.json', 'Cargo.toml', 'go.mod')):
            return candidate
    return start


def read_yaml(path):
    try:
        with Path(path).open(encoding='utf-8') as stream:
            data = yaml.safe_load(stream)
    except (yaml.YAMLError, UnicodeError) as exc:
        raise ValueError('Invalid YAML in {}: {}'.format(path, exc)) from exc
    if not isinstance(data, dict):
        raise ValueError('YAML must contain a mapping: {}'.format(path))
    _json_safe(data, path)
    return data


def write_yaml(path, data):
    path = Path(path)
    if not isinstance(data, dict):
        raise ValueError('YAML must contain a mapping')
    _json_safe(data, path)
    _atomic_text(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def _json_safe(data, path):
    """Keep persisted YAML interoperable with the JSON CLI before any mutation."""
    try:
        json.dumps(data, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError('YAML must use JSON-compatible values in {} (quote dates as text): {}'.format(path, exc)) from exc

    def check_keys(value):
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError('YAML mapping keys must be strings: {}'.format(path))
            for child in value.values():
                check_keys(child)
        elif isinstance(value, list):
            for child in value:
                check_keys(child)

    check_keys(data)


def _atomic_text(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=str(path.parent))
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def safe_path(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Path must be relative and remain inside the project')
    candidate = root / relative
    try:
        candidate.resolve().relative_to(root)
    except (ValueError, RuntimeError) as exc:
        raise ValueError('Path escapes project: {}'.format(relative)) from exc
    return candidate


@contextmanager
def project_lock(root):
    directory = safe_path(root, '.agent-team')
    directory.mkdir(parents=True, exist_ok=True)
    lock = safe_path(root, '.agent-team/.lock')
    with lock.open('a', encoding='utf-8') as stream:
        if os.name == 'nt':
            if stream.tell() == 0:
                stream.write('0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _strings(value, field):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError('{} must be a list of nonempty strings'.format(field))
    return value


def validate_team(data):
    if not isinstance(data, dict) or (data.get('version') != 1 and data.get('schema_version') != '1.0'):
        raise ValueError('Unsupported or missing team version')
    members = data.get('team', {}).get('members') if isinstance(data.get('team'), dict) else data.get('members')
    if data.get('schema_version') == '1.0':
        for field in ('project', 'team', 'settings'):
            if not isinstance(data.get(field), dict):
                raise ValueError('{} must be a mapping'.format(field))
    orchestration = data.get('orchestration', {})
    if not isinstance(orchestration, dict):
        raise ValueError('orchestration must be a mapping')
    limit = orchestration.get('max_parallel_agents', 3)
    if type(limit) is not int or not 1 <= limit <= 3:
        raise ValueError('max_parallel_agents must be 1 through 3')
    thresholds = orchestration.get('thresholds', {})
    if not isinstance(thresholds, dict):
        raise ValueError('thresholds must be a mapping')
    low, high = thresholds.get('assisted', 40), thresholds.get('multi_agent', 70)
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in (low, high)) or not 40 <= low < high <= 100:
        raise ValueError('Thresholds must satisfy 40 <= assisted < multi_agent <= 100')
    if not isinstance(members, list) or not members:
        raise ValueError('Team members must be a nonempty list')
    identifiers = set()
    for member in members:
        if not isinstance(member, dict):
            raise ValueError('Each member must be a mapping')
        for field in ('id', 'role'):
            if not isinstance(member.get(field), str) or not member[field].strip():
                raise ValueError('Member {} is required'.format(field))
        if member['id'] in identifiers:
            raise ValueError('Duplicate member id: ' + member['id'])
        identifiers.add(member['id'])
        for field in ('capabilities', 'deliverables', 'write_scope'):
            if field in member:
                _strings(member[field], field)
    return data


def bootstrap(root, platform='generic'):
    from .adapters import entry_path, entry_text
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with project_lock(root):
        team_path = safe_path(root, '.agent-team/team.yaml')
        if team_path.exists():
            team = validate_team(read_yaml(team_path))
        else:
            stack = [label for marker, label in [('pyproject.toml', 'python'), ('requirements.txt', 'python'),
                     ('package.json', 'javascript'), ('Cargo.toml', 'rust'), ('go.mod', 'go'),
                     ('pom.xml', 'java'), ('build.gradle', 'java'), ('build.gradle.kts', 'kotlin'),
                     ('vue.config.js', 'vue'), ('vite.config.ts', 'vite')]
                     if (root / marker).exists()]
            team = {'schema_version': '1.0', 'platform': platform,
                    'project': {'id': str(uuid.uuid4()), 'name': root.name, 'root': '.', 'stack': sorted(set(stack))},
                    'settings': {},
                    'orchestration': {'thresholds': {'assisted': 40, 'multi_agent': 70}, 'max_parallel_agents': 3},
                    'team': {'id': str(uuid.uuid4()), 'name': root.name + ' team', 'status': 'active',
                    'members': [{'id': 'implementer', 'name': 'Implementation Engineer',
                                 'role': 'Implementation Engineer', 'capabilities': ['implementation'],
                                 'deliverables': ['verified implementation'], 'write_scope': []}]}}
            # Validate adapter/platform before creating any configuration.
            entry_path(platform)
            write_yaml(team_path, team)
        orchestration_path = safe_path(root, '.agent-team/orchestration.yaml')
        if orchestration_path.exists():
            orchestration = read_yaml(orchestration_path)
            validate_team(dict(team, orchestration=orchestration))
        else:
            write_yaml(orchestration_path, team.get('orchestration',
                       {'thresholds': {'assisted': 40, 'multi_agent': 70}, 'max_parallel_agents': 3}))
        selected = team.get('platform', platform)
        entry = safe_path(root, entry_path(selected))
        existing = entry.read_text(encoding='utf-8') if entry.exists() else ''
        begin, end = '<!-- agent-team-runtime:begin -->', '<!-- agent-team-runtime:end -->'
        addition = entry_text(selected)
        if begin in existing or end in existing:
            if existing.count(begin) != 1 or existing.count(end) != 1 or existing.index(begin) >= existing.index(end):
                raise ValueError('Project entry has invalid runtime markers; preserve and repair it before initialization')
            managed = addition[addition.index(begin):].rstrip('\n')
            updated = existing[:existing.index(begin)] + managed + existing[existing.index(end) + len(end):]
            if updated != existing:
                _atomic_text(entry, updated)
        else:
            if existing and selected == 'cursor':
                addition = addition[addition.index(begin):]
            _atomic_text(entry, existing + ('\n\n' if existing else '') + addition)
        for relative in ('.agent-team/tasks', '.agent-team/memory', '.agent-team/members'):
            safe_path(root, relative).mkdir(parents=True, exist_ok=True)
        return team
