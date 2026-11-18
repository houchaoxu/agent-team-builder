<div align="center">

![Agent Team Builder — talk, build, remember](assets/banner.svg)

**Describe your goal. Get the team you need.**

Small tasks stay with one agent. Bigger tasks bring in specialists, with a team you can reuse next session.

[English](README.md) · [简体中文](README.zh-CN.md)

[![Tests](https://github.com/houchaoxu/agent-team-builder/actions/workflows/test.yml/badge.svg)](https://github.com/houchaoxu/agent-team-builder/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/houchaoxu/agent-team-builder)](https://github.com/houchaoxu/agent-team-builder/releases/latest)
![Python engine](https://img.shields.io/badge/engine-Python%203.9%2B-3776AB?logo=python&logoColor=white)
![Setup](https://img.shields.io/badge/setup-just%20ask%20your%20agent-14B8A6)

[Get started](#-get-started) · [Features](#-what-you-get) · [Updates](#-updates-and-notifications) · [Platforms & validation](#-platforms-and-validation)

</div>

---

**[v2.6.0 is available](https://github.com/houchaoxu/agent-team-builder/releases/tag/v2.6.0):** update reminders during use, conversational upgrades, and backup-based rollback. Stable releases include a complete Skill ZIP and SHA-256 checksum.

## 💬 Get started

Open your project in a development agent with file and command tools, then send:

```text
Install the latest stable Agent Team Builder for this project from
https://github.com/houchaoxu/agent-team-builder.
Follow INSTALL.md, handle environment setup,
and verify the installation and host loading status.
```

Your agent installs the complete Skill, prepares its internal tools, and enables the project entry point. **You don't need to run Python, pip, or CLI commands yourself.**

Then ask for what you want to build:

> Add an order management module with an API and frontend, and verify the result.

Once your host loads the project entry, **just describe your task — no need to mention Agent Team Builder again.**

Project installation is the default. Prefer a shared installation? Add **“Install it as a personal Skill.”** Each additional project still needs its own entry enabled. If your host hasn't discovered the Skill yet, your agent will explain whether a new session is needed.

Release files: [v2.6.0](https://github.com/houchaoxu/agent-team-builder/releases/tag/v2.6.0) · [Complete Skill ZIP](https://github.com/houchaoxu/agent-team-builder/releases/download/v2.6.0/agent-team-runtime-skill.zip) · [SHA-256](https://github.com/houchaoxu/agent-team-builder/releases/download/v2.6.0/agent-team-runtime-skill.zip.sha256)

## ✨ What you get

| | Capability | What it means for you |
| --- | --- | --- |
| 🧠 | **A team that persists** | Reuse your project's team in the next session. |
| 🎯 | **The right amount of help** | Small tasks stay with one agent; complex tasks get focused assistance. |
| 🤝 | **Clear ownership** | Dependencies and file boundaries keep parallel work coordinated. |
| 🧩 | **Roles that fit your request** | Your agent evaluates installed roles first, then searches a built-in fallback library when needed, using its own LLM to judge the candidates. |
| 📚 | **Project memory** | Keep useful decisions and lessons, with sources and revision history. |
| 🔄 | **Updates with a way back** | Get update reminders; authorize an upgrade with verification, backup, and rollback. |
| 📊 | **Honest execution records** | Track real outcomes and available metrics; unknown values stay unknown. |

### A conversation, not a control panel

| You say… | Your agent handles… |
| --- | --- |
| “Fix this button's color.” | A small change with one agent. |
| “Build the API and frontend.” | A plan, suitable roles, file ownership, and verification. |
| “Find and install a database specialist if our team needs one.” | Evaluate existing roles, find suitable library material, preview it, and install within your authorization. |
| “Remember this compatibility rule.” | A sourced project note for future work. |
| “Update the team tool.” | Preview, protect local changes, back up, upgrade, and verify. |
| “Snooze update reminders for 30 days.” | Pause automatic checks for the selected installation. |

These are usage examples. Actual delegation depends on the tools and permissions available in your current host.

## 🛠️ How it works

**Talk → choose the smallest useful team → execute → verify → remember.**

The Skill is the user-facing workflow. An optional Python engine handles configuration checks, dependency-aware plans, role installation, and persistent records. The host agent performs the actual model calls and tool work.

| Mode | When to use it |
| --- | --- |
| **Full engine** | Your agent uses Python 3.9+ and prepares dependencies in a private environment when needed. Includes configuration validation, write locks, task state, and metrics. |
| **Basic collaboration** | No Python available? Use host file tools for team instructions and Markdown records. Engine validation, write locks, and the Python updater are unavailable. |

Project data stays in `.agent-team/`. Existing project instructions are preserved outside the managed entry block. Installation does not change system Python or your global `PATH`.

The lightweight project entry keeps the workflow small:

1. **Assess the task.** Simple work runs directly, without loading the full Skill or team, scanning roles, or checking updates.
2. **Load only what helps.** For work that benefits from collaboration, read the existing `.agent-team/team.yaml`, selected roles, and relevant task records.
3. **Fill actual gaps.** Consult Marketplace only when existing roles cannot cover the task.
4. **Reuse next session.** Resume the same team without running initialization again.

Automatic routing depends on the host loading the entry. There is no unconditional startup hook or independent scheduling service.

### A fallback library, loaded as needed

The bundled index contains **283 role cards** from a pinned [Agency-Agents](https://github.com/msitarzewski/agency-agents) revision. Your agent checks installed roles first. When a capability is missing, local BM25/keyword retrieval and English/Chinese scenario aliases select **up to six capability cards by default**; your host LLM judges their meaning and fit. No extra model API, vector database, or repository clone is required. An empty retrieval result may need broader terms or another page; it does not prove a suitable role is absent.

Only a selected role's full profile is downloaded, from a pinned revision, checked against its indexed hash, and cached for reuse. Installation follows a preview and requires existing authorization or your confirmation. A request to automatically find and install missing specialists provides that authorization within its stated scope. Installing a profile does not prove the current host can immediately call a new native agent. The library is MIT-licensed upstream material; attribution and pinned provenance travel with the index and profiles. See the [role workflow](agent_team/skill/references/role-matching.md) for details.

## 🔄 Updates and notifications

**Automatic checks and reminders; installation after your authorization.** From 2.6.0, successful business operations through the Skill runner can check official stable Releases, with a default seven-day interval.

| When… | What happens |
| --- | --- |
| You open a project or start a session | No update check just for opening it. |
| You ask for a simple change | The agent works directly, without going online for updates. |
| The Skill runner completes a business operation and a check is due | A best-effort check runs; each new target version is announced once. |
| You authorize an upgrade | The updater previews, verifies the official release, backs up, and replaces managed Skill files. Local modifications cause a safe stop. |
| You disable checks or snooze reminders | Automatic update requests stop. |

Just ask:

- “Check for Agent Team Builder updates.”
- “Update to the latest stable version and keep a rollback backup.”
- “Snooze update reminders for 30 days.” or “Turn off automatic checks.”
- “Roll back the last update.”

Updates preserve installation scope, project teams, task history, and personal roles. Rollback restores the Skill backup while retaining current update preferences. Check failures do not affect your task. There is no background process, scheduled task, or startup check. An explicit request to check now can bypass the interval, disable, and snooze settings for that check only.

Checks read public official GitHub release information without uploading requirements, conversations, project files, or tokens. For independent notifications, select **Watch → Custom → Releases** on the repository. See the [update and rollback workflow](agent_team/skill/references/updates.md).

**Upgrading from 2.5.x or earlier?** Those installations have no updater and cannot notify you automatically. Ask: “Migrate Agent Team Builder to the latest stable version with update support; verify and back up my old installation first.” Your agent must verify the old source and preserve a complete backup before migrating it once.

## 🌍 Platforms and validation

| Host | Project entry | Execution |
| --- | --- | --- |
| **Codex** | `AGENTS.md` | Native subagents when verified; sequential handoffs otherwise. |
| **Claude Code** | `CLAUDE.md` | Host capabilities must be verified in the current session. |
| **Cursor** | `.cursor/rules/agent-team.mdc` | Uses the features actually available in your version. |
| **Gemini CLI** | `GEMINI.md` | Uses the features actually available in your version. |
| **Other agents** | Explicit Skill/instruction entry | Sequential role prompts and handoffs. |

Codex native delegation has been exercised in a real integration scenario. Other host adapters are provided; their actual discovery and execution still need verification in those hosts. A role file alone is never proof of a callable agent.

**Release 2.6.0 verification:**

- **206 tests**, passing across Linux, macOS, and Windows with Python 3.9 and 3.12 — [release CI](https://github.com/houchaoxu/agent-team-builder/actions/runs/44228301974).
- Published ZIP downloaded and checked against its checksum, installation manifest, and runtime version.
- Live GitHub update lookup, upgrade, and rollback exercised in an isolated installation.
- Codex task routing and native subagent delegation exercised in integration scenarios.

Cross-platform engine tests do not certify every host integration. Other hosts' native delegation and measured Token savings remain unverified. [Validation history](VALIDATION.md) records checks at each development stage; release CI above provides the subsequent cross-platform result.

## 📖 Go deeper

- [Installation contract](INSTALL.md) — instructions your agent follows.
- [Updates and rollback](agent_team/skill/references/updates.md) — checks, preferences, backups, and older-version migration.
- [CLI and engine reference](docs/CLI.md) — for developers and troubleshooting.
- [Skill workflow](agent_team/skill/SKILL.md) — orchestration and progressive loading.
- [Validation record](VALIDATION.md) — checks performed and remaining coverage gaps.
- [Examples](examples/) — task and host input formats for agent tooling.

**Contributions welcome:** reproducible bug reports, host integration results, documentation, and translations. [Open an issue](https://github.com/houchaoxu/agent-team-builder/issues) or send a pull request. Developer setup and test commands are in the [engine reference](docs/CLI.md#验证).
