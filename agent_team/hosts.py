"""Standard-library host negotiation; host tools execute the returned handoffs.

Platform contracts describe packaging, never runtime availability. Capability
observations belong to the supplied session and are not restored from disk.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .platforms import PLATFORMS

STAGES = ("files_installed", "skill_discovered", "role_registered", "agent_invoked", "result_received")


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _platform(value):
    if value not in PLATFORMS:
        raise ValueError("Unsupported platform: " + str(value))
    return value


def detect_host(root, env=None, host=None, require_runtime=False):
    """Prefer session identity; project folders only provide contextual hints."""
    env = os.environ if env is None else env
    host = {} if host is None else host
    if not isinstance(host, dict):
        raise ValueError("host must be a mapping")
    if host.get("platform") is not None:
        if not _text(host.get("evidence")):
            raise ValueError("Session platform requires host evidence")
        return _platform(host["platform"])
    if env.get("AGENT_TEAM_PLATFORM"):
        return _platform(env["AGENT_TEAM_PLATFORM"])
    active = {platform for marker, platform in (
        ("CODEX_THREAD_ID", "codex"), ("CLAUDE_CODE_ENTRYPOINT", "claude-code"),
        ("CURSOR_AGENT", "cursor"), ("GEMINI_CLI", "gemini-cli")) if env.get(marker)}
    if len(active) > 1:
        raise ValueError("Conflicting active host markers; select the actual --platform or supply --host")
    if active:
        return active.pop()
    if require_runtime:
        return "generic"
    root = Path(root)
    contexts = {platform for directory, platform in (
        (".codex", "codex"), (".claude", "claude-code"), (".cursor", "cursor"),
        (".gemini", "gemini-cli"), (".opencode", "opencode"), (".qwen", "qwen"),
        (".trae", "trae"), (".pi", "pi"), (".vibe", "vibe"), (".zcode", "zcode"),
        (".dsh", "dsh")) if (root / directory).is_dir()}
    if len(contexts) == 1:
        return contexts.pop()
    return "generic"


def negotiate(platform, host=None):
    """Normalize current tool observations, retaining unknowns as None.

    The legacy evidence/native_subagents format stays supported. Version 1
    additionally binds observations to an explicit host and session identity.
    """
    _platform(platform)
    host = {} if host is None else host
    if not isinstance(host, dict):
        raise ValueError("host must be a mapping")
    if "schema_version" in host:
        if type(host["schema_version"]) is not int or host["schema_version"] != 1:
            raise ValueError("Unsupported host schema_version")
        if not _text(host.get("session_id")) or not _text(host.get("platform")) or not _text(host.get("evidence")):
            raise ValueError("Host schema 1 requires platform, session_id and current tool evidence")
    if host.get("platform") not in (None, platform):
        raise ValueError("Host evidence platform does not match the selected platform")
    evidence = host.get("evidence")
    observed = _text(evidence)
    agents = host.get("available_agents", [])
    if not isinstance(agents, list) or any(not _text(value) for value in agents):
        raise ValueError("available_agents must be a list of nonempty identifiers")
    parallel = host.get("max_parallel_agents")
    if parallel is not None and (type(parallel) is not int or parallel < 1):
        raise ValueError("Host max_parallel_agents must be a positive integer")
    result = {"platform": platform, "session_id": host.get("session_id"),
              "host_version": host.get("host_version"), "evidence": evidence.strip() if observed else None,
              "available_agents": list(dict.fromkeys(agents)) if observed else [],
              "max_parallel_agents": parallel if observed else None}
    for field in ("native_subagents", "accepts_role_instructions", "dynamic_agents", "role_registration",
                  "shared_workspace", "worktree", "parallel_writes", "results_errors"):
        value = host.get(field)
        result[field] = value if observed and type(value) is bool else None
    for field in ("generic_agent_id", "delegation_tool", "result_tool", "registration_tool"):
        value = host.get(field)
        result[field] = value.strip() if observed and _text(value) else None
    delivery = host.get("result_mode")
    if delivery not in (None, "inline", "tool"):
        raise ValueError("result_mode must be inline or tool")
    result["result_mode"] = (delivery or ("tool" if result["result_tool"] else None)) if observed else None
    constraints = host.get("permission_constraints")
    result["permission_constraints"] = (list(constraints) if observed and isinstance(constraints, list)
                                         and all(_text(item) for item in constraints) else None)
    result["warnings"] = ([] if observed else ["Runtime capabilities are unknown without current host tool evidence."])
    return result


def execution_route(platform, host=None, identifiers=(), role_instructions=False, kind="agent"):
    """Choose a transport without executing tools or asserting a role is registered."""
    cap = negotiate(platform, host)
    route = {"mode": "sequential_handoff", "agent_id": None,
             "delegation_tool": cap["delegation_tool"], "result_tool": cap["result_tool"],
             "result_mode": cap["result_mode"],
             "execution_verified": False}
    if cap["native_subagents"] is not True:
        route["reason"] = "Current session has no verified subagent capability"
        return route
    if (host or {}).get("schema_version") == 1 and (
            not cap["delegation_tool"] or not (cap["result_mode"] == "inline" or cap["result_tool"])):
        route["reason"] = "Current session must expose a delegation tool and a verified result delivery mechanism"
        return route
    matched = next((value for value in identifiers if value in cap["available_agents"]), None)
    if matched and kind != "skill":
        route.update(mode="native_role", agent_id=matched, reason="Role is listed by the current host")
    elif role_instructions and cap["accepts_role_instructions"] is True:
        if cap["generic_agent_id"] in cap["available_agents"]:
            route.update(mode="generic_subagent", agent_id=cap["generic_agent_id"],
                         reason="Use a real generic executor with the selected specialist instructions")
        elif cap["dynamic_agents"] is True and cap["delegation_tool"]:
            route.update(mode="dynamic_subagent", reason="Host can create a temporary role through its delegation tool")
        else:
            route["reason"] = "Role instruction transport has no verified generic or dynamic executor"
    else:
        route["reason"] = "No native role or verified instruction transport; retain explicit role handoff"
    return route


def adapter_contract(platform):
    """Packaging contracts are intentionally separate from session capability claims."""
    _platform(platform)
    from .host_installers import installer_for
    installer = installer_for(platform)
    mechanism = ("native-skill-directory" if installer else
                 "manual-import-package" if platform == "workbuddy" else "explicit-destination")
    return {"id": platform, "skill_installation": mechanism,
            "project_skill_path": installer.project_path if installer else None,
            "user_skill_path": installer.user_path if installer else None,
            "runtime_detection": "session-tools-required", "version_compatibility": "unverified",
            "execution_modes": ["native_role", "generic_subagent", "dynamic_subagent", "sequential_handoff"],
            "role_source": "msitarzewski/agency-agents",
            "registration": "Use the host's verified creation/registration tool; never infer an API or path"}


def inspect_host(platform, host=None, root=None):
    cap = negotiate(platform, host)
    result = {"adapter": adapter_contract(platform), "capabilities": cap,
              "verification": {stage: "unknown" for stage in STAGES},
              "registration": {"available": cap["role_registration"] is True and bool(cap["registration_tool"]),
                               "tool": cap["registration_tool"]},
              "execution": execution_route(platform, host, role_instructions=True)}
    if root is not None:
        from .storage import safe_path
        path = safe_path(root, ".agent-team/hosts/" + platform + ".json")
        if path.is_file():
            receipt = json.loads(path.read_text(encoding="utf-8"))
            _validate_saved_receipt(receipt, platform)
            result["last_verification"] = receipt
            result["last_verification_is_current_session"] = bool(
                cap["session_id"] and receipt.get("session_id") == cap["session_id"])
            # Persisted reports are historical observations, never tool inventory.
    return result


def record_verification(root, platform, receipt, host=None):
    """Persist a host-reported acceptance receipt; this does not run a smoke test."""
    from .storage import _atomic_text, project_lock, safe_path
    cap = negotiate(platform, host)
    if not isinstance(receipt, dict) or type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1:
        raise ValueError("Verification requires schema_version 1")
    if receipt.get("platform") != platform or not _text(receipt.get("session_id")):
        raise ValueError("Verification requires the selected platform and a session_id")
    if not cap["session_id"] or cap["session_id"] != receipt["session_id"] or not cap["evidence"]:
        raise ValueError("Verification requires matching current --host session evidence")
    stages = receipt.get("checks")
    if not isinstance(stages, dict) or not stages or set(stages) - set(STAGES):
        raise ValueError("Verification checks must name installation/discovery/registration/invocation/result stages")
    for stage, check in stages.items():
        if not isinstance(check, dict) or check.get("status") not in ("passed", "failed", "pending"):
            raise ValueError("Each verification check requires passed, failed or pending status")
        if check["status"] != "pending" and not _text(check.get("evidence")):
            raise ValueError("Verification outcomes require actual evidence")
        if stage in ("agent_invoked", "result_received") and check["status"] == "passed":
            if not _text(check.get("agent_id")):
                raise ValueError("Invocation and result verification require the actual returned agent_id")
    returned = stages.get("result_received", {})
    invoked = stages.get("agent_invoked", {})
    if returned.get("status") == "passed" and (
            invoked.get("status") != "passed" or returned["agent_id"] != invoked.get("agent_id")):
        raise ValueError("A received result must match a passed invocation in this receipt")
    saved = dict(receipt, host_version=cap["host_version"], recorded_at=datetime.now(timezone.utc).isoformat(), reporter="host",
                 runtime_capabilities_reusable=False)
    with project_lock(root):
        path = safe_path(root, ".agent-team/hosts/" + platform + ".json")
        _atomic_text(path, json.dumps(saved, ensure_ascii=False, indent=2) + "\n")
    return saved


def _validate_saved_receipt(receipt, platform):
    if (not isinstance(receipt, dict) or receipt.get('platform') != platform
            or type(receipt.get('schema_version')) is not int or receipt['schema_version'] != 1
            or not isinstance(receipt.get('checks'), dict)):
        raise ValueError('Invalid stored host verification; preserve the file and repair explicitly')
    for stage, check in receipt['checks'].items():
        if stage not in STAGES or not isinstance(check, dict) or check.get('status') not in ('passed', 'failed', 'pending'):
            raise ValueError('Invalid stored host verification; preserve the file and repair explicitly')


def verification_matrix(root):
    """Summarize saved host checks without promoting them to runtime evidence."""
    from .storage import safe_path
    rows = []
    for platform in PLATFORMS:
        path = safe_path(root, ".agent-team/hosts/" + platform + ".json")
        receipt = None
        if path.is_file():
            receipt = json.loads(path.read_text(encoding="utf-8"))
            _validate_saved_receipt(receipt, platform)
        checks = {stage: "unknown" for stage in STAGES}
        if receipt:
            for stage, check in receipt.get("checks", {}).items():
                checks[stage] = check["status"]
        rows.append({"platform": platform, "host_version": receipt.get("host_version") if receipt else None,
                     "recorded_at": receipt.get("recorded_at") if receipt else None,
                     "checks": checks, "source": "saved_receipt" if receipt else "no_receipt"})
    return {"verification_scope": "latest saved host receipts; not current-session capability evidence",
            "platforms": rows}
