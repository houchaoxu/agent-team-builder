<!-- agent-team-runtime:begin -->
At each new session or task, assess collaboration value from the request and available context; users need not mention Agent Team Builder.
Default to one agent. Handle simple tasks directly, without loading the full team configuration or Skill.
Do not run setup, init, status, doctor, or role scans merely because a session started.
For complex tasks with clear collaboration value, use the installed agent-team-runtime Skill and read its SKILL.md for the workflow contract.
Reuse the existing .agent-team/team.yaml team across sessions; do not recreate it or run init to resume.
Load only selected roles and relevant task records; consult Marketplace only for a demonstrated role or capability gap.
Initialize only for first enablement; preserve damaged configuration and report it. Explicit installation, upgrade, repair, or diagnostic requests follow their own workflow.
Delegate only within existing user authorization and host restrictions, with explicit host capability evidence.
Locate agent-team-runtime through the host's discovered Skills.
For a project installation, read .agents/skills/agent-team-runtime/SKILL.md; in this source repository, read agent_team/skill/SKILL.md.
If neither is available, use the host's installation/discovery workflow before enabling team features.
<!-- agent-team-runtime:end -->
