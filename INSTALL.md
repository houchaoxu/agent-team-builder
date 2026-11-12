# 给安装 Agent 的操作契约

用户将仓库/完整 Skill 包交给你并要求安装时，由你完成环境准备和安装，最终让用户通过自然语言使用。不要把 Python 或 pip 命令交给用户执行。

## 选择安装入口

- 本地完整源码：执行根 `install.py`，仅用标准库，不依赖事先安装本项目、PyYAML 或系统 PATH 中的 agent-team。
- 用户给的是仓库地址：使用宿主已授权的克隆/下载工具取得**该真实地址**，读取此文件后执行同一安装流程。不要臆造 GitHub owner、默认分支或发行 URL。
- 用户给的是完整导出 Skill：应包含 SKILL.md、references、scripts/run.py 和 scripts/runtime/agent_team。将完整目录安装到宿主实际支持的位置，不只复制 SKILL.md。

默认范围为当前项目；只有用户明确要求跨项目使用才选 user。Codex 项目路径 `.agents/skills/agent-team-runtime`，个人路径 `~/.agents/skills/agent-team-runtime`。其他宿主先核对其实际 Skill/指令机制，必要时通过 `--destination` 选一个明确目录并链接其项目入口；不假装自动发现。现有同名不同内容不覆盖。

## 由 Agent 执行

1. 检测已有 Python 3.9+ 或宿主提供的解释器。没有时，先用文件工具复制完整 Skill；仅有源码时按 references/installation.md 的布局组装 bundle，再按 basic-mode.md 启用基础协作。不替用户安装系统软件。
2. 预览：`<python> <repo>/install.py --project <project> --scope project --platform codex`。
3. 对已授权的范围执行同命令加 `--approve`。明确项目/个人安装的用户请求已提供相应授权，不额外机械确认；宿主的实际写入权限仍需遵守。
4. 读取安装后 SKILL.md，Agent 执行 `<python> <skill>/scripts/run.py --check`。若要求准备环境，执行一次 `--setup`，依赖安装到 Skill 私有缓存环境，不影响系统包。
5. Agent 调 runner 进行 `--project <project> --platform <actual-platform> init` 与 `status`。项目入口保留用户已有内容。
6. 验证当前宿主是否发现 Skill。无法证明已加载时，准确报告“文件已安装，待宿主加载”；按宿主实际要求引导重新打开会话。

更详细的动作边界与基础模式在安装包的 `references/installation.md`、`references/basic-mode.md`。失败时记录准确原因；可完成的项目配置继续完成，不绕过环境权限或无限重试下载。

## 成功回复

用户只需要知道：安装位置/范围、完整或基础模式、是否已验证宿主加载、下一步直接描述需求。日常操作不暴露 YAML、任务ID、venv或内部命令，除非用户主动询问。
