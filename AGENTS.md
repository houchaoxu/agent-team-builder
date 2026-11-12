<!-- agent-team-runtime:begin -->
Default to one agent. Handle simple tasks without loading the full team configuration.
For complex tasks, use the installed agent-team-runtime Skill and read its SKILL.md for the workflow contract.
The agent handles its bundled tools and environment setup; users only describe their goals in conversation.
Reuse the existing .agent-team/team.yaml team across sessions; do not recreate it.
Then load only the roles and task records needed for the current task.
Delegate only within existing user authorization and host restrictions, with explicit host capability evidence.
Locate agent-team-runtime through the host's discovered Skills.
For a project installation, read .agents/skills/agent-team-runtime/SKILL.md; in this source repository, read agent_team/skill/SKILL.md.
If neither is available, use the host's installation/discovery workflow before enabling team features.
<!-- agent-team-runtime:end -->
