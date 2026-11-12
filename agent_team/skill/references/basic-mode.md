# 基础协作模式（无需 Python）

缺少可执行引擎时，用宿主文件读写工具执行以下有限流程。用户仍用自然语言，不被要求安装 Python。没有文件工具时只能给出协作建议，不声称已安装项目配置。

## 初始化与恢复

检查 `.agent-team/team.yaml`。存在则按需读取并复用；损坏或字段不明时保留原文，说明问题，不自行重建。团队缺失时先确认未有完整引擎初始化留下的其他文件；避免两个会话同时写入。

首次初始化可创建以下兼容索引（JSON 是合法 YAML，便于宿主工具写入）。用真实项目名称和宿主可用角色填入项目及成员，不把模板名当成已安装可调用角色：

```json
{
  "schema_version": "1.0",
  "platform": "generic",
  "project": {"id": "<生成唯一ID>", "name": "<项目名>", "root": ".", "stack": []},
  "team": {"id": "<生成唯一ID>", "name": "Project Team", "status": "active", "members": [
    {"id": "implementer", "role": "implementation", "capabilities": ["implementation"], "status": "unavailable"}
  ]},
  "settings": {}
}
```

只在项目内写 `.agent-team/members/`、`memory/`、`tasks/`。对 Codex 使用 AGENTS.md、Claude Code 使用 CLAUDE.md、Gemini 使用 GEMINI.md；Cursor 仅在已知支持的规则路径追加适当规则。保留已有内容，追加带唯一标记的轻入口，明确本 Skill 的真实绝对路径和团队位置。

入口要求：默认单 Agent，复杂任务才读取本 Skill 和团队索引；恢复已有团队；委派遵守宿主权限和本次会话工具证据。普通任务不扫描全角色。

## 任务与能力边界

默认主 Agent 完成任务。只有宿主确有委派工具且有独立交付物时才委派，最多3个并发子 Agent，每个有唯一写入范围；无法确定文件是否冲突时顺序执行。Reviewer 只读。用宿主实际返回值确认启动与完成，保留简短 Markdown 任务记录。

基础模式不写完整引擎专用的 `tasks/*.yaml`，避免产生未通过校验的状态；用 `.agent-team/tasks/<唯一ID>.md` 保存真实目标、范围、执行者、验收结果和限制。未知计量保持未测。无需把任务日志转成长期记忆。

长效知识以独立 Markdown 文件放入 memory，并保留来源、日期、决策理由；不覆盖完整引擎的 YAML 记忆。重要架构决策仍需用户确认。角色安装以定义草案/项目 Prompt 为限，不能声称完成原生格式和可调用性验证。

回复明确为“基础协作模式”，不宣称具备 CLI 的配置验证、跨进程写锁、原子持久化或完整指标统计。后续解释器与依赖可用时由 Agent 启用完整引擎；保留这些 Markdown 记录，不静默改写。
