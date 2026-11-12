# Agent Team Runtime 实现约定

需求来源：https://chatgpt.com/s/t_6af52790b7c481919c628336c14738b5

交付 Python >=3.9 CLI + 可安装 Skill；YAML/Markdown 持久化，不依赖外部服务。
宿主负责自然语言理解、实际启动 Agent 和最终验收；CLI 负责确定性状态、调度校验、交接生成与记录。没有宿主能力证据时必须降级，不假装执行。

## 文件归属与接口

- runtime 实现者：`agent_team/storage.py`, `agent_team/runtime.py`, `tests/test_runtime.py`。
- marketplace 实现者：`agent_team/adapters.py`, `agent_team/marketplace.py`, `tests/test_marketplace.py`。
- 主 Agent：CLI、打包、Skill、文档、端到端测试。
- Reviewer：只读审查，主 Agent 修复后复核。

所有公开 API 接受 `pathlib.Path` 根路径，返回可 JSON 序列化的 dict/list，业务错误抛 `ValueError`，IO 错误由 CLI 统一报告。

### storage

`discover_root(start) -> Path`：向上找最近 .agent-team/team.yaml，或 Git/项目标识；
`read_yaml(path) -> dict`（safe_load，映射必需，损坏明确报错）；
`write_yaml(path, data)`（原子替换）；`safe_path(root, relative) -> Path`（禁止绝对、越界和符号链接逃逸）；
`project_lock(root)` 上下文管理器（并发写入排他，锁在 .agent-team）；
`validate_team(data) -> dict`（验证后原样返回）；
`bootstrap(root, platform='generic') -> dict`（幂等恢复；首次识别栈，最小团队，保留已有入口文本，损坏不覆盖）。

### runtime

`plan_task(root, spec, host=None) -> dict`；`get_task(root, task_id) -> dict`；`list_tasks(root) -> list`；
`update_task(root, task_id, status, summary='', metrics=None, evidence=None) -> dict`；
`add_memory(root, category, text, source, approved=False) -> dict`；`read_memory(root, category=None) -> dict`；`analytics(root) -> dict`。

spec: `{title, goal?, scores:{independence,complexity,specialization,parallel_benefit}, work_items:[{id,role,goal,deliverables:[str],write_scope:[str],depends_on:[id]}], acceptance_criteria:[str]}`。
评分 0.30/0.25/0.25/0.20，<40 single_agent / <70 assisted / 否则 multi_agent；并发子 Agent 上限3，单独主 Agent不计数。角色名对应 member.id 或 member.role。无独立边界、交付物不启动。重叠写入以依赖串行化或明确拒绝。任务状态 planned/running/completed/failed/cancelled；completed 需要 summary 与真实验收 evidence。指标未知 null，不估算 Token。

简单 single_agent 路径不读取 team.yaml、成员或记忆（已有初始化）；其他路径按需加载。
host 格式与 adapter 相同；host.native_subagents 只有显式布尔 true 加 evidence 字符串才成立。
任务保存 `.agent-team/tasks/<id>.yaml`，id UUID；含 `task`, `execution`（mode, strategy, agents, work_items, batches, handoffs, warnings）, `metrics`, `result`。返回完整记录。handoffs 为清晰 prompt，勿复制完整对话。

### adapters

`detect_platform(root, env=None) -> str`；`capabilities(platform, host=None) -> dict`；
`entry_path(platform) -> str`；`entry_text(platform) -> str`；
`render_role(role, platform) -> {path: relative str, content: str}`。
平台 codex/claude-code/cursor/gemini-cli/generic；本地 role 文件或 CLI 存在不等于可调用。host `{native_subagents:bool,evidence:str,available_agents:[str],max_parallel_agents:int?,...}`。

### marketplace

`build_catalog(root, platform='generic', sources=None, host=None) -> list`；
`recommend_roles(catalog, capabilities, deliverables=None, limit=3) -> list`；
`generate_role(role_id, name, capabilities, deliverables=None) -> dict`；
`install_role(root, role, platform='generic', approved=False, host=None) -> dict`。
role `{id,name,capabilities:[str],deliverables:[str],prompt,source,platforms:[str],...}`。
catalog 来源当前宿主、项目成员、本地源目录（可选 Agency-Agents checkout，不自动联网拉取）及内置 proposed 角色。状态 available/installable/proposed/unavailable 与证据分离。安装预览先给来源/目标/权限/内容，approved 才写入，绝不修改全局配置，幂等避免覆盖已有内容。install 后只有 host 可验证才 available。

## 验收

覆盖首次初始化/恢复、多项目隔离、损坏拒绝覆盖、简单路径按需加载、三模式调度、平台降级、依赖与写入冲突、角色发现/Top3/预览安装/重复安装、带来源记忆去重、任务状态和真实指标、CLI 完整流程。不得修改用户全局配置或发布。
