# Agency-Agents 宿主安装适配

本文件面向执行安装的 Agent。用户通过对话选择角色、查看预览并手动确认；以下参数和脚本由 Agent 处理，不要求用户执行命令。角色推荐和手动确认契约见 [role-matching.md](role-matching.md)。

## 目标和作用域

先核对当前实际宿主，再用 `role tools` 查询随包固定版本的支持矩阵。它列出上游 17 个目标，本项目支持其中 16 个的文件安装；Hermes 的路由插件/配置集成尚不支持。矩阵描述文件格式与安装契约，不证明宿主已加载角色或具备委派能力。

| 安装目标（`--platform`） | 可选作用域 | 安装内容 |
| --- | --- | --- |
| `codex`、`claude-code`、`gemini-cli`、`copilot`、`opencode`、`qwen`、`zcode` | project / user | 对应宿主角色文件 |
| `antigravity`、`dsh` | project / user | 每角色一个 Skill 目录 |
| `vibe` | project / user | 角色 TOML 与配套 prompt |
| `cursor` | project | `.cursor/rules/` 中的规则 |
| `aider`、`windsurf` | project | 由已选角色构成的合并索引/规则文件 |
| `kimi`、`osaurus` | user | 多文件角色 / Skill 目录 |
| `openclaw` | user | 工作区文件，仍需单独原生注册 |
| `hermes` | 此安装器不支持 | 上游为路由插件，涉及配置启用 |

`--scope project` 是默认值。当前目标不支持项目范围时，向用户说明可用范围并等待其明确选择，不自动切到 `user`。用户范围角色文件写到用户目录，当前项目仍保存可移植定义和团队记录；另将角色资料与原生文件 hash 记录到 `~/.agent-team/agency-roles/<tool>/<id>.json`，此文件也在具体预览中列出并确认。其他项目只读取当前宿主的托管记录并验证原生文件后复用，避免重复安装或列出原生别名。手动修改过的文件会使对应记录校验失败并提示，不静默恢复。任务规划可按所选角色 ID 临时加载已验证的个人角色，不重复安装，也不为复用而重建或改写项目团队；原生调用仍需当前宿主证据。宿主权限不足时报告真实阻塞，不把 `--approve` 当作沙箱权限。

其他工具可选择 `--platform generic` 保存可移植角色指令，再由宿主支持的通用子 Agent 或主 Agent 顺序执行；不能承诺任意工具都能注册原生角色。

## 执行方式

完整引擎下，沿用已有团队；只有首次启用项目才按安装流程初始化。实际调用使用随 Skill 的 `<python> <skill>/scripts/run.py` 替代下文的 `agent-team`。

```sh
agent-team --project /project role tools
agent-team --project /project --platform opencode role install --agency AGENCY_ROLE_ID
# 仅在用户明确确认上面的具体预览后，保持相同参数：
agent-team --project /project --platform opencode role install --agency AGENCY_ROLE_ID --approve
```

若用户明确选择个人范围，预览和执行都加 `--scope user`；用户选择只授权准备该范围的预览，安装仍等待针对预览的手动确认。目标、范围、文件内容或安装后端变化时重新预览确认。

`--installer auto` 是默认值：Agency 角色在非 `generic` 目标使用上游桥接，`generic` 使用内置可移植格式。`--installer agency` 显式选择上游桥接，必须提供 `--agency ID`。`--installer builtin` 显式选择内置项目角色格式，也用于兼容本地规范化 profile；它不承诺额外宿主的原生格式，且不支持 `user` 范围。

桥接随包保存与角色索引同 revision 的上游 `install.sh`、`convert.sh`、`lib.sh` 和安装元数据，执行前校验文件 hash。只获取已选角色的固定版本正文并校验、缓存，保留许可证与来源；无需用户 clone Agency-Agents。

上游脚本先在独立临时目录转换、安装，输入只包含本次角色及合并文件所需的既有已选角色。真实项目和用户目录不交给脚本。桥接收集产物后返回精确文件、内容、作用域和激活要求，再由本项目在确认后写入目标及团队索引。不同内容的现有文件拒绝覆盖，团队索引写入失败会恢复本次文件变更。

桥接需要 Bash 3.2+、标准 Unix 工具；TOML 转换还需 Perl。Windows 需要可用的 Git Bash/WSL 环境，原生 PowerShell 本身不具备这些条件。没有依赖时明确说明；若用户选择可移植后端，重新预览并确认，不能声称已完成原生安装。

## 合并与激活

- **Aider / Windsurf：**合并此前已安装和本次选定角色，保留其他已选角色。只有 hash 仍匹配的托管合并文件可以更新；用户编辑过的文件保留并报告冲突。Aider 的角色全文保存在项目 `.agent-team/agency-sources/`，索引指向持久路径，不依赖临时上游目录。
- **OpenClaw：**仅使用上游转换器生成工作区文件，不执行会调用真实 OpenClaw CLI 的上游安装步骤。返回 `activation.state=registration_required` 和待执行命令；注册、修改原生状态或重启需有对应明确授权，并核对实际状态。文件安装成功不能报告为角色已激活。
- **Hermes：**不将路由插件伪装成单角色安装，也不自动修改插件配置。说明当前边界；用户可选择可移植指令，或另行授权处理插件集成。
- **所有目标：**分别验证文件安装、团队记录、宿主发现和真实调用。返回的 `agent_id` 来自宿主产物，项目角色 ID 用于团队记录；不能改名或伪造宿主证据来强制原生执行。必要时刷新会话；无法原生发现时明确实际交接执行者。

`--offline` 禁止下载，使用校验通过的缓存与随包脚本。合并文件所需的既有角色也必须具备有效缓存；缺少时说明具体阻塞，不下载整库或改用未固定分支。

## 维护固定资源

维护者从干净的上游 checkout 先运行 `scripts/build_agency_index.py CHECKOUT`，再用同一 revision 运行 `scripts/build_agency_installer.py CHECKOUT`（可用 `--data DATA` 指定数据目录），从 Git blob 同步五个上游资源及 hash manifest，避免 checkout 换行转换改变固定字节。后者拒绝脏 checkout 或与索引不一致的 revision。发布前审查脚本副作用、目标与作用域变化，并运行转换、冲突保护和确认流程测试；只更新索引或只更新脚本都不能视为已完成同步。普通用户无需执行这些维护命令。
