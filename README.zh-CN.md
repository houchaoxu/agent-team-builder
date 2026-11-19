<div align="center">

![Agent Team Builder — 对话、构建、记忆](assets/banner.svg)

**说出目标，按需配齐团队。**

小任务独立完成，复杂任务引入专家，下一次会话继续复用已有团队。

[English](README.md) · [简体中文](README.zh-CN.md)

[![Tests](https://github.com/houchaoxu/agent-team-builder/actions/workflows/test.yml/badge.svg)](https://github.com/houchaoxu/agent-team-builder/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/houchaoxu/agent-team-builder)](https://github.com/houchaoxu/agent-team-builder/releases/latest)
![Python 引擎](https://img.shields.io/badge/engine-Python%203.9%2B-3776AB?logo=python&logoColor=white)
![安装方式](https://img.shields.io/badge/setup-just%20ask%20your%20agent-14B8A6)

[开始使用](#-一句话开始) · [功能亮点](#-你会得到什么) · [工作方式](#-它如何工作) · [更多文档](#-继续了解)

</div>

---

Agent Team Builder 让你的开发 Agent 拥有一支可复用的项目团队：按任务选择专家、协调分工，并把有用的决策留给下一次会话。

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

## ✨ 你会得到什么

| | 能力 | 对你的帮助 |
| --- | --- | --- |
| 🧠 | **团队长期保存** | 下次打开项目，继续复用已有团队。 |
| 🎯 | **按需选择成员** | 小任务由一个 Agent 完成，复杂任务再找帮手。 |
| 🤝 | **明确分工边界** | 根据依赖与文件归属协调并行工作。 |
| 🧩 | **按需补齐角色** | 由当前 Agent 的 LLM 判断候选，展示更合适的角色供你选择，手动确认后安装。 |
| 📚 | **沉淀项目知识** | 保存有来源的决策与经验，并保留修订历史。 |
| 📊 | **如实记录结果** | 记录真实交付与可取得的指标，未测数据保持未知。 |

### 你负责表达目标，Agent 负责安排

| 你说…… | Agent 处理…… |
| --- | --- |
| “改一下按钮颜色。” | 主 Agent 直接完成小改动。 |
| “开发这个模块的前后端。” | 拆解任务、选择角色、约定文件边界并验收。 |
| “找一个合适的 Agent 来优化这个界面。” | 比较现有角色与专业需求，展示候选供点选，预览并等待你确认安装。 |
| “记住这个接口兼容约定。” | 保存带来源的项目知识，供后续工作参考。 |

以上为使用示例。实际委派取决于当前宿主提供的工具与权限。

## 🛠️ 它如何工作

**描述目标 → 选择必要成员 → 执行任务 → 验证结果 → 保留有用知识。**

Skill 提供面向用户的工作流程；可选的 Python 引擎负责配置校验、依赖编排、角色安装和持久化记录。实际模型调用与工具执行由宿主 Agent 完成。

| 模式 | 适用情况 |
| --- | --- |
| **完整引擎** | Agent 使用已有 Python 3.9+，必要时自动准备私有依赖环境；提供配置校验、写锁、任务状态与指标统计。 |
| **基础协作** | 没有 Python 时，使用宿主文件工具维护团队指令和 Markdown 记录；不具备完整引擎的校验与写锁保障。 |

项目数据保存在 `.agent-team/`。已有项目指令在托管入口块之外的内容会保留。安装不修改系统 Python，也不改全局 `PATH`。

轻量项目入口让每次使用都按需展开：

1. **先判断任务。** 简单任务直接完成，不加载完整 Skill 或团队，也不扫描角色。
2. **只读需要的内容。** 确有协作收益时，才读取已有 `.agent-team/team.yaml`、选中角色和相关任务记录。
3. **有缺口再补齐。** 现有角色无法覆盖任务时，才检索 Marketplace。
4. **下次继续复用。** 恢复同一团队，不重复运行初始化。

自动判断依赖宿主加载项目入口；没有无条件启动钩子或独立调度后台。

### 按需加载的后备素材库

内置固定版本 [Agency-Agents](https://github.com/msitarzewski/agency-agents) 的 **283 张角色卡**。Agent 先检查已安装角色；有能力缺口时，再用本地 BM25 / 关键词检索和中英文场景别名，**默认筛出最多 6 张能力卡**，交给宿主 LLM 判断含义与适用性。无需额外模型 API、向量库或 clone 素材仓库。检索为空时可能需要补充词义或翻页，不能直接断言没有合适角色。

**匹配 → 选择角色 → 预览安装 → 手动确认 → 使用。** 宿主支持交互问答时提供可点击的候选列表，否则提供编号列表；你可以选择角色，也可以跳过安装。完整资料按需从固定 revision 下载，校验 hash 并缓存复用。Agent 展示来源、目标位置与写入范围，收到你对具体安装的明确确认后才写入；选中候选或默认预选不等于同意安装。

**把角色装进你正在使用的工具。** 复用 Agency-Agents 随包提供的适配器，为 Codex、Claude Code、OpenCode、Qwen、Cursor 等工具生成对应的角色、规则或 Skill 格式。默认安装到当前项目，用户范围安装需由你明确选择；转换和安装都由 Agent 处理。具体见[支持目标与环境要求](agent_team/skill/references/agency-installation.md)，文件安装后仍需验证宿主发现状态。

安装后的角色若尚不能原生调用，可在宿主支持时将其专业指令交给通用子 Agent，或由主 Agent 按角色指令顺序执行，并说明实际执行方式。上游素材采用 MIT 许可证，索引和角色保留署名与固定版本来源。详细流程见[语义角色推荐](agent_team/skill/references/role-matching.md)。

## 📖 继续了解

- [安装契约](INSTALL.md)：交给 Agent 阅读并执行。
- [CLI 与引擎参考](docs/CLI.md)：开发、排障时按需查看。
- [Skill 工作流](agent_team/skill/SKILL.md)：任务编排与分层加载。
- [输入示例](examples/)：供 Agent 内部工具使用的任务和宿主格式。

**欢迎参与：** 提交可复现的问题、平台集成结果、文档改进或翻译。可以[创建 Issue](https://github.com/houchaoxu/agent-team-builder/issues)或提交 Pull Request。开发环境与测试命令见[引擎参考](docs/CLI.md#验证)。
