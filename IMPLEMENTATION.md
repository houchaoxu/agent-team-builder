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
catalog 来源当前宿主、项目成员、本地源目录及内置 proposed 角色。自然语言推荐默认先评估现有已安装角色，排除内置草案；不足时显式使用 Agency 后备索引。状态 available/installable/proposed/unavailable 与证据分离。安装预览先给来源/目标/权限/内容，已有授权或用户确认后 approved 才写入，绝不修改全局配置，幂等避免覆盖已有内容。install 后只有 host 可验证才 available。

### 2.5.0 后备素材库与推荐边界

- [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents) 是 MIT 许可的后备素材来源。内置轻量索引保留真实固定 revision、角色路径、内容 hash 与版权署名；维护者从已有 checkout 通过 `scripts/build_agency_index.py` 生成增量索引，用户无需 clone 或运行维护脚本。
- `role recommend --query TEXT` 使用本地关键词及中英文场景别名召回，不提供 embedding 或外部模型 API。`--library agency` 切换后备索引；可重复 `--term` 补义，`--limit` 默认 6、范围 1..20，`--offset` 默认 0。能力卡不包含完整 prompt，由宿主 LLM 判断语义。最多两次扩大检索后仍无合适候选时如实说明，不能把零召回当作语义上不存在。
- `--assessment` 绑定完整目录版本/状态指纹及原查询参数，保留候选、评分、引用等校验；不把宿主判断冒充程序证明。仅 `--capability` 的旧精确标签算法与本地 `--source` 接入保持兼容。
- `role show ID` 按需读取完整 profile；`--library agency` 仅下载所选固定 revision 角色，hash 校验后缓存。`role install --agency ID` 复用缓存；show/install 的 `--offline` 禁止联网，缺少有效缓存时失败。安装默认预览，只有 `--approve` 才写入；用户已授权自动补位安装时可在范围内连续完成。
- 角色安装、宿主发现配置、当前会话原生可调用性、实际执行是不同状态。不能承诺安装后立即产生可调用原生 Agent。当前任务不以未经测量的准确率或 Token 节省比例作为验收证据。

## 验收

覆盖首次初始化/恢复、多项目隔离、损坏拒绝覆盖、简单路径按需加载、三模式调度、平台降级、依赖与写入冲突、角色发现/Top3/预览安装/重复安装、带来源记忆去重、任务状态和真实指标、CLI 完整流程。不得修改用户全局配置或发布。
