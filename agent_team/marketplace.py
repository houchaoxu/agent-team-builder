"""Local role discovery, recommendations and explicitly approved installation."""

import os
import re
import warnings
from pathlib import Path

import yaml

try:
    import tomllib
except ImportError:  # Python 3.9 and 3.10
    import tomli as tomllib

from .adapters import capabilities as host_capabilities, render_role, _ROLE_DIRS


def _strings(values, label):
    if values is None:
        return []
    if isinstance(values, str):
        return [values]
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise ValueError(label + " must be a list of strings.")
    return values


def _id(value):
    return re.sub(r"[^a-z0-9_-]+", "-", str(value).lower()).strip("-")[:80]


def _host_matches(role, host):
    aliases = {role.get(key) for key in ("id", "role", "name", "agent_id")
               if isinstance(role.get(key), str) and role[key].strip()}
    return [name for name in host["available_agents"]
            if name in aliases or _id(name) == role.get("id")]


def generate_role(role_id, name, capabilities, deliverables=None):
    caps = _strings(capabilities, "capabilities")
    outputs = _strings(deliverables, "deliverables")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Role name must be non-empty.")
    role = {"id": role_id, "name": name, "capabilities": caps, "deliverables": outputs,
            "prompt": ("You are %s.\nResponsibilities: %s.\nDeliverables: %s.\n"
                       "Respect the assigned scope, preserve collaborators' changes, and report actual validation and risks."
                       % (name, ", ".join(caps) or "follow the assigned task", ", ".join(outputs) or "task results")),
            "source": "generated", "platforms": list(_ROLE_DIRS), "status": "proposed", "evidence": []}
    render_role(role, "generic")  # Validate identifiers before returning a profile.
    return role


def _status(role, platform, host, channel="generated"):
    """Never trust status or availability claims embedded in a role file."""
    role = dict(role)
    available = host["native_subagents"] and bool(_host_matches(role, host))
    if platform not in role.get("platforms", list(_ROLE_DIRS)):
        status, evidence = "unavailable", ["Role does not support platform " + platform]
    elif available:
        status, evidence = "available", [host["evidence"]]
    elif channel in ("project", "installed"):
        status, evidence = "unavailable", ["Installed role requires host verification before native invocation."]
    elif isinstance(role.get("prompt"), str) and role["prompt"].strip():
        status, evidence = ("proposed" if role.get("source") in ("builtin", "generated") else "installable"), []
    else:
        status, evidence = "unavailable", ["No role instructions are available for installation."]
    trust = {"host": 1.0, "project": 0.85, "installed": 0.8,
             "local": 0.65, "builtin": 0.7, "generated": 0.4}.get(channel, 0.4)
    role.update(status=status, evidence=evidence, platform_compatible=platform in role.get("platforms", list(_ROLE_DIRS)),
                provenance={"channel": channel, "definition_trust": trust})
    return role


def _read_role(path, source):
    content = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".toml":
        data = tomllib.loads(content)
        prompt = data.get("developer_instructions", data.get("prompt", ""))
    else:
        content = content.lstrip("\ufeff")
        data, prompt = {}, content
        if content.startswith("---\n") or content.startswith("---\r\n"):
            lines = content.splitlines()
            end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
            if end is None:
                raise ValueError("Unclosed YAML frontmatter")
            data = yaml.safe_load("\n".join(lines[1:end])) or {}
            prompt = "\n".join(lines[end + 1:]).strip()
        if not isinstance(data, dict):
            raise ValueError("Role frontmatter must be a mapping")
    name = data.get("name", path.stem)
    role_id = data.get("id") or _id(path.stem)
    role = {"id": role_id, "name": name,
            "description": data.get("description", "Specialist role: " + str(name)),
            "capabilities": _strings(data.get("capabilities"), "capabilities"),
            "deliverables": _strings(data.get("deliverables"), "deliverables"),
            "prompt": prompt, "source": source, "source_path": str(path),
            "platforms": _strings(data.get("platforms", list(_ROLE_DIRS)), "platforms")}
    for key in ("role", "agent_id"):
        if key in data:
            if not isinstance(data[key], str) or not data[key].strip():
                raise ValueError("Role %s must be a non-empty string" % key)
            role[key] = data[key]
    if not role["capabilities"]:
        role["capabilities"] = [str(name), role["description"]]
    render_role(role, "generic")
    return role


