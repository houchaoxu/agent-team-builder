<div align="center">

![Agent Team Builder — talk, build, remember](assets/banner.svg)

**Your project. A team that remembers.**

Build persistent, on-demand agent teams — starting with a conversation.

[English](README.md) · [简体中文](README.zh-CN.md)

[![Tests](https://github.com/houchaoxu/agent-team-builder/actions/workflows/test.yml/badge.svg)](https://github.com/houchaoxu/agent-team-builder/actions/workflows/test.yml)
![Python engine](https://img.shields.io/badge/engine-Python%203.9%2B-3776AB?logo=python&logoColor=white)
![Setup](https://img.shields.io/badge/setup-just%20ask%20your%20agent-14B8A6)

[Get started](#-get-started) · [Features](#-what-you-get) · [Platforms](#-bring-your-agent) · [Documentation](#-go-deeper)

</div>

---

## 💬 Get started

Open your project in a development agent with file and command tools, then send:

```text
Install Agent Team Builder from https://github.com/houchaoxu/agent-team-builder
for this project. Follow INSTALL.md, handle environment setup,
and verify the installation.
```

Your agent installs the complete Skill, prepares its internal tools, and enables the project entry point. **You don't need to run Python, pip, or CLI commands yourself.**

Then ask for what you want to build:

> Add an order management module with an API and frontend, and verify the result.

Prefer one installation across projects? Add **“Install it as a personal Skill.”** Project installation is the default. If your host hasn't discovered the Skill yet, your agent will explain whether a new session is needed.

## ✨ What you get

| | Capability | What it means for you |
| --- | --- | --- |
| 🧠 | **A team that persists** | Reuse your project's team in the next session. |
| 🎯 | **The right amount of help** | Small tasks stay with one agent; complex tasks get focused assistance. |
| 🤝 | **Clear ownership** | Dependencies and file boundaries keep parallel work coordinated. |
| 🧩 | **Roles that fit your request** | Your agent evaluates installed roles first, then searches a built-in fallback library when needed, using its own LLM to judge the candidates. |
| 📚 | **Project memory** | Keep useful decisions and lessons, with sources and revision history. |
| 📊 | **Honest execution records** | Track real outcomes and available metrics; unknown values stay unknown. |

### A conversation, not a control panel

| You say… | Your agent handles… |
| --- | --- |
| “Fix this button's color.” | A small change with one agent. |
| “Build the API and frontend.” | A plan, suitable roles, file ownership, and verification. |
| “Find and install a database specialist if our team needs one.” | Evaluate existing roles, find suitable library material, preview it, and install within your authorization. |
| “Remember this compatibility rule.” | A sourced project note for future work. |

These are usage examples. Actual delegation depends on the tools and permissions available in your current host.

## 🛠️ How it works

**Talk → choose the smallest useful team → execute → verify → remember.**

The Skill is the user-facing workflow. An optional Python engine handles configuration checks, dependency-aware plans, role installation, and persistent records. The host agent performs the actual model calls and tool work.

| Mode | When to use it |
| --- | --- |
| **Full engine** | Your agent uses Python 3.9+ and prepares dependencies in a private environment when needed. Includes configuration validation, write locks, task state, and metrics. |
| **Basic collaboration** | No Python available? Use host file tools for team instructions and Markdown records. This mode does not provide the engine's locking or validation guarantees. |

Project data stays in `.agent-team/`. Existing project instructions are preserved outside the managed entry block. Installation does not change system Python or your global `PATH`.

Once your host loads the lightweight project entry, each new session or task starts with a quick collaboration decision. **Just describe your task; you don't need to mention Agent Team Builder.** Simple work runs directly without loading the Skill or team. Work that benefits from collaboration loads the existing team and selected roles; Marketplace is consulted only for an actual capability gap. Resuming does not run initialization, diagnostics, or role installation, and no unconditional startup hook is added. Automatic routing depends on the host loading the entry; the engine cannot intercept opening a project.

### A fallback library, loaded as needed

Version 2.5.0 includes a compact index of [Agency-Agents](https://github.com/msitarzewski/agency-agents) role material. Your agent first checks existing installed roles. If they leave a capability gap, local keyword retrieval and English/Chinese scenario aliases select up to six capability cards by default; your host LLM judges their meaning and fit. This uses no embeddings, extra model API, or repository clone. An empty retrieval result can require broader terms or another page; it does not prove a suitable role is absent.

Only a selected role's full profile is downloaded, from a pinned revision, checked against its indexed hash, and cached for reuse. Installation follows a preview and requires existing authorization or your confirmation. A request to automatically find and install missing specialists provides that authorization within its stated scope. Installing a profile does not prove the current host can immediately call a new native agent. The library is MIT-licensed upstream material; attribution and pinned provenance travel with the index and profiles. See the [role workflow](agent_team/skill/references/role-matching.md) for details.

## 🌍 Bring your agent

| Host | Project entry | Execution |
| --- | --- | --- |
| **Codex** | `AGENTS.md` | Native subagents when verified; sequential handoffs otherwise. |
| **Claude Code** | `CLAUDE.md` | Host capabilities must be verified in the current session. |
| **Cursor** | Project rules | Uses the features actually available in your version. |
| **Gemini CLI** | `GEMINI.md` | Uses the features actually available in your version. |
| **Other agents** | Explicit Skill/instruction entry | Sequential role prompts and handoffs. |

Codex native delegation has been exercised in a real integration scenario. Other host adapters are provided; their actual discovery and execution still need verification in those hosts. A role file alone is never proof of a callable agent.

## 📖 Go deeper

- [Installation contract](INSTALL.md) — instructions your agent follows.
- [CLI and engine reference](docs/CLI.md) — for developers and troubleshooting.
- [Skill workflow](agent_team/skill/SKILL.md) — orchestration and progressive loading.
- [Validation record](VALIDATION.md) — checks performed and remaining coverage gaps.
- [Examples](examples/) — task and host input formats for agent tooling.

**Contributions welcome:** reproducible bug reports, host integration results, documentation, and translations. [Open an issue](https://github.com/houchaoxu/agent-team-builder/issues) or send a pull request. Developer setup and test commands are in the [engine reference](docs/CLI.md#验证).
