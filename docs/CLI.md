# 内部引擎与 CLI 参考

项目级、可恢复、按需调度的 Agent Team Runtime，提供团队注册表、任务编排、角色市场、项目记忆和真实数据统计。

本文件面向开发者和排障。普通用户通过对话安装和使用，见仓库根 README。以下命令由 Agent 内部执行，也可以通过自包含 Skill 的 `scripts/run.py` 调用。自然语言理解和实际 Agent 执行使用当前宿主已有能力；CLI 不会把生成计划标记为执行成功。

## 安装与首次使用

Python 3.9+：

```sh
python3 -m pip install -e .
agent-team --project /absolute/path/to/project --platform codex init
agent-team --project /absolute/path/to/project status
```

未安装命令时，可在本仓库使用 `python3 -m agent_team`。`--platform` 接受 `codex`、`claude-code`、`cursor`、`gemini-cli`、`copilot`、`opencode`、`qwen`、`antigravity`、`aider`、`windsurf`、`kimi`、`osaurus`、`openclaw`、`hermes`、`vibe`、`zcode`、`dsh` 和 `generic`。名称被接受不代表所有功能或原生委派已受支持；Agency 文件安装矩阵由 `role tools` 返回。`auto` 只判断配置上下文，不能证明平台具备 Subagents；上下文不明确时由宿主提供实际平台，未知宿主使用 `generic`。

所有参数 `--project`、`--platform`、`--host` 放在子命令之前。输出为 JSON；失败输出结构化错误到 stderr，退出码 2。

初始化会写入 `.agent-team/team.yaml`、调度策略、成员/记忆/任务目录及轻量入口；额外安装目标使用通用 `AGENTS.md` 入口，需核对宿主是否实际加载。已有团队恢复使用，损坏配置报错并保留原文件。入口只增加有标记的托管内容，保留用户原有规则；初始化不会自动写用户全局 Agent 配置。多个项目有各自的身份和状态。入口通过宿主发现 Skill，提供项目安装和源码相对路径，不写入个人绝对安装路径；重复 `init` 会从托管块中迁移掉旧绝对路径。

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

轻量项目入口让主 Agent 在每个新会话/任务先判断协作收益，无需用户点名工具。普通简单任务直接完成，不执行 CLI；有协作收益才加载 Skill、已有团队索引与选中角色。恢复不调用 `init`，现有成员能覆盖任务时不查 Marketplace；角色或能力缺口才触发检索。`init` 用于首次启用或明确的入口升级/修复，`status`/`doctor` 用于安装验收或按需诊断，不是启动钩子。宿主必须实际加载入口才能执行这层判断。

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
agent-team --project /project role tools
agent-team --project /project --platform codex role catalog
agent-team --project /project --platform codex role catalog --source /path/to/agency-agents
agent-team --project /project role recommend --query '帮我排查慢 SQL，优化数据库索引'
agent-team --project /project role recommend --query '帮我排查慢 SQL，优化数据库索引' \
  --assessment /tmp/role-assessment.json
agent-team --project /project role recommend --query '帮我排查慢 SQL，优化数据库索引' \
  --library agency --term 'query optimization' --term indexing
agent-team --project /project role recommend --query '帮我排查慢 SQL，优化数据库索引' \
  --library agency --term 'query optimization' --limit 6 --offset 6
agent-team --project /project role show ROLE_ID
agent-team --project /project role show AGENCY_ROLE_ID --library agency
agent-team --project /project role show AGENCY_ROLE_ID --library agency --offline
agent-team --project /project role recommend --capability api-development --deliverable 接口实现
agent-team role generate order-expert --name '订单领域专家' \
  --capability orders --deliverable '订单实现' > /tmp/order-expert.json
