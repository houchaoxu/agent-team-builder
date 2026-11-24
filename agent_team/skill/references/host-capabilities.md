# 宿主能力协商与验收

安装、修复宿主适配或准备实际委派时按需读取。普通简单任务不执行探测，不读取全部适配器，也不为每个新会话重新安装团队。下面的输入和命令由当前 Agent 准备、执行，用户只需描述目标。

## 获取本次会话证据

先查看当前会话的真实工具、可调用角色及权限，再填入 `--host` 文件。产品官方文档用于确认格式、版本与安装入口；当前工具和调用结果用于判断本次能否执行。平台名称、角色文件、历史成功记录都不能替代当前能力证据。

证据文件可以记录 `schema_version: 1`、`platform`、`session_id`、`host_version`、`evidence`，并按已核实的情况提供：

| 字段 | 核实内容 |
| --- | --- |
| `native_subagents`、`available_agents` | 当前会话是否有委派工具，哪些真实 Agent ID 可调用 |
| `generic_agent_id`、`accepts_role_instructions` | 能否把专业角色指令传给一个实际可用的通用子 Agent |
| `dynamic_agents` | 是否支持按任务定义临时专业角色（布尔值） |
| `delegation_tool`、`result_tool`、`result_mode` | 实际委派工具与结果工具；同步直接返回可明确填写 `result_mode: inline` |
| `role_registration`、`registration_tool` | 当前是否提供已核实的原生角色创建/注册工具 |
| `max_parallel_agents` | 当前宿主允许的并发数量，不以产品名推测 |
| `shared_workspace`、`parallel_writes`、`worktree` | 共享工作区、并行写入及隔离工作区能力 |

未核实的能力留空或保持未知，不把“没有证据”写成“该产品不支持”。已知不支持时明确写 `false`。当前使用的平台优先于团队首次创建时的平台；同一项目保留其他工具的目录并不代表当前正运行那个工具。显式 `--platform` 或有证据的本次 `--host.platform` 可以消除自动识别歧义，但两者不能互相冲突。同层多个活动环境标识冲突时拒绝猜测，先核对当前会话，不自动选择旧目录对应的宿主。

新证据使用 schema 1，并要求真实 `platform`、`session_id` 和 `evidence`。例如，当前实际存在通用子 Agent 时，可由宿主生成以下 JSON；尖括号内容必须换成本次观察值，未发生的观察不得照填：

```json
{
  "schema_version": 1,
  "platform": "workbuddy",
  "session_id": "<当前会话标识>",
  "evidence": "<当前工具和角色清单的实际观察>",
  "native_subagents": true,
  "available_agents": ["<真实通用Agent ID>"],
  "generic_agent_id": "<真实通用Agent ID>",
  "accepts_role_instructions": true,
  "delegation_tool": "<真实委派工具>",
  "result_tool": "<真实结果工具>"
}
```

通用执行者必须同时出现在 `available_agents` 中。临时角色执行要求 `native_subagents`、`accepts_role_instructions`、`dynamic_agents` 均为 `true`，且提供真实 `delegation_tool`；不从一个产品自称支持多 Agent 就推导这些条件已满足。新协议所有委派路径均需真实 `delegation_tool`，并提供 `result_tool`；若委派工具同步返回完整结果，可用已核实的 `result_mode: inline` 代替结果工具。旧版无 schema 的证据格式仍兼容，但新的安装与验收应使用 schema 1。

```text
agent-team --project <project> --platform <actual-platform> --host <current-host.json> host inspect
```

`host inspect` 返回适配器契约、当前能力与可用运输方式；没有具体角色输入时，它只能展示通用、临时或顺序交接选择，不会凭空确定某个原生专家已经可用。具体角色的路由由 `plan` 的各项 `handoffs[].transport` 返回。inspect 不会自行枚举宿主私有工具或创建子 Agent；Python 引擎负责校验与规划，实际宿主工具由当前 Agent 调用。未验证的宿主版本不能报告为已兼容。

## 选择实际执行方式

