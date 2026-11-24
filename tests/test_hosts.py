"""Cross-host negotiation tests exercise real planners, bootstrap and receipts."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from agent_team.cli import main
from agent_team.hosts import (adapter_contract, detect_host, execution_route, inspect_host,
                              negotiate, record_verification, verification_matrix)
from agent_team.platforms import PLATFORMS
from agent_team.runtime import plan_task
from agent_team.storage import bootstrap, read_yaml, write_yaml


def observation(platform="workbuddy", **values):
    return dict({"schema_version": 1, "platform": platform, "session_id": "current-session",
                 "host_version": "test-version", "evidence": "Current session exposes spawn and wait tools",
                 "native_subagents": True, "available_agents": ["worker"], "generic_agent_id": "worker",
                 "accepts_role_instructions": True, "delegation_tool": "spawn", "result_tool": "wait",
                 "max_parallel_agents": 4, "parallel_writes": True}, **values)


def prepared(root, platform="codex"):
    team = bootstrap(root, platform)
    team["team"]["members"][0]["prompt"] = "Specialist instructions: report actual validation."
    team["team"]["members"][0]["agent_ids"] = {"codex": "codex-specialist", "claude-code": "claude-specialist"}
    write_yaml(root / ".agent-team/team.yaml", team)
    return team


def spec(count=2):
    return {"title": "Independent specialist tasks", "scores": dict.fromkeys(
        ("independence", "complexity", "specialization", "parallel_benefit"), 90),
        "work_items": [{"id": "task-" + str(i), "role": "implementer", "goal": "Check component",
                        "deliverables": ["checked component"], "write_scope": ["component-" + str(i)]}
                       for i in range(count)]}


@pytest.mark.parametrize("platform", PLATFORMS)
def test_every_host_can_use_a_generic_executor_without_native_role_registration(platform):
    host = observation(platform)
    route = execution_route(platform, host, ("agency-specialist",), True, kind="skill")
    assert route["mode"] == "generic_subagent" and route["agent_id"] == "worker"
    assert route["delegation_tool"] == "spawn" and not route["execution_verified"]
    # Platform names never prove a runtime or registration capability.
    assert negotiate(platform)["native_subagents"] is None
    assert inspect_host(platform)["verification"]["agent_invoked"] == "unknown"


def test_routes_need_real_executor_and_instruction_transport():
    host = observation("pi", available_agents=["registered", "worker"])
    assert execution_route("pi", host, ["registered"], True)["mode"] == "native_role"
    assert execution_route("pi", host, ["registered"], True, "skill")["mode"] == "generic_subagent"
    host["generic_agent_id"] = "nonexistent"
    assert execution_route("pi", host, [], True)["mode"] == "sequential_handoff"
    host["dynamic_agents"] = True
    route = execution_route("pi", host, [], True)
    assert route["mode"] == "dynamic_subagent" and route["agent_id"] is None
    host["accepts_role_instructions"] = False
    assert execution_route("pi", host, [], True)["mode"] == "sequential_handoff"
    host["evidence"] = ""
    with pytest.raises(ValueError, match="current tool evidence"):
        execution_route("pi", host, ["registered"], True)
    host.pop("schema_version")
    assert execution_route("pi", host, ["registered"], True)["mode"] == "sequential_handoff"


@pytest.mark.parametrize("native", [False, True])
def test_schema_one_requires_actual_dispatch_and_result_transport(native):
    host = observation(available_agents=["worker", "registered"])
    aliases = ["registered"] if native else []
    for field in ("delegation_tool", "result_tool"):
        missing = dict(host)
        missing.pop(field)
        assert execution_route("workbuddy", missing, aliases, True)["mode"] == "sequential_handoff"
    host.pop("result_tool")
    host["result_mode"] = "inline"
    result = execution_route("workbuddy", host, aliases, True)
    assert result["mode"] == ("native_role" if native else "generic_subagent")
    assert result["result_mode"] == "inline" and result["result_tool"] is None


def test_detect_conflicts_and_ignores_project_folders_during_installation(tmp_path):
    (tmp_path / ".codex").mkdir()
    assert detect_host(tmp_path, {}, require_runtime=True) == "generic"
    assert detect_host(tmp_path, {}, observation()) == "workbuddy"
    (tmp_path / ".claude").mkdir()
    assert detect_host(tmp_path, {}) == "generic"
    with pytest.raises(ValueError, match="Conflicting"):
        detect_host(tmp_path, {"CODEX_THREAD_ID": "a", "CLAUDE_CODE_ENTRYPOINT": "b"})
    # CODEX_HOME is a configuration location, not proof that Codex is active.
    assert detect_host(tmp_path, {"CODEX_HOME": "/tmp/config", "CLAUDE_CODE_ENTRYPOINT": "b"}) == "claude-code"


@pytest.mark.parametrize("host", [[], {"schema_version": True}, {"schema_version": 2},
                                 {"schema_version": 1, "platform": "codex"},
                                 {"max_parallel_agents": False}, {"available_agents": "worker"}])
def test_invalid_observations_fail_without_pretending_support(host):
    with pytest.raises(ValueError):
        negotiate("codex", host)


def test_host_platform_mismatch_is_rejected():
    with pytest.raises(ValueError, match="does not match"):
        negotiate("codex", observation())


def test_runtime_platform_overrides_team_creation_platform(tmp_path):
    prepared(tmp_path, "codex")
    host = observation("claude-code", available_agents=["claude-specialist", "worker"])
    plan = plan_task(tmp_path, spec(), host, platform="claude-code")["execution"]
    assert plan["platform"] == "claude-code" and plan["strategy"] == "native_subagents"
    assert {agent["agent_id"] for agent in plan["agents"]} == {"claude-specialist"}
    assert read_yaml(tmp_path / ".agent-team/team.yaml")["platform"] == "codex"
    # An explicit enable/repair adds the active host's entry without recreating a team.
    team_id = read_yaml(tmp_path / ".agent-team/team.yaml")["team"]["id"]
    bootstrap(tmp_path, "claude-code")
    assert (tmp_path / "CLAUDE.md").is_file()
    assert read_yaml(tmp_path / ".agent-team/team.yaml")["team"]["id"] == team_id


def test_skill_installation_does_not_block_generic_subagent_execution(tmp_path):
    team = prepared(tmp_path, "workbuddy")
    member = team["team"]["members"][0]
    member.update(platforms=["workbuddy"], agent_kinds={"workbuddy": "skill"})
    write_yaml(tmp_path / ".agent-team/team.yaml", team)
    plan = plan_task(tmp_path, spec(), observation())["execution"]
    assert plan["strategy"] == "host_subagents"
    assert {agent["member_id"] for agent in plan["agents"]} == {"implementer"}
    assert {agent["agent_id"] for agent in plan["agents"]} == {"worker"}
    assert all("Specialist instructions" in h["prompt"] for h in plan["handoffs"])
    assert all(h["transport"]["mode"] == "generic_subagent" for h in plan["handoffs"])
    assert plan["batches"] == [["task-0", "task-1"]] and not plan["execution_verified"]


def test_dynamic_and_mixed_transports_are_plannable_without_fake_executor_ids(tmp_path):
    prepared(tmp_path, "workbuddy")
    host = observation(available_agents=[], generic_agent_id=None, dynamic_agents=True)
    dynamic = plan_task(tmp_path, spec(), host)["execution"]
    assert dynamic["strategy"] == "host_subagents"
    assert all(agent["agent_id"] is None and agent["execution_mode"] == "dynamic_subagent"
               for agent in dynamic["agents"])
    team = read_yaml(tmp_path / ".agent-team/team.yaml")
    team["team"]["members"].append({"id": "other", "role": "Other", "prompt": "Review the changes"})
    write_yaml(tmp_path / ".agent-team/team.yaml", team)
    mixed_spec = spec()
    mixed_spec["work_items"][1]["role"] = "other"
    host = observation(available_agents=["implementer"], accepts_role_instructions=False)
    mixed = plan_task(tmp_path, mixed_spec, host)["execution"]
    assert mixed["strategy"] == "mixed_handoffs"
    assert [agent["execution_mode"] for agent in mixed["agents"]] == ["native_role", "sequential_handoff"]
    assert mixed["batches"] == [["task-0"], ["task-1"]]


def test_configured_host_concurrency_and_unknown_write_permissions(tmp_path):
    prepared(tmp_path, "workbuddy")
    write_yaml(tmp_path / ".agent-team/orchestration.yaml", {"max_parallel_agents": 6})
    host = observation(max_parallel_agents=4)
    execution = plan_task(tmp_path, spec(6), host)["execution"]
    assert execution["max_parallel_agents"] == 4
    assert list(map(len, execution["batches"])) == [4, 2]
    for field in ("max_parallel_agents", "parallel_writes"):
        reduced = dict(host)
        reduced.pop(field)
        assert all(len(batch) == 1 for batch in plan_task(tmp_path, spec(), reduced)["execution"]["batches"])


@pytest.mark.parametrize("worktree", [False, True])
def test_known_isolation_requires_project_transfer_before_delegation(tmp_path, worktree):
    prepared(tmp_path, "workbuddy")
    plan = plan_task(tmp_path, spec(), observation(shared_workspace=False, worktree=worktree))["execution"]
    assert plan["strategy"] == "sequential_handoffs"
    assert all(agent["agent_id"] is None for agent in plan["agents"])
    assert all("transfer" in handoff["transport"]["reason"] for handoff in plan["handoffs"])
    assert not any("You share the workspace" in handoff["prompt"] for handoff in plan["handoffs"])


def receipt():
    return {"schema_version": 1, "platform": "workbuddy", "session_id": "current-session", "checks": {
        "files_installed": {"status": "passed", "evidence": "Host import tool returned a verified skill path"},
        "agent_invoked": {"status": "passed", "evidence": "spawn returned child-42", "agent_id": "child-42"},
        "result_received": {"status": "passed", "evidence": "wait returned the expected read-only smoke response", "agent_id": "child-42"}}}


def test_verification_is_separate_from_current_session_capabilities(tmp_path):
    saved = record_verification(tmp_path, "workbuddy", receipt(), observation())
    assert not saved["runtime_capabilities_reusable"]
    assert (tmp_path / ".agent-team/hosts/workbuddy.json").is_file()
    assert inspect_host("workbuddy", observation(), tmp_path)["last_verification_is_current_session"]
    restarted = inspect_host("workbuddy", {"session_id": "another-session"}, tmp_path)
    assert not restarted["last_verification_is_current_session"]
    assert restarted["capabilities"]["native_subagents"] is None
    assert restarted["verification"]["agent_invoked"] == "unknown"
    assert restarted["execution"]["mode"] == "sequential_handoff"


def test_verification_matrix_shows_saved_receipts_and_unknowns(tmp_path):
    record_verification(tmp_path, "workbuddy", receipt(), observation())
    matrix = verification_matrix(tmp_path)
    assert matrix["verification_scope"].startswith("latest saved host receipts")
    workbuddy = next(row for row in matrix["platforms"] if row["platform"] == "workbuddy")
    codex = next(row for row in matrix["platforms"] if row["platform"] == "codex")
    assert workbuddy["checks"]["files_installed"] == "passed"
    assert workbuddy["checks"]["agent_invoked"] == "passed"
    assert workbuddy["host_version"] == "test-version"
    assert codex["checks"]["agent_invoked"] == "unknown"
    assert codex["source"] == "no_receipt"


def test_matrix_keeps_invalid_saved_checks_for_explicit_repair(tmp_path):
    directory = tmp_path / '.agent-team/hosts'
    directory.mkdir(parents=True)
    path = directory / 'codex.json'
    original = json.dumps({'schema_version': 1, 'platform': 'codex', 'checks': []})
    path.write_text(original, encoding='utf-8')
    with pytest.raises(ValueError, match='preserve'):
        verification_matrix(tmp_path)
    assert path.read_text(encoding='utf-8') == original


@pytest.mark.parametrize("failure", ["session", "result_id", "no_invocation", "no_evidence"])
def test_false_or_mismatched_acceptance_is_not_saved(tmp_path, failure):
    data = receipt()
    if failure == "session": data["session_id"] = "old-session"
    elif failure == "result_id": data["checks"]["result_received"]["agent_id"] = "another-child"
    elif failure == "no_invocation": data["checks"].pop("agent_invoked")
    else: data["checks"]["agent_invoked"].pop("evidence")
    with pytest.raises(ValueError):
        record_verification(tmp_path, "workbuddy", data, observation())
    assert not (tmp_path / ".agent-team/hosts/workbuddy.json").exists()


def test_bootstrap_auto_detection_uses_stdlib_even_without_site_packages(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for platform, marker, relative in (("codex", "CODEX_THREAD_ID", ".agents/skills"),
                                        ("claude-code", "CLAUDE_CODE_ENTRYPOINT", ".claude/skills")):
        env = {key: value for key, value in os.environ.items()
               if key not in ("CODEX_THREAD_ID", "CLAUDE_CODE_ENTRYPOINT", "AGENT_TEAM_PLATFORM", "CURSOR_AGENT", "GEMINI_CLI")}
        env[marker] = "active"
        result = subprocess.run([sys.executable, "-S", str(root / "install.py"), "--project", str(tmp_path)],
                                env=env, text=True, capture_output=True, timeout=15)
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["platform"] == platform and relative in data["path"]
        assert not (tmp_path / relative).exists()


def test_workbuddy_install_negotiates_tools_without_claiming_import_or_invocation(tmp_path):
    from agent_team.installer import main as install
    host_path = tmp_path / "host.json"
    host_path.write_text(json.dumps(observation()))
    with contextlib.redirect_stdout(io.StringIO()) as out:
        assert install(["--project", str(tmp_path), "--host", str(host_path), "--approve"]) == 0
    result = json.loads(out.getvalue())
    assert result["platform"] == "workbuddy" and Path(result["path"]).is_file()
    assert result["status"] == "prepared_for_import"
    assert result["host"]["execution"]["mode"] == "generic_subagent"
    assert result["host"]["verification"]["agent_invoked"] == "unknown"
    assert result["host"]["verification"]["files_installed"] != "passed"


def test_host_cli_reads_session_evidence_and_records_only_actual_receipt(tmp_path):
    host_path = tmp_path / "host.json"
    host_path.write_text(json.dumps(observation()))
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt()))
    prefix = ["--project", str(tmp_path), "--host", str(host_path)]
    for command in (["host", "inspect"], ["host", "verify", str(receipt_path)]):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            assert main(prefix + command) == 0
        data = json.loads(output.getvalue())
        if command[-1] == "inspect":
            assert data["adapter"]["id"] == "workbuddy"
            assert data["execution"]["mode"] == "generic_subagent"
        else:
            assert data["checks"]["result_received"]["agent_id"] == "child-42"
    assert not (tmp_path / ".agent-team/team.yaml").exists()


def test_adapter_contract_does_not_conflate_packaging_with_native_support():
    contract = adapter_contract("workbuddy")
    assert contract["skill_installation"] == "manual-import-package"
    assert contract["runtime_detection"] == "session-tools-required"
    assert contract["version_compatibility"] == "unverified"
