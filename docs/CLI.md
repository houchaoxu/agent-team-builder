# 内部引擎与 CLI 参考

项目级、可恢复、按需调度的 Agent Team Runtime。实现[需求方案](https://chatgpt.com/s/t_6af52790b7c481919c628336c14738b5)中的团队注册表、任务编排、角色市场、项目记忆和真实数据统计。

本文件面向开发者和排障。普通用户通过对话安装和使用，见仓库根 README。以下命令由 Agent 内部执行，也可以通过自包含 Skill 的 `scripts/run.py` 调用。自然语言理解和实际 Agent 执行使用当前宿主已有能力；CLI 不会把生成计划标记为执行成功。

## 安装与首次使用

Python 3.9+：

```sh
python3 -m pip install -e .
agent-team --project /absolute/path/to/project --platform codex init
agent-team --project /absolute/path/to/project status
```

未安装命令时，可在本仓库使用 `python3 -m agent_team`。支持 `codex`、`claude-code`、`cursor`、`gemini-cli` 和 `generic`；`auto` 只判断平台类型，不能证明平台具备 Subagents。

所有参数 `--project`、`--platform`、`--host` 放在子命令之前。输出为 JSON；失败输出结构化错误到 stderr，退出码 2。

初始化会写入 `.agent-team/team.yaml`、调度策略、成员/记忆/任务目录及对应平台的轻量入口。已有团队恢复使用，损坏配置报错并保留原文件。入口只增加有标记的托管内容，保留用户原有规则；不会自动写用户全局 Agent 配置。多个项目有各自的身份和状态。

```text
your-project/
  AGENTS.md                      # Codex 示例入口
  .agent-team/
    team.yaml                    # L2 团队索引
    orchestration.yaml           # 调度阈值、并发上限
    members/                     # L3 选中时才读角色正文
    memory/                      # 有来源的长期知识
    tasks/                       # 单个需求的状态和结果
```

将本项目 Skill 导出后放入目标宿主支持的 skills 目录：

```sh
agent-team skill /tmp/agent-team-runtime
```

源码开发时可直接读取 `agent_team/skill/SKILL.md`。发行导出包包含 runtime，目标不存在时创建，完全相同则幂等复用，不同内容拒绝覆盖。Skill 的发现/启用由宿主控制；此命令不修改全局设置。初始化一个项目之后，其轻量入口可以在后续会话中引导恢复，并在复杂任务时读取已安装 Skill 的契约；`guide` 也可按需输出。首次进入尚未初始化的其他项目，需要已启用该 Skill 的宿主按其流程执行 `init`；CLI 不能拦截宿主打开目录事件。

## 按需调度与实际执行

简单任务由主 Agent 直接完成。规划简单任务时也不会加载完整团队、角色正文或项目记忆：

```sh
agent-team --project /project plan examples/simple-task.yaml
```

复杂任务由主 Agent 根据实际代码边界写 spec，格式见 [examples/task.yaml](../examples/task.yaml)。输入是结构化语义分析，CLI 不通过需求关键词冒充任务理解。评分为 `0.30*independence + 0.25*complexity + 0.25*specialization + 0.20*parallel_benefit`。

| 默认评分 | 模式 | 最大并发子 Agent |
| --- | --- | --- |
| <40 | single_agent | 0 |
| 40–69 | assisted | 1 |
| ≥70 | multi_agent | 3 |

分数之外还要求独立交付物、明确写入边界和预期收益。依赖关系按批次执行，同一文件/父子目录的写入冲突必须串行或拒绝。自定义策略不能突破硬上限3；低于40的快速路径固定为单 Agent，以免为了决策加载项目团队。

```sh
agent-team --project /project --platform codex plan /tmp/spec.yaml
agent-team --project /project task list
agent-team --project /project task show TASK_ID
```

无能力证明时生成顺序角色工作流。当前宿主确实提供 Subagent 工具时，由主 Agent 写本次会话 `host.yaml`：

```yaml
native_subagents: true
evidence: 当前会话工具列表包含实际委派工具，已核对可用角色
available_agents: [真实角色ID]
max_parallel_agents: 3
```

通过 `--host /tmp/host.yaml plan /tmp/spec.yaml` 生成可供宿主执行的 handoffs 和 batches。只有当前明确可用的角色才可安排原生委派。role.id、role.role 或实际 agent_id 的映射以团队配置为准。

主 Agent 使用真实 spawn/delegate 工具执行交接，等待实际结果、处理失败并验收。CLI 记录状态，未内嵌宿主私有 RPC，也不启动伪 Agent 进程。`running` 是用户/宿主报告的状态，不能证明有后台进程。

```sh
agent-team --project /project task update TASK_ID running
agent-team --project /project task update TASK_ID completed \
  --summary '实际完成内容及验证结果' --evidence /tmp/evidence.yaml
```

evidence 必须是非空映射，记录实际测试、产物、结果和未验证项；示例见 `examples/evidence.yaml`，示例本身不是执行证明。可加 `--metrics /tmp/metrics.yaml` 保存宿主真实统计。未知 Token、时长和质量保持 `null`，不估算缓存命中或成本节约。计划与角色 Prompt 的边界是协作约定，真实权限隔离由宿主沙箱提供。

## 角色市场

```sh
agent-team --project /project --platform codex role catalog
agent-team --project /project --platform codex role catalog --source /path/to/agency-agents
agent-team --project /project role recommend --capability api-development --deliverable 接口实现
agent-team role generate order-expert --name '订单领域专家' \
  --capability orders --deliverable '订单实现' > /tmp/order-expert.json
agent-team --project /project --platform codex role install /tmp/order-expert.json
agent-team --project /project --platform codex role install /tmp/order-expert.json --approve
```

先扫描当前宿主证据和本地角色，再参考可选来源目录及内置角色草案。`role generate` 生成可编辑的确定性初稿，主 Agent 可根据业务完善 prompt 后预览安装。Agency-Agents 通过用户已有 checkout 接入，不是运行依赖，不执行其脚本，也不自动下载仓库。支持角色 Markdown/frontmatter 和 Codex TOML。自定义可信社区库也可通过 `--source` 传入本地目录。

推荐以能力、交付物、平台和可信度加权，最多 Top 3。角色状态明确区分：

| 状态 | 含义 |
| --- | --- |
| available | 当前宿主明确报告可调用 |
| installable | 有可读取来源，尚待安装 |
| proposed | 本地生成或内置建议草案 |
| unavailable | 定义已存在，当前宿主未验证可调用 |

平台兼容但尚未验证的角色仍可作为顺序 Prompt 候选，推荐结果会说明需先验证。能力缺口会记录在任务计划的 `capability_gaps` 中，并保留给主 Agent，不会凭空创建可执行 Agent。

默认 `role install` 预览来源、路径、权限和文件内容。授权后 `--approve` 写入项目目录及团队索引；重复安装保持幂等，拒绝覆盖不同的现有内容。Codex 渲染独立 `.codex/agents/*.toml`；其他平台输出对应配置/Prompt。安装完成不代表当前会话已重载，更不代表 Agent 已运行。

平台和版本变化时，以当前宿主实际工具及其官方文档为准。Codex 格式依据[官方 Subagents 文档](https://developers.openai.com/codex/subagents/)，需有 `name`、`description`、`developer_instructions`。Cursor/Gemini 的原生子 Agent 支持仍由宿主提供证据；没有证据时使用顺序交接。

## 记忆与统计

```sh
agent-team --project /project memory add experience \
  '旧接口字段需保持兼容' --source 'task-123:兼容性测试'
agent-team --project /project memory add decisions \
  '订单通过应用服务写入' --source 'ADR-003' --approve
agent-team --project /project memory show --category experience
agent-team --project /project memory update experience ENTRY_ID \
  '经过新验收确认的最新约束' --source 'task-124:回归测试'
agent-team --project /project analytics
agent-team --project /project doctor
```

记忆分 `project-context` / `architecture` / `decisions` / `experience`，只保存长期信息及其来源，避免重复；更新过期信息时保留修订历史，任务日志单独保存在 tasks。重要架构和决策写入需要确认。统计保留已知数据与覆盖率，存在缺测值时不冒充完整总量。`doctor` 为按需诊断，会读取完整索引和角色，不应在简单任务的每次会话执行。

## 验证

```sh
python3 -m pip install '.[test]'
python3 -m pytest tests -q
```

测试以临时项目验证初始化/恢复、团队损坏、三模式、降级、冲突、角色安装、状态迁移与 CLI 流程。不会调用付费模型或修改个人配置。宿主的真实 Agent 调用、平台自动入口加载和计量数据需要在各自宿主环境中验证，单元测试不能代替这些集成检查。

本次实际验证结果与原生宿主验收见 [VALIDATION.md](../VALIDATION.md)。
