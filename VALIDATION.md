# 验证记录

## 新会话轻量判断与团队复用

- 五种宿主入口明确先判断任务：普通简单任务不加载 Skill/团队，不因会话开始运行初始化、诊断或角色扫描；有协作收益才读取现有团队，有实际能力缺口才检索 Marketplace。显式安装、升级、修复和诊断请求保留独立流程。
- Python 3.9.6 完整回归 `python -m pytest tests -q`：169 项通过。新增验证覆盖五平台入口升级时团队与历史数据字节/修改时间不变、独立 runner 进程直接规划并复用团队、只加载选中角色、无能力缺口不扫描 Marketplace。简单计划的配置/记忆/目录扫描读取使用失败哨兵检查；普通简单任务按入口直接执行，无需调用 `plan`。
- 独立前向测试仅提供隔离项目和普通用户请求：按钮文字修改只读取轻入口与 HTML；订单 API/页面规划按需读取项目 Skill、编排契约和已有成员，成功生成有依赖及文件归属的计划。两条路径均未运行 `init`、安装、诊断或 Marketplace，也未创建额外团队；复杂场景只规划，未声称业务功能或原生委派已执行。
- Skill validator、diff 空白检查通过。独立 Code Reviewer 检查入口、安装/恢复和引擎关联行为，无已知阻塞发现。仓库 47 文件及导出 Skill 19 文件的定向公开内容扫描无匹配；不是完整秘密检测保证。
- 自动判断依赖宿主实际加载项目入口。这两次受控模型测试不保证所有新会话或其他宿主遵循相同路由，未测量 Token 节省比例；未添加无条件启动钩子。

## 项目入口可移植性与公开内容检查

- 项目入口使用宿主 Skill 发现和项目/源码相对路径；runner 不再向入口生成器传入安装机器的位置。重复初始化会移除托管块中的旧绝对路径，保留用户自有内容。
- 移除已提交的个人安装路径、私人会话链接、本机安装记录和会话专属 Agent 标识。公开仓库链接及上游许可署名保留；环境文件和项目内安装的 Skill 副本加入忽略规则。
- 完整回归 162 项通过。新增检查覆盖五种宿主入口、旧安装指针迁移，以及两处独立安装生成相同入口。扫描了 47 个仓库文件和 19 个导出 Skill 文件，未匹配当前机器个人目录、私人会话链接、私钥或常见 GitHub Token 格式。此定向检查不保证识别所有秘密信息格式。
- 本次清理未重写已有 Git 历史。

## Windows JSON 输出兼容修复

- GitHub Actions `43178611557`：Linux/macOS 的 Python 3.9、3.12 全部成功，Windows 两个版本在 pytest 阶段失败。公开接口未提供详细 traceback；没有将浏览器权限受限的日志声称为已读取。
- 本地把子进程 stdout/stderr 强制设为 cp1252，中文素材库推荐稳定复现 `UnicodeEncodeError`。CLI、标准库安装器和 Skill runner 的 JSON 输出统一为 UTF-8，测试调用方显式用 UTF-8 解码，不通过跳过 Windows 或覆盖 CI 环境掩盖问题。
- 新增 8 项真实子进程回归，覆盖中文推荐、中文安装路径、三入口中文错误及 surrogateescape 文件名错误 JSON。统一 UTF-8 时显式保留 backslashreplace，避免错误处理自身再次崩溃。Python 3.9.6 完整测试 155 项通过；远程最终结果以修复提交对应的 Actions 任务为准。

## Agency-Agents 后备素材库（2.5.0）

