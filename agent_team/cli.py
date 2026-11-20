"""Command line interface. All successful commands emit machine-readable JSON."""

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .installer import export_bundle, skill_source
from .adapters import PLATFORMS as HOST_PLATFORMS, capabilities
from .marketplace import build_catalog, generate_role, install_role, recommend_roles
from .recommendation import assessed_request, compact_request, _digest
from .runtime import (add_memory, analytics, get_task, list_tasks, plan_task,
                      read_memory, update_task)
from .storage import bootstrap, discover_root, read_yaml, safe_path, validate_team

PLATFORMS = ("auto",) + HOST_PLATFORMS


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
    host_parser = sub.add_parser("host", help="协商当前宿主能力；验收记录不作为以后会话的工具证据")
    host_sub = host_parser.add_subparsers(dest="action", required=True)
    host_sub.add_parser("inspect", help="只读查看安装契约、当前会话能力与执行方式")
    verify = host_sub.add_parser("verify", help="校验并保存宿主实际验收结果，不执行宿主工具")
    verify.add_argument("receipt", type=Path)
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
    role_sub.add_parser("tools", help="查询 Agency 上游安装目标、格式和作用域")
    catalog = role_sub.add_parser("catalog")
    catalog.add_argument("--source", action="append", type=Path, default=[])
    recommend = role_sub.add_parser("recommend")
    recommend.add_argument("--capability", action="append", default=[])
    recommend.add_argument("--query", help="自然语言需求；由宿主 LLM 进行语义评估")
    recommend.add_argument("--assessment", type=Path, help="宿主 LLM 的语义评估 YAML/JSON")
    recommend.add_argument("--deliverable", action="append", default=[])
    recommend.add_argument("--source", action="append", type=Path, default=[])
    recommend.add_argument("--library", choices=("installed", "agency"), default="installed")
    recommend.add_argument("--term", action="append", default=[], help="宿主补充的检索词，可用英文能力短语")
    recommend.add_argument("--limit", type=int, default=6, help="每次交给宿主的能力卡数量，1..20")
    recommend.add_argument("--offset", type=int, default=0, help="扩大候选检索的分页偏移")
    show_role = role_sub.add_parser("show", help="仅加载选中角色的完整资料")
    show_role.add_argument("id")
    show_role.add_argument("--source", action="append", type=Path, default=[])
    show_role.add_argument("--library", choices=("installed", "agency"), default="installed")
    show_role.add_argument("--offline", action="store_true")
    gen = role_sub.add_parser("generate", help="生成角色草案 JSON 到标准输出")
    gen.add_argument("id")
    gen.add_argument("--name", required=True)
    gen.add_argument("--capability", action="append", required=True)
    gen.add_argument("--deliverable", action="append", default=[])
    install = role_sub.add_parser("install", help="默认预览；--approve 才写项目内文件")
    install.add_argument("profile", type=Path, nargs="?")
    install.add_argument("--agency", metavar="ID", help="按需获取并安装 Agency-Agents 角色")
    install.add_argument("--offline", action="store_true", help="仅使用已校验的本地缓存")
    install.add_argument("--approve", action="store_true")
    install.add_argument("--installer", choices=("auto", "agency", "builtin"), default="auto",
                         help="Agency 角色默认使用固定版本上游安装器；generic 使用内置可移植格式")
    install.add_argument("--scope", choices=("project", "user"), default="project",
                         help="角色安装范围；user 需要用户明确选择和确认")
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
    update = sub.add_parser("update", help="Skill 更新检查、偏好、预览升级与回退")
    update.add_argument("--skill", type=Path, help="完整安装的 Skill 目录；默认当前随包 Skill")
    update_sub = update.add_subparsers(dest="action", required=True)
    check = update_sub.add_parser("check")
    check.add_argument("--force", action="store_true")
    update_sub.add_parser("status")
    configure = update_sub.add_parser("configure")
    configure.add_argument("--enabled", choices=("true", "false"))
    configure.add_argument("--snooze-days", type=int)
    apply = update_sub.add_parser("apply")
    apply.add_argument("--approve", action="store_true")
    rollback = update_sub.add_parser("rollback")
    rollback.add_argument("backup_id")
    rollback.add_argument("--approve", action="store_true")
    return p


def export_skill(destination):
    return export_bundle(destination)


