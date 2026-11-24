# 编排接口

以下命令仅面向 Agent。用户通过对话描述需求，由 Agent 生成输入并执行。优先使用随 Skill 的 `<python> <skill>/scripts/run.py` 替代下文的 `agent-team`；不存在全局 CLI 时也可正常工作。环境准备见 installation.md。

协作模式默认为 `smart`；用户可说“只用当前 Agent / 省 Token”指定 `solo`，或明确要求“团队协作”指定 `team`。spec 可提供 `collaboration_mode: solo|smart|team`，也可用 `plan --mode` 设置本次模式。`solo` 跳过团队及角色读取；`smart` 只在协作分数达到门槛时升级；`team` 明确启用协作规划，但文件边界、依赖和宿主实际能力仍然优先。

真正委派前，按计划 `execution.cost_estimate` 展示子 Agent 数量、粗略影响级别、传递的任务范围与角色指令，以及是否需要确认。顺序 handoff 不计作额外子 Agent。宿主没有可靠预执行 Token 数据时必须显示“未知”，不按人数编造 Token 或费用。用户已明确授权当前任务使用团队时，不机械重复确认。

`additional_agents` 表示预计子 Agent 调用次数；同一角色用于多个工作项也可能多次调用。`impact` 仅按调用数分档（0 为 none、1 为 low、更多为 moderate），不是价格或 Token 预测。先展示为什么值得协作、预览的调用数和范围；未获授权时提供“按计划协作 / 单 Agent 完成”选择。已有当前任务授权则直接记录。随后用 `task update TASK_ID running --approve-delegation` 保存授权；未记录授权的新委派计划不能进入 running/completed，旧任务记录继续兼容。引擎不控制宿主工具，实际调用仍由当前 Agent 在授权后执行。

交接仅提供目标、必要背景、依赖、文件归属、验收和选中角色正文；宿主支持时使用空白上下文子 Agent，不复制完整聊天。无法控制上下文继承时说明限制，不承诺上下文已被压缩。

首次启用用 `agent-team --project /project --platform codex init` 注册轻量入口。已有团队的新会话直接复用 `.agent-team/team.yaml`，无需再执行 `init`；只有明确的升级或修复才按需刷新入口。

宿主加载项目入口后，每个新任务先用需求和当前上下文判断协作收益，不要求用户说出工具名称。简单任务直接完成，不加载本 Skill、团队或角色，不运行 `plan`、`status`、`doctor` 或扫描角色。明确的安装、诊断或角色管理请求仍按其工作流处理。

对复杂任务，主 Agent 分析实际工作并保存 YAML：

```yaml
title: 新增订单模块
collaboration_mode: smart
goal: 实现订单创建及独立前端页面
scores:
  independence: 90
  complexity: 80
  specialization: 80
  parallel_benefit: 85
acceptance_criteria:
  - 订单接口与页面通过现有测试
work_items:
  - id: backend
    role: backend-developer
    goal: 实现订单接口
    deliverables: [订单接口及测试结果]
    write_scope: [server/]
    depends_on: []
  - id: frontend
    role: frontend-developer
    goal: 按已约定接口实现订单页面
    deliverables: [订单页面及构建结果]
    write_scope: [web/]
    depends_on: []
```

分数由主 Agent 按实际交付物和代码边界判断；CLI 不用关键词猜测需求。默认加权分 `<40` single_agent、`40..69` assisted、`>=70` multi_agent。没有独立边界或交付物的工作不委派。assisted 最多 1，multi 的新项目默认并发为 2，可配置正整数；已有显式上限保留。有效数量同时受当前宿主上限限制，未知时保守使用 1，主 Agent 不计入。写入任务仅在本次验证 `parallel_writes: true` 时可并行。需要先设计接口时把该阶段作为依赖，不能把有契约依赖的工作称为独立。

宿主能力证明只限本次会话，按 [宿主能力协商](host-capabilities.md) 核实真实工具和角色。以下为原生角色已可用时的示例：

```yaml
schema_version: 1
platform: codex
session_id: 当前会话实际标识
native_subagents: true
evidence: 当前工具明确暴露 collaboration.spawn_agent，已核对角色列表
available_agents: [backend-developer, frontend-developer]
delegation_tool: collaboration.spawn_agent
result_tool: collaboration.wait_agent
max_parallel_agents: 3
```

将真实会话及角色 ID 替换到证明和 spec 中；示例名字不代表已安装。如果对应专业 Agent 不可用，但当前宿主提供通用子 Agent 且允许传入角色指令，填写真实 `generic_agent_id` 与 `accepts_role_instructions`；支持临时角色时提供相应能力。引擎按原生角色、通用子 Agent、临时角色、顺序交接选择执行路径。没有委派证据时使用顺序交接，不制造证据来让 CLI 输出 native。实际运行平台优先于团队创建平台，不为跨宿主复用重建团队。

```sh
agent-team --project /project --host /tmp/current-host.yaml plan /tmp/spec.yaml
agent-team --project /project task update TASK_ID running --approve-delegation
```

读取返回的 execution；仅加载选择角色。`execution.agents` 区分专业角色 `member_id`、实际执行者 `agent_id` 与 `execution_mode`；handoffs 提供角色指令和真实调用工具标识。现有成员能覆盖任务时不扫描 Marketplace，有实际能力缺口时才按 role-matching.md 检索补齐；规划不会重建团队或自动安装角色。按 batches 调度并等待每批真实结果，不跨依赖提前写文件。宿主实际调用失败时报告、调整或顺序降级，不能把 capability 声明当成启动成功。CLI 中的 running 只是状态记录，不是进程证明。

用户明确要求找更合适的专家时，不能用通用成员“也能执行”代替专业能力判断。匹配通过后先展示角色选项，选中后准备安装预览并等待本次手动确认；等待期间不派其他成员先做同一工作。安装后重新规划；原生角色尚未被宿主发现时保留顺序 handoff，不把配置存在当作可调用证明。宿主实际支持以角色指令交给通用子 Agent 时可使用该方式，但须记录真实执行者与所用专业角色的区别。

完成后保存验收映射并执行：

```sh
agent-team --project /project task update TASK_ID completed \
  --summary '订单接口与页面完成，相关测试通过' --evidence /tmp/acceptance.yaml
```

evidence 使用映射保存实际命令、结果、产物和限制，不把未执行的验证记为通过。主 Agent 检查交付物后才记录完成，计量字段按下文记录。

有真实计量时用 `task update --metrics` 记录 `tokens`、`cost`、`duration_seconds` 和非负整数 `subagent_calls`、`tool_calls`、`rework_rounds`。无法计量时保持 null。只有明确观察到本任务未调用子 Agent 才填写 `subagent_calls: 0`；计划中的人数不能代替实际调用次数。`analytics.mode_comparison` 按已测调用次数分组，未测任务单列，不把不同难度任务之间的差异当作节约率。