def _scan(directory, source, project_root=None):
    """Bounded discovery; implicit project sources must remain in that project."""
    directory = Path(directory).expanduser()
    if project_root is not None:
        from .storage import safe_path
        directory = safe_path(project_root, directory.relative_to(project_root))
    if not directory.exists():
        return
    if not directory.is_dir():
        raise ValueError("Role source is not a directory: %s" % directory)
    count = 0
    for current, dirs, files in os.walk(str(directory), followlinks=False):
        relative = Path(current).relative_to(directory)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(current) / d).is_symlink())
        if len(relative.parts) >= 3:
            dirs[:] = []
        for name in sorted(files):
            path = Path(current) / name
            if path.suffix.lower() not in (".md", ".toml") or path.is_symlink():
                continue
            if path.stem.lower() in ("readme", "agents", "claude", "gemini", "license", "contributing"):
                continue
            count += 1
            if count > 300:
                warnings.warn("Role source scan stopped after 300 files: %s" % directory, RuntimeWarning)
                return
            try:
                if path.stat().st_size > 256_000:
                    raise ValueError("Role file exceeds 256 KB")
                yield _read_role(path, source)
            except (ValueError, OSError, UnicodeError, yaml.YAMLError) as exc:
                warnings.warn("Skipping invalid role %s: %s" % (path, exc), RuntimeWarning)


def build_catalog(root, platform="generic", sources=None, host=None):
    from .storage import read_yaml, safe_path, validate_team

    root = Path(root).resolve()
    verified_host = host_capabilities(platform, host)
    roles = {}

    def add(role, channel):
        existing = roles.get(role["id"])
        # Host inventory proves invocation but local definitions supply the profile.
        if existing is None or existing["source"] == "host":
            matched = _host_matches(role, verified_host)
            placeholders = [key for key, value in roles.items()
                            if value["source"] == "host" and value["name"] in matched]
            for key in placeholders:
                del roles[key]
            roles[role["id"]] = _status(role, platform, verified_host, channel)

    for name in verified_host["available_agents"]:
        add({"id": _id(name) or "host-agent", "name": name, "capabilities": [name],
             "deliverables": [], "prompt": "", "source": "host", "platforms": [platform]}, "host")

    config_path = safe_path(root, ".agent-team/team.yaml")
    if config_path.exists():
        config = validate_team(read_yaml(config_path))
        members = config.get("team", {}).get("members", config.get("members", []))
        for member in members:
            definition = member.get("definition")
            role = dict(member, name=member.get("name", member["role"]),
                        capabilities=member.get("capabilities", [member["role"]]),
                        deliverables=member.get("deliverables", []),
                        prompt=member.get("prompt", ""), source="project",
                        platforms=_strings(member.get("platforms", list(_ROLE_DIRS)), "platforms"))
            if definition:
                path = safe_path(root, definition)
                if path.is_file():
                    try:
                        parsed = _read_role(path, "project")
                        role.update(prompt=parsed["prompt"], source_path=str(path))
                        # The registry retains platform restrictions even when the
                        # native file format has no field for them. A definition
                        # may narrow those restrictions, never silently widen them.
                        role["platforms"] = [value for value in role["platforms"] if value in parsed["platforms"]]
                    except (ValueError, OSError, UnicodeError, yaml.YAMLError) as exc:
                        warnings.warn("Skipping invalid role definition %s: %s" % (path, exc), RuntimeWarning)
            add(role, "project")
    for role in _scan(safe_path(root, _ROLE_DIRS[platform]), "project", project_root=root):
        add(role, "project")
    if sources is None:
        source_dirs = [{"path": Path.home() / path, "kind": "local"}
                       for path in _ROLE_DIRS.values() if path != _ROLE_DIRS["generic"]]
    else:
        if isinstance(sources, (str, Path)):
            sources = [sources]
        if not isinstance(sources, (list, tuple)):
            raise ValueError("sources must be a list of local directories.")
        source_dirs = [item if isinstance(item, dict) else {"path": item, "kind": "local"} for item in sources]
    for source in source_dirs:
        if not source.get("path"):
            raise ValueError("Role source requires a local path.")
        directory = Path(source["path"]).expanduser()
        if not directory.is_absolute():
            directory = root / directory
        for role in _scan(directory, source.get("kind", "local")):
            add(role, "installed" if sources is None else "local")
    builtins = (("implementation-engineer", "Implementation Engineer", ["implementation", "coding", "development"], ["code", "tests"]),
                ("test-engineer", "Test Engineer", ["testing", "validation", "regression"], ["test report", "test cases"]),
                ("code-reviewer", "Code Reviewer", ["review", "security", "correctness"], ["review findings"]),
                ("software-architect", "Software Architect", ["architecture", "design", "interfaces"], ["design", "implementation plan"]),
                ("requirements-analyst", "Requirements Analyst", ["requirements", "analysis", "acceptance"], ["acceptance criteria", "requirements"]),
                ("devops-automator", "DevOps Automator", ["deployment", "ci", "infrastructure"], ["pipeline", "deployment plan"]))
    for role_id, name, caps, outputs in builtins:
        role = generate_role(role_id, name, caps, outputs)
        role["source"] = "builtin"
        add(role, "builtin")
    return list(roles.values())


