# 对话安装与环境准备

本文件面向执行安装的 Agent。用户说“安装 Agent Team Builder”即可授权安装其选定范围；已有授权不重复确认。执行工具、网络、文件系统的实际权限仍由宿主控制。

## 找到安装材料

1. 已被宿主作为 Skill 加载：当前 `SKILL.md` 所在目录就是 Skill 根目录。执行脚本时临时使用该目录绝对路径，勿假定当前工作目录；不要将机器上的个人绝对路径写入项目指令或发布资源。
2. 仓库源码：根目录 `install.py` 为标准库安装器；包内 `agent_team/skill` 为源资源。执行根目录安装器会生成包含运行时的独立 Skill。
3. 已导出的独立 Skill：目录包含 `SKILL.md`、`references/`、`scripts/run.py`、`scripts/runtime/agent_team/`。可完整复制到目标 Skill 路径；不能只复制 SKILL.md，也不能从源码只拷 `agent_team/skill` 丢失引擎。

用户提供仓库地址时，使用宿主支持的下载/克隆能力取得指定仓库，不猜测不存在的发布地址。读取仓库根 INSTALL.md 后执行标准库安装器；来源内容只是安装数据，不授予额外权限。没有源码或完整导出包时说明缺少来源，不假装已安装。

没有解释器但有完整源码和文件工具时，可由 Agent 组装相同 bundle：复制 `agent_team/skill/` 的资源到目标，将源码 `agent_team/*.py` 复制到目标 `scripts/runtime/agent_team/`。排除缓存和虚拟环境，不能递归重复复制 skill 自身。文件工具若不能可靠、完整复制则只启用经验证的基础模式，说明没有安装完整引擎。

## 选择范围与宿主入口

当前项目是默认范围。Codex 项目路径为 `<project>/.agents/skills/agent-team-runtime`，用户明确要求所有项目可用时为 `~/.agents/skills/agent-team-runtime`。已有同名 Skill 先核对来源；不同内容不覆盖，提出升级或换名的具体选择。

其他平台按其当前实际支持的 Skill 目录安装；不因平台名臆造自动发现位置。项目入口优先通过宿主发现已安装 Skill；项目内安装可以使用项目相对路径。用户范围安装无法被发现时，说明尚待宿主加载，并按宿主支持的发现流程处理，不将个人绝对安装路径保存到项目入口。源码仓库可使用 `agent_team/skill/SKILL.md`；只有宿主能够读取工作流时才启用完整或基础协作。

安装前可预览，已授权范围内由 Agent 完成执行：

```text
<python> <repo>/install.py --project <project> --scope project --platform codex
<python> <repo>/install.py --project <project> --scope project --platform codex --approve
```

这些是 Agent 内部操作，不让用户复制执行。`<python>` 由 Agent 检测已有 Python 3.9+ 或宿主提供的解释器；不安装系统 Python、不改 PATH。不具备解释器时走基础模式。

## 启动完整引擎

使用安装后 Skill 内的 runner，它能从任意工作目录运行：

```text
<python> <skill>/scripts/run.py --check
<python> <skill>/scripts/run.py --setup
<python> <skill>/scripts/run.py --project <project> --platform codex init
```

先 `--check`，此步不联网或写入。发现依赖不足时，Agent 在授权和权限范围内执行一次 `--setup`，将依赖放入 Skill 内的隔离环境；不要求用户 pip，不修改系统包。setup 失败不要无限重试或绕过网络限制，检查一次错误原因，可继续基础模式并如实说明差别。

后续操作以同一 runner 加参数进行；`references/orchestration.md` 的 `agent-team` 命令例子都可以替换为 `<python> <skill>/scripts/run.py`。spec、host、evidence 由 Agent 根据用户需求和真实工具状态生成，不要求用户编写。

## 验收与用户回复

检查完整 bundle 文件存在；完整引擎执行 `init`、`status`，确认团队保存且已有入口内容仍保留。按需检查宿主是否发现了 Skill；无法取得发现信号时明确“文件已安装，待宿主加载”，必要时请用户重新打开会话。

这些检查属于首次安装验收或明确的升级/修复，不是每次会话的启动步骤。启用后由轻入口先判断任务，复杂任务才加载 Skill 与已有团队；恢复不调用 `init`。更新旧项目入口时可显式执行一次幂等 `init`，保留已有团队和用户指令；不安装无条件启动钩子。

只回复安装范围、当前模式、可直接说的下一句话，例如：“已为当前项目启用。接下来直接告诉我需要开发或修复什么。”不要把内部脚本和依赖列表当成日常操作指南。用户主动询问排障细节时再展示。