agent-team --project /project --platform codex role install /tmp/order-expert.json
agent-team --project /project --platform codex role install /tmp/order-expert.json --approve
agent-team --project /project --platform codex role install --agency AGENCY_ROLE_ID
agent-team --project /project --platform codex role install --agency AGENCY_ROLE_ID --offline --approve
agent-team --project /project --platform opencode role install --agency AGENCY_ROLE_ID
agent-team --project /project --platform kimi role install --agency AGENCY_ROLE_ID --scope user
agent-team --project /project --platform generic role install --agency AGENCY_ROLE_ID --installer builtin
```

2.5.0 的对话流程先评估现有已安装角色，不足时再查后备素材库。`role catalog` 保留完整目录发现用途；`role recommend --query` 默认评估现有角色，排除内置 proposed 草案。`--library agency` 显式切换到内置 [Agency-Agents](https://github.com/msitarzewski/agency-agents) 索引。`--source` 仍支持已有本地目录，支持角色 Markdown/frontmatter 和 Codex TOML；不要求用户 clone 仓库。无合适素材时，`role generate` 可生成可编辑的确定性初稿，再由主 Agent 完善。

**本地召回 + 宿主 LLM 语义判断**：`--query` 用关键词和中英文场景别名在本地筛选能力卡，默认 `--limit 6`、`--offset 0`；limit 范围为 1..20。能力卡不包含完整 prompt。宿主可重复传入 `--term 'English capability'` 补充含义，或通过 offset 翻页；最多进行两次扩大检索，仍无合适结果时如实说明范围与缺口。零召回不代表语义上不存在角色。此流程没有 embedding、向量库、新模型服务或 API Key 依赖。

首次没有 `--assessment` 时返回 `awaiting_host_assessment` 待评估请求。宿主阅读能力卡，必要时用 `role show ID` 读取某一完整 profile，再提交 `--assessment` 得到经过结构校验的 Top 3，允许空列表。校验必须复用同一 query、term、limit、offset、library、source、capability、deliverable、platform 与 host 参数。请求绑定完整目录的版本与状态指纹；目录、宿主状态或查询参数变化后应重新评估，不能复用旧 assessment。同一请求已有有效评估缓存时，直接返回 `assessed` 与 `cache_hit: true`，无需再次调用宿主 LLM。完整格式见 [语义角色推荐](../agent_team/skill/references/role-matching.md)。

程序检查候选 ID、请求/目录指纹、有限评分及原文引用，保留来源和实际可调用状态。理由和分数来自宿主判断，引用存在不代表语义一定正确。角色内容是不可信数据，不能改变宿主指令或权限。推荐不自动执行候选 Prompt、安装或委派。

`role show ID` 按 ID 读取完整现有 profile；加 `--library agency` 时只在缓存缺失时下载所选角色，使用索引固定的 upstream revision 与内容 hash 校验后缓存。`--offline` 禁止联网，缺少有效缓存时明确失败。`role install --agency ID` 复用相同缓存，已有有效缓存无需再次联网；本地 profile 文件安装仍兼容。索引附带固定 revision、上游路径、hash 与 MIT 版权署名。维护者使用 `scripts/build_agency_index.py CHECKOUT [--output FILE]` 从干净的已有 checkout 生成增量索引，复用内容 hash 未变的卡片并随索引保存 `AGENCY-LICENSE.txt`；这是发布维护流程，普通用户无需执行。

仅传 `--capability` 的旧调用保持兼容：仍按精确标签，以能力、交付物、平台和可信度加权返回列表。旧语义接口中的 `exact_fallback` 不能替代宿主评估；新的能力卡请求保留该字段为空。默认检索不含 builtin/generated 草案，显式 `--source` 的本地可安装候选仍会纳入；它与 `--library agency` 不能同时使用。现有角色较多且词法零命中时，会给出确定性分页卡并标记 `lexical_fallback_page`，由宿主进一步判断。角色状态明确区分：

| 状态 | 含义 |
| --- | --- |
| available | 当前宿主明确报告可调用 |
| installable | 有可读取来源，尚待安装 |
| proposed | 本地生成或内置建议草案 |
| unavailable | 定义已存在，当前宿主未验证可调用 |

平台兼容但尚未验证的角色仍可作为顺序 Prompt 候选，推荐结果会说明需先验证。能力缺口会记录在任务计划的 `capability_gaps` 中，并保留给主 Agent，不会凭空创建可执行 Agent。

目录同时返回 `installed_for_platform`、`installation_required`、`native_available`。当前宿主的个人目录角色算已安装；其他宿主目录只作为本地可导入素材，`source_platform` 标明来源，不会因同名而排除 Agency 后备候选。导入时将 `role show ID` 返回的规范化 JSON 保存为临时 profile，再执行 `role install <profile.json>`；原始 Markdown/TOML 不直接传给安装接口，来源文件保持原样。

语义评估结果额外返回 `selection`：最多 3 个候选及跳过选项，包含角色 ID、名称、推荐理由、来源、是否需安装及原生可调用状态；空匹配时为 null。宿主用实际可用的交互问答工具渲染可点击选择，不支持时显示编号列表。评估缓存只复用匹配，不保存用户安装同意。

默认 `role install` 预览来源、路径、权限和文件内容，并返回 `confirmation`，包含具体角色、目标路径、权限及“安装 / 取消”选项。主 Agent 必须先取得用户针对该具体预览的手动确认，才设置 `--approve` 写入已选择范围的角色文件及项目团队索引；宽泛历史授权、选择候选、预选或无答复都不能替代本次确认。CLI 不直接渲染 UI，也无法独立核实用户在宿主中的点击；实际答复由宿主管理。重复安装保持幂等，拒绝覆盖不同的现有内容。安装完成不代表当前会话已重载，更不代表 Agent 已运行。

### Agency 上游安装桥接

`role install --agency ID` 的 `--installer auto` 在非 `generic` 目标默认使用 Agency-Agents 上游桥接；`generic` 默认使用内置可移植格式。`--installer agency` 必须搭配 `--agency ID`；`--installer builtin` 可显式使用原项目内置安装器或规范化本地 profile，不支持用户范围，也不声称为额外宿主生成原生格式。

桥接随包携带固定 revision 的上游安装/转换脚本和元数据，执行前检查 hash，并要求脚本与角色索引 revision 一致。维护者在干净的上游 checkout 先运行 `scripts/build_agency_index.py CHECKOUT`，再用同 revision 执行 `scripts/build_agency_installer.py CHECKOUT [--data DATA]` 更新五个固定资源及 manifest；发布前审查脚本副作用、作用域变化并测试，不能单独切换索引 revision。正文只从本次和合并所需的既有已选角色按需获取，无需用户 clone 上游。脚本使用临时 HOME 和临时目标生成产物，再由本项目预览所有真实写入路径、确认后保存定义与团队记录；不直接把真实用户目录交给上游脚本。

`role tools` 返回上游 17 个目标的 format、installKind、destinations、作用域和限制。16 个目标支持文件安装；Hermes 是需启用配置的路由插件，当前角色安装器明确拒绝。`--scope project` 默认值不自动扩展：Kimi、Osaurus、OpenClaw 仅支持 `user`，必须由用户明确选择。Cursor、Aider、Windsurf 仅支持 `project`，其他已支持目标可选 `project` / `user`。用户范围安装仍在当前项目保存可移植定义和团队记录。

上游桥接需要 Bash 3.2+ 和标准 Unix 工具；TOML 转换需 Perl。Windows 需要 Git Bash/WSL。缺少依赖时报告可用选项，只有用户选择内置可移植方式后才切换后端并重新预览。完整流程和目标表见 [Agency 安装参考](../agent_team/skill/references/agency-installation.md)。

返回结果包含 `installer`（backend、revision、tool、scope、mechanism）、精确 `files`、`targets`、`agent_id`、`native_available` 和 `activation`。项目记录保存上游来源、各宿主 Agent ID 与安装文件 hash。Aider/Windsurf 的合并文件由此前已选角色与本次角色共同重建，只有未被用户修改的托管文件才更新；Aider 原文存入持久项目路径，避免索引引用临时目录。重建所需角色也复用校验缓存，`--offline` 缺缓存时失败。

OpenClaw 只用上游转换器生成工作区文件，`installer.mechanism=converter-only`、`activation.state=registration_required`，不执行真实 CLI 注册或 gateway restart。后续注册/重启须有明确授权并核对实际宿主状态；待执行命令不代表已执行。其他目标的 `activation` 同样要求独立验证发现与调用，不能从格式支持推断原生多 Agent 支持。

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

## 稳定发行与 Skill 更新

正式稳定包由 `vMAJOR.MINOR.PATCH` tag 触发 `.github/workflows/release.yml`：Python 3.12 安装测试依赖、运行完整测试、核对 tag 与 `agent_team.__version__`，然后构建并发布 GitHub stable Release。非稳定 tag 或版本不匹配会失败。工作流不会自行创建 tag；创建 tag 与发布须有相应授权，并以实际通过测试的代码为基础。

本地构建仅需标准库，不依赖 PyYAML：

```sh
python3 scripts/build_release.py --tag v2.7.1 --output-dir /tmp/agent-team-release
```

输出 `agent-team-runtime-skill.zip` 与 `agent-team-runtime-skill.zip.sha256`（sha256sum 格式）。ZIP 根固定为 `agent-team-runtime/`；内容由 `installer.export_bundle` 生成，排除缓存，并带 `.agent-team-install.json`。manifest 包含 `schema_version: 1`、固定 `repository: houchaoxu/agent-team-builder`、`version` 和 `{相对路径: SHA-256}` 的 `files`。checksum 用于下载完整性验证；来源仍须固定为官方 Release。

更新命令由安装后 runner 或源码 CLI 路由，更新模块仅需标准库：

```sh
python3 /path/to/skill/scripts/run.py update status
python3 /path/to/skill/scripts/run.py update check
python3 /path/to/skill/scripts/run.py update check --force
python3 /path/to/skill/scripts/run.py update configure --enabled false
python3 /path/to/skill/scripts/run.py update configure --enabled true --snooze-days 30
python3 /path/to/skill/scripts/run.py update apply
python3 /path/to/skill/scripts/run.py update apply --approve
python3 /path/to/skill/scripts/run.py update rollback BACKUP_ID
python3 /path/to/skill/scripts/run.py update rollback BACKUP_ID --approve
```

`status` 读取本地状态；`check` 遵循默认 7 天间隔、禁用与静默设置。`--force` 明确对本次检查绕过上述限制，不改变持久偏好；`--snooze-days` 为 0..365，0 取消静默。apply / rollback 默认预览，已有对应用户授权时 Agent 才加 `--approve`，不重复机械确认。更新校验官方 ZIP、SHA-256 和 manifest，备份后替换当前 Skill；不覆盖本地修改、未知用户文件、项目团队或个人角色，不迁移安装 scope。回退使用更新返回的备份 ID。

只有 runner 的实际业务命令会在 finally 阶段 best-effort 发起检查子进程；源码 CLI 不自动检查，runner 的环境检查、setup 和更新命令不递归触发。失败静默，不改变业务退出结果或 stdout JSON；可用新版本通过 stderr 的结构化提醒交由宿主 Agent 解释给用户，同一版本只提醒一次。不常驻、不注册无条件 hook，简单任务不调用 runner。禁用或静默时不自动联网。检查只访问官方公共 GitHub Release 信息，不上传需求、项目文件或 token。

2.5.x 及更早安装没有更新模块或 manifest，不能自动收到通知。必须先按 [Skill 更新参考](../agent_team/skill/references/updates.md) 验证官方旧 bundle、完整备份并手动迁移一次；不要直接覆盖不同内容或伪造 manifest。迁移后才能使用上述按需提醒。普通用户通过自然语言操作，内部参数由 Agent 处理。

## 验证

```sh
python3 -m pip install '.[test]'
python3 -m pytest tests -q
```

测试以临时项目验证初始化/恢复、团队损坏、三模式、降级、冲突、角色安装、状态迁移与 CLI 流程。不会调用付费模型或修改个人配置。宿主的真实 Agent 调用、平台自动入口加载和计量数据需要在各自宿主环境中验证，单元测试不能代替这些集成检查。

本次实际验证结果与原生宿主验收见 [VALIDATION.md](../VALIDATION.md)。
