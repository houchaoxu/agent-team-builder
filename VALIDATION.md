# 验证记录

## 对话安装优化（本轮）

- 普通用户入口改为自然语言安装/使用，内部命令移到 `docs/CLI.md`；安装 Agent 使用 `INSTALL.md` 和 Skill 安装契约。
- 安装器只依赖标准库，导出自包含 Skill；不依赖全局 CLI 或源码工作目录。完整引擎依赖可由 Agent 在 Skill 私有环境准备，无 Python 时提供明确的基础模式。
- 完整测试：Python 3.13 `python -m pytest tests -q`，85 项通过。
- 系统 Python 3.9 安装器专项 unittest：14 项通过，含 `-S` 无第三方依赖预览、冷包初始化/恢复、缓存与防覆盖回归。
- Skill validator 通过，wheel 构建通过。完整 Skill 压缩包生成于 `dist/agent-team-runtime-skill.zip`。
- 独立 Reviewer 在隔离临时项目中完成真实对话安装前向场景：无全局 CLI、从源码目录之外预览/安装，冷 bundle init/status、简单任务完整生命周期、guide，以及三代 bundle 再导出的14项资源保持一致；旧入口刷新绝对 Skill 路径且保留用户前后内容。
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

主 Agent 依照两个生成的 handoff 实际调用 `collaboration.spawn_agent`，分别启动 `/root/native_alpha` 和 `/root/native_beta`（Implementation Engineer）。每个 Agent 只有一个文本文件的写入范围，未再委派。

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