优先复用当前会话明确可调用的专业 Agent。没有对应原生角色时，按已证明的能力选择通用子 Agent 加载专业指令，或创建临时专业角色；两种方式还必须实际加载非空角色正文，不能只传角色名字冒充专业指令。都不可用时才由主 Agent 顺序执行交接。不能因为某个平台的文件安装器生成的是 Skill，就判定该平台没有子 Agent。

计划中的 `member_id` 表示所用专业角色，`agent_id` 表示实际调用的宿主执行者，`execution_mode` 标明执行方式。保留两种身份；给通用子 Agent 传入 AI Engineer 指令，并不意味着已把 AI Engineer 注册为原生 Agent。使用 handoff 中的任务范围、完整角色指令与真实工具标识，记录实际返回的调用 ID，不把计划字段当作已执行证据。

执行方式为 `native_role`、`generic_subagent`、`dynamic_subagent` 或 `sequential_handoff`。临时角色在创建前可以没有 `agent_id`；其实际调用 ID 必须从宿主返回值取得，不自行生成。

新项目默认并发为 2，可配置正整数；已有显式配置保留。有效并发取项目策略与当前宿主限制中较小者，assisted 最多 1；宿主限制未知时保守使用 1。写入任务只有在本次明确验证 `parallel_writes: true` 后才可并行，否则串行。原有依赖、独立交付物与文件边界仍须满足，不因增加并发配置放宽。

若 `shared_workspace: false`，当前规划器保留顺序交接并报告项目传递缺口；须先建立、验证隔离工作区的项目输入与产物回收契约。`worktree: true` 只表示能力存在，不证明已经准备好工作区，不能直接安排文件任务。

注册永久角色、启用插件和扩大用户范围都需遵守相应安装与权限契约。原生注册只有在真实工具可用且格式/接口已核实后才能执行，不猜测 API、目录或命令。Agency-Agents 仍是唯一默认后备角色来源；宿主能力协商不引入其他素材库，也不替代所选角色的预览与手动安装确认。

## 分别验收并保留记录

将安装文件、宿主发现、原生注册、实际调用、结果返回分别验收；尚未执行或无法观察的阶段保持未知。文件存在不等于宿主已发现，宿主发现不等于原生注册，注册成功也不等于本次任务执行成功。

回执要求 `schema_version: 1`、`platform`、`session_id`，后两者必须与当前 `--host` 证据一致。`checks` 只填写实际检查过的阶段：`files_installed`、`skill_discovered`、`role_registered`、`agent_invoked`、`result_received`。每项使用 `status: passed | failed | pending`；passed/failed 附实际 `evidence`，调用和结果 passed 还须包含真实返回的 `agent_id`。结果与调用必须在同一回执中成功且 ID 一致，不能用另一次会话的成功结果补齐当前验收。

安装或适配验收时，在授权范围内做一次最小只读调用：传入所选专业指令和一个可核对的简短任务，使用真实结果工具取回返回值。保存调用 ID、返回结果与实际观察证据。若还需刷新会话或 UI 操作，报告停在哪个阶段，不为了完整成功状态而伪造回执。

```text
agent-team --project <project> --platform <actual-platform> --host <current-host.json> host verify <receipt.json>
```

`host verify` 校验回执并保存到 `.agent-team/hosts/<platform>.json`；它不是执行工具，也不会替你完成注册或试调用。`host inspect` 的 `verification` 表示当前仍待验收的阶段，历史回执独立显示为 `last_verification`，不会升级当前能力。持久记录用于排障和说明已经验证过什么，不作为下次会话的能力授权。后续复杂任务只复核将要使用的工具、角色和限制；普通简单任务无需运行 inspect、verify 或安装诊断。

`host matrix` 汇总各宿主最近一次保存的五阶段回执。它只反映历史验收记录；没有记录显示 `unknown`，不代表不支持，也不会推断当前会话能力。保存回执时应记录宿主版本和实际证据，以便版本间比较。

当前适配器的格式支持和测试结果只覆盖其声明范围。单元测试能够验证路由、转换和校验边界；宿主真实加载、注册、调用与结果返回需在相应版本中取得实际证据，不能从 Mock 测试推断所有平台均已原生适配。
