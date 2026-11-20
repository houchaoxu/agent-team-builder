"""Conservative host capability checks and project-local role formats."""

import json
import re

import yaml

from .platforms import PLATFORMS
_ROLE_DIRS = {
    "codex": ".codex/agents", "claude-code": ".claude/agents",
    "cursor": ".cursor/agents", "gemini-cli": ".gemini/agents",
    "generic": ".agent-team/roles",
}
# These portable definitions support handoffs. Agency's installer, not this
# generic renderer, produces the native formats for the additional tools.
_ROLE_DIRS.update({tool: ".agent-team/roles/" + tool for tool in PLATFORMS if tool not in _ROLE_DIRS})
_ROLE_DIRS.update({
    # These hosts consume Agent Skills, not Agency's native agent formats.
    "trae": ".trae/skills",
    "pi": ".agents/skills",
    # WorkBuddy's public docs expose UI import, not a stable on-disk directory.
    "workbuddy": ".agent-team/workbuddy-imports",
})
SKILL_PLATFORMS = ("trae", "pi", "workbuddy")


def _platform(platform):
    if platform not in PLATFORMS:
        raise ValueError("Unsupported platform: %s" % platform)
    return platform


def detect_platform(root, env=None):
    """Detect configuration context, without asserting execution capability."""
    from .hosts import detect_host
    return detect_host(root, env)


def capabilities(platform, host=None):
    from .hosts import negotiate
    result = negotiate(platform, host)
    verified = result["native_subagents"] is True
    result.update(native_subagents=verified, capability_evidence=result["evidence"],
                  strategy="native_subagents" if verified else "single_agent")
    return result


def entry_path(platform):
    _platform(platform)
    return {"claude-code": "CLAUDE.md", "cursor": ".cursor/rules/agent-team.mdc",
            "trae": ".trae/rules/agent-team-runtime.md",
            "gemini-cli": "GEMINI.md"}.get(platform, "AGENTS.md")


def entry_text(platform):
    _platform(platform)
    skill_path = {
        "codex": ".agents/skills/agent-team-runtime/SKILL.md",
        "pi": ".agents/skills/agent-team-runtime/SKILL.md",
        "claude-code": ".claude/skills/agent-team-runtime/SKILL.md",
        "trae": ".trae/skills/agent-team-runtime/SKILL.md",
    }.get(platform, ".agents/skills/agent-team-runtime/SKILL.md")
    text = ("<!-- agent-team-runtime:begin -->\n"
            "At each new session or task, assess collaboration value from the request and available context; users need not mention Agent Team Builder.\n"
            "Default to one agent. Handle simple tasks directly, without loading the full team configuration or Skill.\n"
            "Do not run setup, init, status, doctor, or role scans merely because a session started.\n"
            "For complex tasks with clear collaboration value, use the installed agent-team-runtime Skill and read its SKILL.md for the workflow contract.\n"
            "Reuse the existing .agent-team/team.yaml team across sessions; do not recreate it or run init to resume.\n"
            "Load only selected roles and relevant task records; consult Marketplace only for a demonstrated role or capability gap.\n"
            "Initialize only for first enablement; preserve damaged configuration and report it. Explicit installation, upgrade, repair, or diagnostic requests follow their own workflow.\n"
            "Delegate only within existing user authorization and host restrictions, with explicit host capability evidence.\n"
            "Locate agent-team-runtime through the host's discovered Skills.\n"
            "For a project installation, read " + skill_path + "; in this source repository, read agent_team/skill/SKILL.md.\n"
            "If neither is available, use the host's installation/discovery workflow before enabling team features.\n"
            "<!-- agent-team-runtime:end -->\n")
    if platform == "cursor":
        return '---\ndescription: Agent Team Runtime project entry\nalwaysApply: true\n---\n\n' + text
    if platform == "trae":
        return '---\nalwaysApply: true\n---\n\n' + text
    if platform == "workbuddy":
        note = ("WorkBuddy Skills are imported through the Skills UI. A project file alone does not confirm "
                "that WorkBuddy loaded this Skill; verify it appears in the current project's Skills.\n")
        return text.replace("<!-- agent-team-runtime:end -->", note + "<!-- agent-team-runtime:end -->")
    if platform == "pi":
        note = ("Pi discovers project Skills in .agents/skills. Use /reload or restart the session after "
                "installing a Skill into an already-running session.\n")
        return text.replace("<!-- agent-team-runtime:end -->", note + "<!-- agent-team-runtime:end -->")
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
    if platform in SKILL_PLATFORMS:
        # These targets accept Agent Skills-style instructions. A Skill is not
        # a native callable subagent, so callers must keep that distinction.
        metadata = {"name": role_id, "description": description,
                    "metadata": {"agent_team_role_id": role_id, "agent_team_role_name": name.strip(),
                                 "agent_team_capabilities": role.get("capabilities", []),
                                 "agent_team_deliverables": role.get("deliverables", [])}}
        content = "---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + "---\n\n"
        content += "# " + name.strip() + "\n\n" + prompt.rstrip() + "\n"
        suffix = "/SKILL.md"
    elif platform == "codex":
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