def dispatch(args):
    if args.command == "update":
        from .updates import check_updates, configure_updates, rollback, update_status, upgrade
        skill = args.skill or skill_source()
        if args.action == "check":
            return check_updates(skill, force=args.force)
        if args.action == "status":
            return update_status(skill)
        if args.action == "configure":
            return configure_updates(skill, enabled=None if args.enabled is None else args.enabled == "true",
                                     snooze_days=args.snooze_days)
        if args.action == "apply":
            return upgrade(skill, approved=args.approve)
        return rollback(skill, args.backup_id, approved=args.approve)
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
    from .hosts import detect_host, inspect_host, negotiate, record_verification
    platform = detect_host(root, host=host) if args.platform == "auto" else args.platform
    negotiate(platform, host)
    if args.command == "host":
        if args.action == "inspect":
            return inspect_host(platform, host, root)
        return record_verification(root, platform, read_yaml(args.receipt), host)
    if args.command == "init":
        return bootstrap(root, platform)
    if args.command == "plan":
        spec = read_yaml(args.spec)
        # Every plan can be created without loading a role catalog for simple work.
        return plan_task(root, spec, host=host, platform=platform)
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
        if args.action == "tools":
            from .agency_install import supported_tools
            return supported_tools()
        if args.action == "generate":
            return generate_role(args.id, args.name, args.capability, args.deliverable)
        if args.action == "install":
            if bool(args.profile) == bool(args.agency):
                raise ValueError("Provide one profile file or --agency ID.")
            if args.agency:
                if args.installer == "agency" or (args.installer == "auto" and platform != "generic"):
                    from .agency_install import install_agency_role
                    return install_agency_role(root, args.agency, platform, scope=args.scope,
                                               approved=args.approve, host=host, offline=args.offline)
                from .agency import fetch_role
                profile = fetch_role(root, args.agency, platform=platform, offline=args.offline)
            else:
                if args.installer == "agency":
                    raise ValueError("The upstream installer requires --agency ID.")
                profile = read_yaml(args.profile)
            if args.scope != "project":
                raise ValueError("User scope requires the Agency installer and --agency ID.")
            return install_role(root, profile, platform, args.approve, host)
        catalog = build_catalog(root, platform, sources=args.source or None, host=host)
        if args.action == "catalog":
            return catalog
        if args.action == "show":
            if args.library == "agency":
                from .agency import fetch_role
                return fetch_role(root, args.id, platform=platform, offline=args.offline)
            role = next((role for role in catalog if role["id"] == args.id), None)
            if role is None:
                raise ValueError("Unknown role: " + args.id)
            return role
        if args.query is not None:
            if args.library == "agency":
                from .agency import load_index, search_roles
                if args.source:
                    raise ValueError("Use --source for local discovery or --library agency, not both.")
                if not 1 <= args.limit <= 20 or args.offset < 0:
                    raise ValueError("limit must be 1..20 and offset must be non-negative.")
                index = load_index()
                # Do not offer an upstream profile already present in the project
                # or user directories under a different local identifier.
                installed = [role for role in catalog if role.get("source") not in ("builtin", "generated")]
                reusable = [role for role in installed if role.get("platform_compatible") is not False
                            and role.get("installed_for_platform") is True]
                names = {role["name"].strip().casefold() for role in reusable}
                paths = {role.get("upstream", {}).get("path") for role in reusable}
                identifiers = {role["id"] for role in reusable}
                excluded = {card["id"] for card in index["roles"]
                            if card["name"].strip().casefold() in names or card["path"] in paths
                            or card["id"] in identifiers}
                candidates = search_roles(args.query, terms=args.term + args.capability + args.deliverable,
                                          limit=args.limit, offset=args.offset, platform=platform,
                                          excluded_ids=excluded)
                context = {"library": "agency", "revision": index["revision"],
                           "index_digest": _digest(index), "installed_digest": _digest(installed),
                           "total_roles": len(index["roles"]), "offset": args.offset,
                           "platform": platform, "host": capabilities(platform, host)}
                request = compact_request(candidates, args.query, args.capability, args.deliverable,
                                          terms=args.term, limit=args.limit, context=context)
                catalog = candidates
            else:
                # Generated drafts remain available through catalog and the old
                # exact interface, but cannot displace existing installed agents.
                catalog = [role for role in catalog if role.get("source") not in ("builtin", "generated")]
                request = compact_request(catalog, args.query, args.capability, args.deliverable,
                                          terms=args.term, limit=args.limit, offset=args.offset,
                                          context={"platform": platform, "host": capabilities(platform, host)})
            return assessed_request(root, catalog, request,
                                    read_yaml(args.assessment) if args.assessment else None)
        if args.assessment or not args.capability:
            raise ValueError("Use --query for semantic matching, or --capability for exact matching.")
        if args.library != "installed" or args.term or args.offset or args.limit != 6:
            raise ValueError("Library retrieval options require --query.")
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
    # JSON is a UTF-8 protocol, independent of Windows' redirected code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = parser().parse_args(argv)
    try:
        result = dispatch(args)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