def _match(requested, offered):
    if not requested:
        return 0.0, []
    matches = []
    offered = {value.strip().casefold() for value in offered}
    for requirement in requested:
        if requirement.strip().casefold() in offered:
            matches.append(requirement)
    return len(matches) / len(requested), matches


def recommend_roles(catalog, capabilities, deliverables=None, limit=3):
    caps, outputs = _strings(capabilities, "capabilities"), _strings(deliverables, "deliverables")
    if type(limit) is not int or limit < 0:
        raise ValueError("limit must be a non-negative integer.")
    results = []
    for role in catalog:
        if role.get("platform_compatible") is False:
            continue
        cap_score, cap_matches = _match(caps, role.get("capabilities", []))
        if not cap_matches:
            continue
        output_score, output_matches = _match(outputs, role.get("deliverables", []))
        platform_score = 1.0 if role.get("platform_compatible") is True else 0.0
        trust_score = role.get("provenance", {}).get("definition_trust", 0.4)
        if type(trust_score) not in (int, float):
            trust_score = 0.4
        trust_score = max(0.0, min(1.0, trust_score))
        score = 0.4 * cap_score + 0.25 * output_score + 0.2 * platform_score + 0.15 * trust_score
        if not outputs:
            score /= 0.75
        results.append(dict(role, score=round(score * 100, 2),
                            warnings=[] if role.get("status") == "available" else ["Native invocation is unverified; use the profile as a sequential prompt or verify with the host."],
                            match_evidence={"capabilities": cap_matches, "deliverables": output_matches,
                                            "capability_coverage": cap_score, "deliverable_coverage": output_score,
                                            "platform_compatibility": platform_score, "definition_trust": trust_score,
                                            "weights": {"C": 0.4, "D": 0.25, "P": 0.2, "T": 0.15},
                                            "normalization": "omit D and divide by 0.75" if not outputs else "none"}))
    return sorted(results, key=lambda role: (-role["score"], role["id"]))[:min(limit, 3)]


def install_role(root, role, platform="generic", approved=False, host=None):
    from .storage import project_lock, read_yaml, safe_path, validate_team, write_yaml

    root = Path(root)
    rendered = render_role(role, platform)
    target = safe_path(root, rendered["path"])
    verified_host = host_capabilities(platform, host)
    status = _status(dict(role, platforms=role.get("platforms", list(_ROLE_DIRS))), platform, verified_host)
    if status["status"] == "unavailable":
        raise ValueError("Role is incompatible with the selected platform.")
    result = {"id": role["id"], "source": role.get("source", "provided"),
              "source_path": role.get("source_path"), "target": rendered["path"],
              "path": rendered["path"], "permissions": ["write project role file", "update project team registry"],
              "content": rendered["content"], "approved": approved is True,
              "installed": False, "status": status["status"], "evidence": status["evidence"]}
    if approved is not True:
        result["action"] = "preview"
        return result
    with project_lock(root):
        # Recheck containment after acquiring the project lock.
        target = safe_path(root, rendered["path"])
        config_path = safe_path(root, ".agent-team/team.yaml")
        if not config_path.is_file():
            raise ValueError("Initialize the project before installing a role.")
        config = validate_team(read_yaml(config_path))
        members = config.get("team", config).setdefault("members", [])
        member = next((item for item in members if item["id"] == role["id"]), None)
        if member and member.get("definition") not in (None, rendered["path"]):
            raise ValueError("Role id already refers to a different definition.")
        existed = target.exists()
        if existed and target.read_text(encoding="utf-8") != rendered["content"]:
            raise ValueError("Role file already exists with different content; refusing to overwrite.")
        if member is None:
            member = {"id": role["id"]}
            members.append(member)
        # Approval installs one coherent profile while preserving user-owned scope
        # and unrelated member settings. Never pair old capabilities with a new prompt.
        member.update({"role": role.get("role", role["name"]), "name": role["name"],
                       "agent_id": role["id"], "definition": rendered["path"],
                       "capabilities": _strings(role.get("capabilities"), "capabilities"),
                       "deliverables": _strings(role.get("deliverables"), "deliverables"),
                       "platforms": _strings(role.get("platforms", list(_ROLE_DIRS)), "platforms"),
                       "status": "installed"})
        if "prompt" in member:
            member["prompt"] = role["prompt"]
        if "description" in role:
            member["description"] = role["description"]
        else:
            member.pop("description", None)
        validate_team(config)
        created = False
        try:
            if not existed:
                target.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive creation avoids replacing a concurrent external file.
                with target.open("x", encoding="utf-8") as handle:
                    created = True
                    handle.write(rendered["content"])
            write_yaml(config_path, config)
        except BaseException:
            if created and target.exists():
                target.unlink()
            raise
    result.update(installed=True, action="unchanged" if existed else "installed",
                  status="available" if status["status"] == "available" else "unavailable",
                  evidence=status["evidence"] if status["status"] == "available" else ["Installed role requires host verification before native invocation."])
    return result