- 内置真实上游 `msitarzewski/agency-agents` 的 283 张角色卡，固定 revision `8ae6164602c95ca78828b148b9052460ee426885`；索引 185,189 bytes，附上游 MIT 许可。维护脚本二次构建复用 283/283 未变卡片。
- 默认先评估现有角色，后备库本地 BM25 与中英文场景扩展默认只发送最多 6 张能力卡；角色全文通过按 ID 查询延迟读取。评估缓存绑定需求、检索参数、完整目录、固定索引、平台和宿主证据；评分仍来自宿主 LLM，不是程序测得概率。
- 回归覆盖：中文慢 SQL/营销/无障碍访问检索、无结果与分页、长 Prompt 不进入候选请求、陈旧或伪造评估拒绝、缓存损坏/失效、去重先于分页、平台不兼容现有角色不阻挡后备候选、固定 URL/版本/内容 hash、离线与损坏缓存、路径与重定向限制、预览/授权安装、来源记录及重复安装。
- Python 3.9.6 最终完整测试：`python -m pytest tests -q`，147 项通过。独立 Code Reviewer 再次运行最终版本全量测试，147 项通过；发现的 3 个 P2（先去重再分页、平台/宿主指纹、跨平台去重）均已修复并独立复核，最终无已知阻塞发现。
- 独立 Test Engineer 使用最终导出的 19 文件 Skill，从其他工作目录完成真实小红书场景：现有角色无匹配后才检索后备库、6 张卡语义评估、真实联网角色下载、hash 校验、预览/批准、离线读取及安装、重复安装字节不变、安装后优先复用与后备排除。原生角色状态仍为未验证，没有冒充已经可调用。
- Skill `quick_validate.py` 通过。干净源码 wheel/sdist 构建成功，检查索引和 MIT 随包提供、维护脚本进入 sdist、无 pyc/系统缓存。wheel 独立目录安装后脱离源码检索小红书角色成功；自包含 Skill 导出及再次导出保留索引与许可。
- 原始角色真实联网下载并通过 SHA-256 校验，离线缓存复用成功。本文中的联网验证只请求固定上游角色文件，不执行上游脚本。
- 尚未做大型准确率基准、真实 Token 计量或 Windows/其他宿主本轮实机验收。第一版检索为词法召回加宿主语义判断，不提供 embedding 模型；未命中时由宿主补义或有限扩大检索。

## 宿主 LLM 语义角色推荐（2.4.0 历史验证）

- 对话 Skill 使用 `role recommend --query` 获取全部平台兼容候选，由宿主理解需求后提交 `--assessment`；程序不自动调用外部模型。旧 `--capability` 精确匹配接口保持兼容。
- Python 3.9 完整回归：`python -m pytest tests -q`，112 项通过；Skill validator、文档本地链接与 diff 空白检查通过。
- 回归覆盖：中文需求与英文角色无精确命中时仍提供候选、空推荐、伪造/重复/不兼容 ID、非有限或越界评分、错误引用、陈旧需求及完整角色定义指纹、长说明尾部引用、不能覆盖角色来源/原生可调用状态、CLI 往返与计划能力缺口集成。
- 独立宿主前向验证：隔离项目创建数据库优化、界面设计、部署三个英文职责角色。中文需求“查询订单列表越来越慢，希望有人分析执行计划和索引”返回 9 个候选且精确回退为空；独立 Reviewer 作为实际宿主 LLM 理解资料并提交评估，CLI 校验后推荐 `order-database`，保持 installable 和原生未验证警告。未调用额外模型 API。
- 独立最终 Review 无已知阻塞问题；其专项回归 95 项通过，长说明截断相关的两个 P2 反例已修复并独立复测关闭。
- 评分与语义理由来自宿主判断，程序仅验证请求指纹、候选与原文依据；这些测试不证明语义准确率，也未对大型角色库做召回率或性能基准。本轮未执行远程跨平台 CI。

## 对话安装优化（本轮）

