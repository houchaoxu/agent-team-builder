# 宿主验收 / Host validation

适配器提供安装格式，当前会话工具决定能否委派。以下状态用于区分程序测试与真实产品验证，不构成任何宿主版本的兼容性保证。

| 宿主 | 当前安装方式 | 原生发现、注册、调用与返回的版本化实测证据 |
| --- | --- | --- |
| Codex | 对应 Skill 目录与项目入口 | 暂无随仓库发布的版本化回执；已有用户成功反馈 |
| Claude Code | 对应 Skill 目录与项目入口 | 待记录 |
| WorkBuddy | Skill ZIP 导入，按会话能力选择执行方式 | 待记录 |
| Trae | 项目 Skill 与规则入口 | 待记录 |
| Pi | 项目 Skill，按需 reload | 待记录 |

自动测试覆盖转换、路由、权限边界和回执校验；它们不操作这些产品的真实 UI，也不能证明原生注册或调用成功。未验证的阶段显示 unknown，表示缺少证据，不表示产品不支持。

## 在当前项目验收

由宿主 Agent 在用户授权范围内操作，无需用户自己执行命令：

1. 确认实际宿主版本、当前会话工具与所选角色，形成 `--host` 证据。
2. 检查安装文件与 Skill 是否被宿主发现。原生角色注册只在实际适用且观察到成功时记录。
3. 经授权做一次最小只读调用；保存真实返回的 Agent ID，再取得并核对结果。无法操作的阶段保持待验证。
4. 用 `host verify` 保存回执，再用 `host matrix` 查看各宿主最近记录的阶段与版本。

矩阵读取项目内 `.agent-team/hosts/<platform>.json`，不会联网、自动启动子 Agent 或扫描个人角色目录。它展示最近一次历史回执，不提供当前会话授权；后续任务仍按实际工具判断。发布测试记录前检查其中是否包含私人路径或项目内容。

## Reading the result

The adapters and automated tests cover packaging, routing, and receipt validation. Live discovery, registration, invocation, and returned results need evidence from the specific host version. `host matrix` summarizes the project's latest saved receipts; missing stages stay unknown. Historical results never become current-session capabilities.
