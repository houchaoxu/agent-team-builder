<div align="center">

![Agent Team Builder — 对话、构建、记忆](assets/banner.svg)

**说出目标，按需配齐团队。**

小任务独立完成，复杂任务引入专家，下一次会话继续复用已有团队。

[English](README.md) · [简体中文](README.zh-CN.md)

[![Tests](https://github.com/houchaoxu/agent-team-builder/actions/workflows/test.yml/badge.svg)](https://github.com/houchaoxu/agent-team-builder/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/houchaoxu/agent-team-builder)](https://github.com/houchaoxu/agent-team-builder/releases/latest)
![Python 引擎](https://img.shields.io/badge/engine-Python%203.9%2B-3776AB?logo=python&logoColor=white)
![安装方式](https://img.shields.io/badge/setup-just%20ask%20your%20agent-14B8A6)

[开始使用](#-一句话开始) · [功能亮点](#-你会得到什么) · [更新回退](#-更新与通知) · [平台与验证](#-平台支持与验证)

</div>

---

**[v2.6.0 已发布](https://github.com/houchaoxu/agent-team-builder/releases/tag/v2.6.0)：** 使用时检查更新、提醒新版本，支持对话式升级与备份回退。稳定版提供完整 Skill ZIP 和 SHA-256 校验文件。

## 💬 一句话开始

在具有文件与命令工具的开发 Agent 中打开项目，然后告诉它：

```text
请从 https://github.com/houchaoxu/agent-team-builder
为当前项目安装 Agent Team Builder 最新稳定版。
按照仓库的 INSTALL.md 完成环境准备，
并验证安装结果和宿主加载状态。
```

Agent 会安装完整 Skill、准备内部工具并设置项目入口。**你无需手动运行 Python、pip 或 CLI 命令。**

之后，直接说你想做什么：

> 帮我完成订单管理模块的 API 和前端页面，并验证结果。

宿主加载项目入口后，**直接描述任务即可，无需再提及 Agent Team Builder。**

默认安装到当前项目。希望跨项目共用一份安装？补充一句 **“安装成我个人可用的 Skill”**，其他项目仍需分别启用项目入口。若宿主尚未发现新 Skill，Agent 会说明是否需要重新打开会话。

发行文件：[v2.6.0](https://github.com/houchaoxu/agent-team-builder/releases/tag/v2.6.0) · [完整 Skill ZIP](https://github.com/houchaoxu/agent-team-builder/releases/download/v2.6.0/agent-team-runtime-skill.zip) · [SHA-256](https://github.com/houchaoxu/agent-team-builder/releases/download/v2.6.0/agent-team-runtime-skill.zip.sha256)

## ✨ 你会得到什么

| | 能力 | 对你的帮助 |
| --- | --- | --- |
| 🧠 | **团队长期保存** | 下次打开项目，继续复用已有团队。 |
| 🎯 | **按需选择成员** | 小任务由一个 Agent 完成，复杂任务再找帮手。 |
| 🤝 | **明确分工边界** | 根据依赖与文件归属协调并行工作。 |
| 🧩 | **按需补齐角色** | 先评估已安装角色，不足时检索内置后备素材索引，由当前 Agent 的 LLM 判断候选是否适合。 |
| 📚 | **沉淀项目知识** | 保存有来源的决策与经验，并保留修订历史。 |
| 🔄 | **升级可回退** | 使用时提醒更新，授权后校验、备份并升级，支持回退。 |
| 📊 | **如实记录结果** | 记录真实交付与可取得的指标，未测数据保持未知。 |

### 你负责表达目标，Agent 负责安排

| 你说…… | Agent 处理…… |
| --- | --- |
| “改一下按钮颜色。” | 主 Agent 直接完成小改动。 |
| “开发这个模块的前后端。” | 拆解任务、选择角色、约定文件边界并验收。 |
| “团队缺数据库专家时，帮我找并安装合适的角色。” | 先评估现有角色，再检索素材、预览并在授权范围内安装。 |
| “记住这个接口兼容约定。” | 保存带来源的项目知识，供后续工作参考。 |
| “把团队工具更新一下。” | 预览更新、保护本地修改、备份、升级并验证。 |
| “30 天内别提醒更新。” | 暂停选定安装的自动检查。 |

以上为使用示例。实际委派取决于当前宿主提供的工具与权限。

## 🛠️ 它如何工作

**描述目标 → 选择必要成员 → 执行任务 → 验证结果 → 保留有用知识。**

Skill 提供面向用户的工作流程；可选的 Python 引擎负责配置校验、依赖编排、角色安装和持久化记录。实际模型调用与工具执行由宿主 Agent 完成。

| 模式 | 适用情况 |
| --- | --- |
| **完整引擎** | Agent 使用已有 Python 3.9+，必要时自动准备私有依赖环境；提供配置校验、写锁、任务状态与指标统计。 |
| **基础协作** | 没有 Python 时，使用宿主文件工具维护团队指令和 Markdown 记录；不具备引擎校验、写锁，也无法使用 Python 更新器。 |

项目数据保存在 `.agent-team/`。已有项目指令在托管入口块之外的内容会保留。安装不修改系统 Python，也不改全局 `PATH`。

轻量项目入口让每次使用都按需展开：

1. **先判断任务。** 简单任务直接完成，不加载完整 Skill 或团队，不扫描角色，也不检查更新。
2. **只读需要的内容。** 确有协作收益时，才读取已有 `.agent-team/team.yaml`、选中角色和相关任务记录。
3. **有缺口再补齐。** 现有角色无法覆盖任务时，才检索 Marketplace。
4. **下次继续复用。** 恢复同一团队，不重复运行初始化。

自动判断依赖宿主加载项目入口；没有无条件启动钩子或独立调度后台。

### 按需加载的后备素材库

内置固定版本 [Agency-Agents](https://github.com/msitarzewski/agency-agents) 的 **283 张角色卡**。Agent 先检查已安装角色；有能力缺口时，再用本地 BM25 / 关键词检索和中英文场景别名，**默认筛出最多 6 张能力卡**，交给宿主 LLM 判断含义与适用性。无需额外模型 API、向量库或 clone 素材仓库。检索为空时可能需要补充词义或翻页，不能直接断言没有合适角色。

选中后才按固定 revision 下载完整角色，校验索引中的 hash，并缓存复用。安装先预览，只在已有授权或用户确认后写入；用户已要求自动寻找并安装缺失专家时，可在该授权范围内连续完成。安装角色文件不代表当前宿主能立即调用新的原生 Agent。上游素材采用 MIT 许可证，索引和角色保留署名与固定版本来源。详细流程见[语义角色推荐](agent_team/skill/references/role-matching.md)。

## 🔄 更新与通知

**自动检查与提醒，用户授权后安装更新。** 从 2.6.0 起，Skill runner 成功完成业务操作后，可以检查官方稳定 Release，默认间隔 7 天。

| 场景 | 实际行为 |
| --- | --- |
| 打开项目或开启新会话 | 不会仅因打开而检查更新。 |
| 处理简单改动 | Agent 直接执行，不为更新联网。 |
| Skill runner 成功完成业务操作，且到了检查时间 | 尝试检查更新；同一目标版本只提醒一次。 |
| 你授权升级 | 预览、校验官方发行包、备份并替换托管 Skill 文件；发现本地修改时停止覆盖。 |
| 关闭检查或静默提醒 | 停止自动更新请求。 |

直接对 Agent 说：

- “检查 Agent Team Builder 有没有更新。”
- “更新到最新稳定版，保留可回退备份。”
- “30 天内别提醒更新。”或“关闭自动检查。”
- “回退刚才的更新。”

升级保留安装范围、项目团队、任务历史和个人角色；回退恢复 Skill 备份，并保留当前更新偏好。检查失败不影响当前任务。没有常驻进程、定时任务或启动检查。主动要求立即检查，可以单次绕过间隔、关闭和静默设置，不改变长期偏好。

检查只读取官方 GitHub 公共发行信息，不上传需求、对话、项目文件或 token。也可在仓库点击 **Watch → Custom → Releases**，独立订阅发布通知。操作细节见[更新与回退](agent_team/skill/references/updates.md)。

**从 2.5.x 或更早版本升级？** 这些安装没有更新器，无法自动通知。告诉 Agent：“把 Agent Team Builder 迁移到支持更新的最新稳定版，先验证旧安装并备份。” Agent 须先核实旧版来源、保留完整备份，再完成一次迁移。

## 🌍 平台支持与验证

| 宿主 | 项目入口 | 执行方式 |
| --- | --- | --- |
| **Codex** | `AGENTS.md` | 验证能力后使用原生子 Agent，否则顺序交接。 |
| **Claude Code** | `CLAUDE.md` | 以当前会话实际提供的能力为准。 |
| **Cursor** | `.cursor/rules/agent-team.mdc` | 使用当前版本实际具备的功能。 |
| **Gemini CLI** | `GEMINI.md` | 使用当前版本实际具备的功能。 |
| **其他 Agent** | 显式 Skill / 指令入口 | 角色 Prompt 与顺序工作流。 |

Codex 原生委派已完成真实集成验收。其他平台提供了适配器，实际发现与执行仍需在对应宿主验证。角色文件存在，不代表角色已经可以调用。

**2.6.0 发行验证：**

- **206 项测试**，在 Linux、macOS、Windows 与 Python 3.9、3.12 的六种组合全部通过——[发行版 CI](https://github.com/houchaoxu/agent-team-builder/actions/runs/44228301974)。
- 实际下载已发布 ZIP，核对校验文件、安装 manifest 和运行时版本。
- 在隔离安装中完成真实 GitHub 更新查询、升级与回退。
- 已验收 Codex 的任务路由与原生子 Agent 委派场景。

跨平台引擎测试不等于所有宿主集成都已认证。其他宿主的原生委派和真实 Token 节省幅度仍未验证。[验证历史](VALIDATION.md)按开发阶段记录检查，上方发行版 CI 提供后续跨平台结果。

## 📖 继续了解

- [安装契约](INSTALL.md)：交给 Agent 阅读并执行。
- [更新与回退](agent_team/skill/references/updates.md)：检查偏好、备份和旧版迁移。
- [CLI 与引擎参考](docs/CLI.md)：开发、排障时按需查看。
- [Skill 工作流](agent_team/skill/SKILL.md)：任务编排与分层加载。
- [验证记录](VALIDATION.md)：已执行的检查与覆盖缺口。
- [输入示例](examples/)：供 Agent 内部工具使用的任务和宿主格式。

**欢迎参与：** 提交可复现的问题、平台集成结果、文档改进或翻译。可以[创建 Issue](https://github.com/houchaoxu/agent-team-builder/issues)或提交 Pull Request。开发环境与测试命令见[引擎参考](docs/CLI.md#验证)。
