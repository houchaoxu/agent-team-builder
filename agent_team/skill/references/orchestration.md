# 编排接口

以下命令仅面向 Agent。用户通过对话描述需求，由 Agent 生成输入并执行。优先使用随 Skill 的 `<python> <skill>/scripts/run.py` 替代下文的 `agent-team`；不存在全局 CLI 时也可正常工作。环境准备见 installation.md。

首次启用用 `agent-team --project /project --platform codex init` 注册轻量入口。已有团队的新会话直接复用 `.agent-team/team.yaml`，无需再执行 `init`；只有明确的升级或修复才按需刷新入口。

宿主加载项目入口后，每个新任务先用需求和当前上下文判断协作收益，不要求用户说出工具名称。简单任务直接完成，不加载本 Skill、团队或角色，不运行 `plan`、`status`、`doctor` 或扫描角色。明确的安装、诊断或角色管理请求仍按其工作流处理。

对复杂任务，主 Agent 分析实际工作并保存 YAML：

```yaml
title: 新增订单模块
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

分数由主 Agent 按实际交付物和代码边界判断；CLI 不用关键词猜测需求。默认加权分 `<40` single_agent、`40..69` assisted、`>=70` multi_agent。没有独立边界或交付物的工作不委派。assisted 最多1、multi 最多3个并发子 Agent，主 Agent 不计入。需要先设计接口时把该阶段作为依赖，不能把有契约依赖的工作称为独立。

宿主能力证明只限本次会话，示例：

```yaml
native_subagents: true
evidence: 当前工具明确暴露 collaboration.spawn_agent，已核对角色列表
available_agents: [backend-developer, frontend-developer]
max_parallel_agents: 3
```

将真实角色 ID 替换到证明和 spec 中；示例名字不代表已安装。没有这些工具则省略 `--host`，计划将降级为顺序交接。不得制造证据来让 CLI 输出 native。

```sh
agent-team --project /project --host /tmp/current-host.yaml plan /tmp/spec.yaml
agent-team --project /project task update TASK_ID running
```

读取返回的 execution；仅加载选择角色。现有成员能覆盖任务时不扫描 Marketplace，有实际能力缺口时才按 role-matching.md 检索补齐；规划不会重建团队或自动安装角色。按 batches 调度并等待每批真实结果，不跨依赖提前写文件。宿主实际调用失败时报告、调整或顺序降级，不能把 capability 声明当成启动成功。CLI 中的 running 只是状态记录，不是进程证明。

完成后保存验收映射并执行：

```sh
agent-team --project /project task update TASK_ID completed \
  --summary '订单接口与页面完成，相关测试通过' --evidence /tmp/acceptance.yaml
```

evidence 使用映射保存实际命令、结果、产物和限制，不把未执行的验证记为通过。metrics 可另行提供；统计字段和状态契约见项目 README。主 Agent 检查交付物后才记录完成。
