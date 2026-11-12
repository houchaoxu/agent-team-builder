"""Command line interface. All successful commands emit machine-readable JSON."""

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .installer import export_bundle, skill_source
from .adapters import capabilities, detect_platform
from .marketplace import build_catalog, generate_role, install_role, recommend_roles
from .recommendation import apply_assessment, semantic_request
from .runtime import (add_memory, analytics, get_task, list_tasks, plan_task,
                      read_memory, update_task)
from .storage import bootstrap, discover_root, read_yaml, safe_path, validate_team

PLATFORMS = ("auto", "codex", "claude-code", "cursor", "gemini-cli", "generic")


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--project", type=Path, default=Path.cwd(), help="项目或其中的目录")
    p.add_argument("--platform", choices=PLATFORMS, default="auto")
    p.add_argument("--host", type=Path, help="本次会话宿主能力证明 YAML/JSON；不自动推断执行能力")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="初始化或恢复项目团队，保留已有入口")
    sub.add_parser("status", help="验证和查看团队索引")
    sub.add_parser("doctor", help="检查配置和实际可用能力")
    plan = sub.add_parser("plan", help="依据主 Agent 提供的语义分析生成任务交接")
    plan.add_argument("spec", type=Path)
    task = sub.add_parser("task", help="任务历史与状态")
    task_sub = task.add_subparsers(dest="action", required=True)
    task_sub.add_parser("list")
    show = task_sub.add_parser("show")
    show.add_argument("id")
    update = task_sub.add_parser("update")
    update.add_argument("id")
    update.add_argument("status", choices=("running", "completed", "failed", "cancelled"))
    update.add_argument("--summary", default="")
    update.add_argument("--evidence", type=Path, help="真实验收结果映射 YAML/JSON")
    update.add_argument("--metrics", type=Path, help="宿主提供的实际统计映射 YAML/JSON")
    role = sub.add_parser("role", help="角色发现、推荐、生成和项目安装")
    role_sub = role.add_subparsers(dest="action", required=True)
    catalog = role_sub.add_parser("catalog")
    catalog.add_argument("--source", action="append", type=Path, default=[])
    recommend = role_sub.add_parser("recommend")
    recommend.add_argument("--capability", action="append", default=[])
    recommend.add_argument("--query", help="自然语言需求；由宿主 LLM 进行语义评估")
    recommend.add_argument("--assessment", type=Path, help="宿主 LLM 的语义评估 YAML/JSON")
    recommend.add_argument("--deliverable", action="append", default=[])
    recommend.add_argument("--source", action="append", type=Path, default=[])
    gen = role_sub.add_parser("generate", help="生成角色草案 JSON 到标准输出")
    gen.add_argument("id")
    gen.add_argument("--name", required=True)
    gen.add_argument("--capability", action="append", required=True)
    gen.add_argument("--deliverable", action="append", default=[])
    install = role_sub.add_parser("install", help="默认预览；--approve 才写项目内文件")
    install.add_argument("profile", type=Path)
    install.add_argument("--approve", action="store_true")
    memory = sub.add_parser("memory", help="有来源的项目知识")
    memory_sub = memory.add_subparsers(dest="action", required=True)
    mem_show = memory_sub.add_parser("show")
    mem_show.add_argument("--category", choices=("project-context", "architecture", "decisions", "experience"))
    mem_add = memory_sub.add_parser("add")
    mem_add.add_argument("category", choices=("project-context", "architecture", "decisions", "experience"))
    mem_add.add_argument("text")
    mem_add.add_argument("--source", required=True)
    mem_add.add_argument("--approve", action="store_true", help="确认重要架构/决策记忆")
    mem_update = memory_sub.add_parser("update", help="更新过期信息并保留修订历史")
    mem_update.add_argument("category", choices=("project-context", "architecture", "decisions", "experience"))
    mem_update.add_argument("id")
    mem_update.add_argument("text")
    mem_update.add_argument("--source", required=True)
    mem_update.add_argument("--approve", action="store_true")
    sub.add_parser("analytics", help="真实任务数据，缺失数据保持 null")
    sub.add_parser("guide", help="按需读取随包 Skill、任务格式和宿主执行契约")
    skill = sub.add_parser("skill", help="导出可安装的入口 Skill；不修改全局设置")
    skill.add_argument("destination", type=Path)
    return p


def export_skill(destination):
    return export_bundle(destination)


def dispatch(args):
    if args.command == "guide":
        source = skill_source()
        return {"skill": (source / "SKILL.md").read_text(encoding="utf-8"),
                "orchestration": (source / "references/orchestration.md").read_text(encoding="utf-8")}
    if args.command == "skill":
        return export_skill(args.destination)
    start = args.project.expanduser().resolve()
    if not start.is_dir():
        raise ValueError("项目目录不存在: {}".format(start))
    root = discover_root(start)
    host = read_yaml(args.host) if args.host else None
    platform = detect_platform(root) if args.platform == "auto" else args.platform
    if args.command == "init":
        return bootstrap(root, platform)
    if args.command == "plan":
        spec = read_yaml(args.spec)
        # Every plan can be created without loading a role catalog for simple work.
        return plan_task(root, spec, host=host)
    if args.command in ("status", "doctor"):
        team = validate_team(read_yaml(safe_path(root, ".agent-team/team.yaml")))
        if args.command == "status":
            return {"root": str(root), "team": team}
        return {"root": str(root), "team_valid": True,
                "capabilities": capabilities(platform, host),
                "roles": build_catalog(root, platform, host=host)}
    if args.command == "task":
        if args.action == "list":
            return list_tasks(root)
        if args.action == "show":
            return get_task(root, args.id)
        return update_task(root, args.id, args.status, args.summary,
                           metrics=read_yaml(args.metrics) if args.metrics else None,
                           evidence=read_yaml(args.evidence) if args.evidence else None)
    if args.command == "role":
        if args.action == "generate":
            return generate_role(args.id, args.name, args.capability, args.deliverable)
        if args.action == "install":
            return install_role(root, read_yaml(args.profile), platform, args.approve, host)
        catalog = build_catalog(root, platform, sources=args.source or None, host=host)
        if args.action == "catalog":
            return catalog
        if args.query is not None:
            request = semantic_request(catalog, args.query, args.capability, args.deliverable)
            return apply_assessment(catalog, request, read_yaml(args.assessment)) if args.assessment else request
        if args.assessment or not args.capability:
            raise ValueError("Use --query for semantic matching, or --capability for exact matching.")
        return recommend_roles(catalog, args.capability, args.deliverable)
    if args.command == "memory":
        if args.action == "show":
            return read_memory(root, args.category)
        if args.action == "update":
            from .runtime import update_memory
            return update_memory(root, args.category, args.id, args.text, args.source, args.approve)
        return add_memory(root, args.category, args.text, args.source, args.approve)
    if args.command == "analytics":
        return analytics(root)
    raise ValueError("不支持的命令")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = dispatch(args)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