- 普通用户入口改为自然语言安装/使用，内部命令移到 `docs/CLI.md`；安装 Agent 使用 `INSTALL.md` 和 Skill 安装契约。
- 安装器只依赖标准库，导出自包含 Skill；不依赖全局 CLI 或源码工作目录。完整引擎依赖可由 Agent 在 Skill 私有环境准备，无 Python 时提供明确的基础模式。
- 完整测试：Python 3.13 `python -m pytest tests -q`，85 项通过。
- 系统 Python 3.9 安装器专项 unittest：14 项通过，含 `-S` 无第三方依赖预览、冷包初始化/恢复、缓存与防覆盖回归。
- Skill validator 通过，wheel 构建通过。完整 Skill 压缩包生成于 `dist/agent-team-runtime-skill.zip`。
- 独立 Reviewer 在隔离临时项目中完成真实对话安装前向场景：无全局 CLI、从源码目录之外预览/安装，冷 bundle init/status、简单任务完整生命周期、guide，以及三代 bundle 再导出的14项资源保持一致；旧入口刷新并保留用户前后内容。
- 本轮独立 Review 最终无已知阻塞发现，独立专项测试38项通过；基础模式完成指令与格式兼容性审查，未将其描述为完整引擎执行验收。
- 本轮未真实联网安装依赖；setup 失败路径、缓存复用用隔离 mock 验证。不宣称当前宿主已自动发现临时安装 Skill。这些验证在仓库首次公开发布之前完成。

以下为原运行时实现阶段的验证记录。

日期：2026-11-12。工作区：Agent Team Builder。

## 实际执行

| 范围 | 命令或方法 | 结果 |
| --- | --- | --- |
| 完整测试 | `python -m pytest tests -q`（Python 3.13） | 70 passed |
| 核心运行时 | `python3 -m unittest discover -s tests -p test_runtime.py -v`（Python 3.9） | 17 passed |
| CLI | `python3 -m unittest discover -s tests -p test_cli.py -v`（Python 3.9） | 6 passed |
| Review 回归 | `python3 -m unittest discover -s tests -p test_regressions.py -v`（Python 3.9） | 3 passed |
| Skill 格式 | skill-creator `quick_validate.py agent_team/skill` | Skill is valid |
| 安装包 | `pip wheel --no-deps --no-build-isolation` | wheel 构建成功，包含 Skill、契约、CLI entrypoint |
| 独立安装 | Reviewer 在临时目录安装 wheel 并脱离源码运行 | init / guide / generate / preview / install / restore / sequential plan / skill export 通过 |

全部测试使用临时项目，未修改用户全局 Agent 配置。

## 真实 Codex 原生委派

主 Agent 在临时目录初始化团队，并用当前实际工具列表声明宿主能力。产品 `plan_task` 返回：

- mode：`multi_agent`
- strategy：`native_subagents`
- batches：`[[alpha, beta]]`

主 Agent 依照两个生成的 handoff 实际调用 `collaboration.spawn_agent`，分别启动两个 Implementation Engineer。每个 Agent 只有一个文本文件的写入范围，未再委派。

两个 Agent 都实际返回完成结果。主 Agent 随后独立读取并断言 `alpha.txt == b'alpha\n'`、`beta.txt == b'beta\n'`，写入真实验收 evidence，并用 `get_task` 验证持久化状态为 `completed`。

产物和任务记录保存在本次验收的隔离临时目录，未作为发行资源提交。Token、费用、时长未获得实际计量，记录保持 null。CLI 负责生成计划和状态；本次启动由真实宿主工具执行。

## 独立 Review

未参与实现的 Code Reviewer 完成源码审查、反例复现及独立安装前向测试。发现并修复、复核关闭：

1. 角色映射未保留宿主实际 Agent ID。
2. 同 ID 安装后元数据与角色 Prompt 不一致。
3. 安装时遗失角色平台限制。
4. 非 JSON 兼容 YAML 值可导致先写盘后输出失败。
5. 原生计划输出未经宿主证实的调用 ID。
6. 隐式项目角色路径通过软链接读取项目外部文件。

另外补齐轻入口到随包 `guide` 的访问链路。最终独立结论：无已知阻塞问题。主 Agent 复测全部 70 项通过。

## 尚未验证

- Windows 实际运行和其他宿主的真实自动入口/配置加载；已提供多系统 CI 配置，但本次没有远程 CI 运行结果。
- Claude Code、Cursor、Gemini CLI 的原生 Agent 委派。无当前能力证据时走顺序交接。
- 强制杀进程、断电、磁盘故障时的完整恢复；已有原子写入、写锁和安装失败回滚测试，不能代替全部故障注入。
- 跨会话 KV Cache 或 Token 节约幅度；系统不作缓存命中及节约比例保证。
