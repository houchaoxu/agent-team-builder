"""Conservative host capability checks and project-local role formats."""

import json
import os
import re
from pathlib import Path

import yaml

PLATFORMS = ("codex", "claude-code", "cursor", "gemini-cli", "generic")
_ROLE_DIRS = {
    "codex": ".codex/agents", "claude-code": ".claude/agents",
    "cursor": ".cursor/agents", "gemini-cli": ".gemini/agents",
    "generic": ".agent-team/roles",
}


def _platform(platform):
    if platform not in PLATFORMS:
        raise ValueError("Unsupported platform: %s" % platform)
    return platform


def detect_platform(root, env=None):
    """Detect configuration context, without asserting execution capability."""
    env = os.environ if env is None else env
    explicit = env.get("AGENT_TEAM_PLATFORM")
    if explicit:
        return _platform(explicit)
    markers = (("CODEX_THREAD_ID", "codex"), ("CODEX_HOME", "codex"),
               ("CLAUDE_CODE_ENTRYPOINT", "claude-code"),
               ("CURSOR_AGENT", "cursor"), ("GEMINI_CLI", "gemini-cli"))
    for marker, platform in markers:
        if env.get(marker):
            return platform
    root = Path(root)
    for directory, platform in ((".codex", "codex"), (".claude", "claude-code"),
                                (".cursor", "cursor"), (".gemini", "gemini-cli")):
        if (root / directory).is_dir():
            return platform
    return "generic"


def capabilities(platform, host=None):
    _platform(platform)
    host = host or {}
    evidence = host.get("evidence")
    verified = host.get("native_subagents") is True and isinstance(evidence, str) and bool(evidence.strip())
    agents = host.get("available_agents", [])
    agents = list(dict.fromkeys(a for a in agents if isinstance(a, str) and a.strip())) if isinstance(agents, list) else []
    parallel = host.get("max_parallel_agents", 3)
    parallel = min(3, max(1, parallel)) if type(parallel) is int else 3
    result = {
        "platform": platform, "native_subagents": verified,
        "evidence": evidence.strip() if verified else None,
        "available_agents": agents if verified else [],
        "max_parallel_agents": parallel if verified else 0,
        "strategy": "native_subagents" if verified else "single_agent",
        "warnings": [] if verified else ["Native subagent execution requires explicit host capability evidence."],
    }
    explicit_evidence = isinstance(evidence, str) and bool(evidence.strip())
    for field in ("shared_workspace", "worktree", "parallel_writes", "results_errors"):
        value = host.get(field)
        result[field] = value if explicit_evidence and type(value) is bool else None
    constraints = host.get("permission_constraints")
    result["permission_constraints"] = (list(constraints) if explicit_evidence and isinstance(constraints, list)
                                         and all(isinstance(item, str) for item in constraints) else None)
    result["capability_evidence"] = evidence.strip() if explicit_evidence else None
    return result


def entry_path(platform):
    _platform(platform)
    return {"claude-code": "CLAUDE.md", "cursor": ".cursor/rules/agent-team.mdc",
            "gemini-cli": "GEMINI.md"}.get(platform, "AGENTS.md")


def entry_text(platform):
    _platform(platform)
    text = ("<!-- agent-team-runtime:begin -->\n"
            "Default to one agent. Handle simple tasks without loading the full team configuration.\n"
            "For complex tasks, use the installed agent-team-runtime Skill and read its SKILL.md for the workflow contract.\n"
            "The agent handles its bundled tools and environment setup; users only describe their goals in conversation.\n"
            "Reuse the existing .agent-team/team.yaml team across sessions; do not recreate it.\n"
            "Then load only the roles and task records needed for the current task.\n"
            "Delegate only within existing user authorization and host restrictions, with explicit host capability evidence.\n"
            "Locate agent-team-runtime through the host's discovered Skills.\n"
            "For a project installation, read .agents/skills/agent-team-runtime/SKILL.md; in this source repository, read agent_team/skill/SKILL.md.\n"
            "If neither is available, use the host's installation/discovery workflow before enabling team features.\n"
            "<!-- agent-team-runtime:end -->\n")
    if platform == "cursor":
        return '---\ndescription: Agent Team Runtime project entry\nalwaysApply: true\n---\n\n' + text
    return text


def render_role(role, platform):
    _platform(platform)
    role_id = role.get("id", "")
    if not isinstance(role_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", role_id):
        raise ValueError("Role id must contain only letters, numbers, underscores or hyphens (max 80).")
    name, prompt = role.get("name"), role.get("prompt")
    if not isinstance(name, str) or not name.strip() or not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Role name and prompt must be non-empty strings.")
    description = role.get("description") or "Specialist role: " + name
    if not isinstance(description, str):
        raise ValueError("Role description must be a string.")
    if platform == "codex":
        # JSON basic strings are valid TOML basic strings for ordinary Unicode text.
        content = "\n".join('%s = %s' % (key, json.dumps(value, ensure_ascii=False))
                            for key, value in (("name", role_id), ("description", description),
                                               ("developer_instructions", prompt))) + "\n"
        suffix = ".toml"
    else:
        metadata = {"name": role_id, "description": description}
        if platform == "gemini-cli":
            metadata["kind"] = "local"
        content = "---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + "---\n\n" + prompt.rstrip() + "\n"
        suffix = ".md"
    return {"path": _ROLE_DIRS[platform] + "/" + role_id + suffix, "content": content}
