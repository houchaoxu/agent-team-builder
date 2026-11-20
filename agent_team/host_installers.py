"""Native Skill installation adapters for supported coding-agent hosts."""
from pathlib import Path


class SkillDirectoryInstaller:
    """Install the shared Skill bundle into a host's native discovery path."""

    def __init__(self, platform, project_path, user_path, activation):
        self.platform = platform
        self.project_path = project_path
        self.user_path = user_path
        self.activation = activation

    def destination(self, project, scope, home):
        if scope == "project":
            return Path(project) / self.project_path
        if scope == "user":
            return Path(home) / self.user_path
        raise ValueError("Unsupported installation scope: " + str(scope))

    def install(self, export_bundle, project, scope, home, destination=None):
        destination = Path(destination) if destination is not None else self.destination(project, scope, home)
        result = export_bundle(destination)
        result.update(platform=self.platform, scope=scope,
                      installed_globally=scope == "user",
                      installer={"id": self.platform, "mechanism": "native-skill-directory"},
                      activation={"state": "host_native_discovery", "executed": False,
                                  "instructions": self.activation})
        return result


HOST_INSTALLERS = {
    "codex": SkillDirectoryInstaller(
        "codex", ".agents/skills/agent-team-runtime", ".agents/skills/agent-team-runtime",
        "Codex discovers project Skills from .agents/skills and user Skills from ~/.agents/skills. "
        "The Skill is available after the host scans or reloads Skills."),
    "claude-code": SkillDirectoryInstaller(
        "claude-code", ".claude/skills/agent-team-runtime", ".claude/skills/agent-team-runtime",
        "Claude Code discovers project Skills from .claude/skills and user Skills from ~/.claude/skills. "
        "The Skill is available after the host scans or reloads Skills."),
    "trae": SkillDirectoryInstaller(
        "trae", ".trae/skills/agent-team-runtime", ".trae/skills/agent-team-runtime",
        "Verify TRAE project Skills are enabled and discovered; file installation does not prove subagent support."),
    "pi": SkillDirectoryInstaller(
        "pi", ".agents/skills/agent-team-runtime", ".agents/skills/agent-team-runtime",
        "Use /reload or restart Pi after installing Skills into an already-running session; verify delegation separately."),
}


def installer_for(platform):
    return HOST_INSTALLERS.get(platform)
