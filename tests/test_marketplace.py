from pathlib import Path

import pytest
import yaml

from agent_team.adapters import PLATFORMS, capabilities, detect_platform, entry_path, entry_text, render_role
from agent_team.marketplace import build_catalog, generate_role, install_role, recommend_roles
from agent_team.storage import bootstrap, read_yaml, write_yaml

try:
    import tomllib
except ImportError:
    import tomli as tomllib


@pytest.fixture
def role():
    return generate_role("security-reviewer", "Security Reviewer", ["security", "review"], ["review report"])


@pytest.mark.parametrize("platform", PLATFORMS)
def test_capability_requires_explicit_evidence(platform):
    assert not capabilities(platform)["native_subagents"]
    assert not capabilities(platform, {"native_subagents": True})["native_subagents"]
    assert not capabilities(platform, {"native_subagents": "true", "evidence": "tool"})["native_subagents"]
    cap = capabilities(platform, {"native_subagents": True, "evidence": "runtime tool inventory",
                                  "available_agents": ["reviewer"], "max_parallel_agents": 99})
    assert cap["native_subagents"] and cap["max_parallel_agents"] == 3
    assert cap["available_agents"] == ["reviewer"]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_render_parseable_role(platform, role):
    role["prompt"] += '\nUnicode 中文 and "quoted" text\\path\n'
    result = render_role(role, platform)
    assert not Path(result["path"]).is_absolute()
    if platform == "codex":
        parsed = tomllib.loads(result["content"])
        assert parsed["developer_instructions"] == role["prompt"]
    else:
        frontmatter = result["content"].split("---", 2)[1]
        assert yaml.safe_load(frontmatter)["name"] == role["id"]
    assert entry_path(platform)


def test_detect_context_is_not_capability(tmp_path):
    (tmp_path / ".codex").mkdir()
    assert detect_platform(tmp_path, {}) == "codex"
    assert not capabilities("codex")["native_subagents"]


def test_catalog_four_states_and_no_forged_availability(tmp_path):
    bootstrap(tmp_path)
    source = tmp_path / "local"
    source.mkdir()
    (source / "auditor.md").write_text(
        "---\nname: Auditor\ncapabilities: [security]\nstatus: available\n---\nAudit security.")
    (source / "claude-only.md").write_text(
        "---\nname: Claude only\nplatforms: [claude-code]\n---\nReview.\n")
    host = {"native_subagents": True, "evidence": "host inventory", "available_agents": ["Host Reviewer"]}
    catalog = build_catalog(tmp_path, "codex", [source], host)
    by_id = {item["id"]: item for item in catalog}
    assert by_id["auditor"]["status"] == "installable"
    assert by_id["claude-only"]["status"] == "unavailable"
    assert by_id["host-reviewer"]["status"] == "available"
    assert by_id["test-engineer"]["status"] == "proposed"


def test_real_toml_and_bad_frontmatter(tmp_path):
    source = tmp_path / "local"
    source.mkdir()
    (source / "reviewer.toml").write_text('name = "Reviewer"\ndescription = "Review code"\ndeveloper_instructions = "Check correctness."\n')
    (source / "broken.md").write_text("---\nname: [broken\n---\nBad.")
    with pytest.warns(RuntimeWarning, match="Skipping invalid role"):
        roles = build_catalog(tmp_path, sources=[source])
    assert next(role for role in roles if role["id"] == "reviewer")["prompt"] == "Check correctness."


def test_local_scan_is_bounded_and_skips_symlink(tmp_path):
    source = tmp_path / "local"
    source.mkdir()
    nested = source / "one/two/three/four"
    nested.mkdir(parents=True)
    (nested / "hidden.md").write_text("Should not be discovered")
    external = tmp_path / "external"
    external.mkdir()
    (external / "outside.md").write_text("External instructions")
    (source / "link").symlink_to(external, target_is_directory=True)
    assert not {"hidden", "outside"} & {r["id"] for r in build_catalog(tmp_path, sources=[source])}


def test_preview_install_repeat_and_index(tmp_path, role):
    bootstrap(tmp_path, "codex")
    preview = install_role(tmp_path, role, "codex")
    assert preview["action"] == "preview" and not preview["installed"]
    assert not (tmp_path / preview["target"]).exists()
    result = install_role(tmp_path, role, "codex", approved=True)
    assert result["installed"] and result["status"] == "unavailable"
    assert install_role(tmp_path, role, "codex", approved=True)["action"] == "unchanged"
    members = read_yaml(tmp_path / ".agent-team/team.yaml")["team"]["members"]
    assert len([member for member in members if member["id"] == role["id"]]) == 1
    assert members[-1]["definition"] == result["path"]
    assert members[-1]["agent_id"] == role["id"]
    assert next(item for item in build_catalog(tmp_path, "codex", sources=[]) if item["id"] == role["id"])["status"] == "unavailable"
    changed = dict(role, prompt="Different instructions")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        install_role(tmp_path, changed, "codex", approved=True)


def test_install_availability_requires_host_verification(tmp_path, role):
    bootstrap(tmp_path)
    host = {"native_subagents": True, "evidence": "verified host role list", "available_agents": [role["id"]]}
    assert install_role(tmp_path, role, approved=True, host=host)["status"] == "available"
    assert install_role(tmp_path, role, approved=True)["status"] == "unavailable"


def test_host_inventory_enriches_from_project_profile(tmp_path, role):
    bootstrap(tmp_path)
    install_role(tmp_path, role, approved=True)
    host = {"native_subagents": True, "evidence": "verified runtime inventory", "available_agents": [role["id"]]}
    entry = next(item for item in build_catalog(tmp_path, sources=[], host=host) if item["id"] == role["id"])
    assert entry["status"] == "available"
    assert entry["capabilities"] == role["capabilities"] and entry["prompt"] == role["prompt"]
    assert entry["evidence"] == [host["evidence"]]


def test_incompatible_role_cannot_become_available_from_host(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "reviewer.md").write_text(
        "---\nname: Reviewer\nplatforms: [claude-code]\ncapabilities: [review]\n---\nReview code.")
    host = {"native_subagents": True, "evidence": "host", "available_agents": ["reviewer"]}
    entry = next(item for item in build_catalog(tmp_path, "codex", [source], host) if item["id"] == "reviewer")
    assert entry["status"] == "unavailable"
    assert recommend_roles([entry], ["review"]) == []


def test_unverified_installed_role_can_be_recommended_for_sequential_use(tmp_path, role):
    bootstrap(tmp_path)
    install_role(tmp_path, role, approved=True)
    entry = next(item for item in build_catalog(tmp_path, sources=[]) if item["id"] == role["id"])
    result = recommend_roles([entry], ["security"])
    assert result[0]["status"] == "unavailable" and result[0]["warnings"]


def test_registry_failure_removes_new_role_file(tmp_path, role, monkeypatch):
    import agent_team.storage as storage
    bootstrap(tmp_path)
    previous = (tmp_path / ".agent-team/team.yaml").read_bytes()
    def fail_write(*args):
        raise OSError("simulated disk failure")
    monkeypatch.setattr(storage, "write_yaml", fail_write)
    with pytest.raises(OSError, match="disk failure"):
        install_role(tmp_path, role, approved=True)
    assert not (tmp_path / render_role(role, "generic")["path"]).exists()
    assert (tmp_path / ".agent-team/team.yaml").read_bytes() == previous


def test_corrupt_registry_is_preserved(tmp_path, role):
    bootstrap(tmp_path)
    registry = tmp_path / ".agent-team/team.yaml"
    registry.write_text("malformed: [")
    with pytest.raises(ValueError):
        install_role(tmp_path, role, approved=True)
    assert registry.read_text() == "malformed: ["
    assert not (tmp_path / render_role(role, "generic")["path"]).exists()


def test_install_rejects_escaping_symlink(tmp_path, role):
    bootstrap(tmp_path)
    external = tmp_path.parent / (tmp_path.name + "-outside")
    external.mkdir()
    (tmp_path / ".codex").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        install_role(tmp_path, role, "codex", approved=True)
    assert not list(external.iterdir())


def test_recommend_top_three_and_weights(tmp_path):
    catalog = build_catalog(tmp_path, sources=[])
    results = recommend_roles(catalog, ["security", "review"], ["review findings"])
    assert results[0]["id"] == "code-reviewer"
    assert len(results) <= 3 and results[0]["match_evidence"]["capabilities"]
    # C=1, D=1, P=1, T=.7 for a built-in definition.
    assert results[0]["score"] == 95.5
    assert all(item["match_evidence"]["capabilities"] for item in results)
    assert recommend_roles(catalog, ["no-such-capability"]) == []
    without_outputs = recommend_roles(catalog, ["security", "review"])
    assert without_outputs[0]["score"] == 94.0
    assert "divide by 0.75" in without_outputs[0]["match_evidence"]["normalization"]


def test_profile_cannot_self_assert_trust(tmp_path):
    source = tmp_path / "external"
    source.mkdir()
    (source / "reviewer.md").write_text(
        "---\nname: Reviewer\ncapabilities: [review]\nsource: host\n"
        "provenance: {channel: host, definition_trust: 1}\nstatus: available\n---\nReview code.")
    entry = next(item for item in build_catalog(tmp_path, sources=[{"path": source, "kind": "host"}])
                 if item["id"] == "reviewer")
    assert entry["status"] == "installable"
    assert entry["provenance"] == {"channel": "local", "definition_trust": .65}


def test_invalid_role_id_rejected(role):
    with pytest.raises(ValueError, match="Role id"):
        render_role(dict(role, id="../escape"), "generic")


@pytest.mark.parametrize("alias", ["api-native-42", "API Platform Engineer", "API Specialist", "api-team-role"])
def test_host_member_aliases_merge_without_placeholder(tmp_path, alias):
    config = bootstrap(tmp_path)
    config["team"]["members"].append({"id": "api-team-role", "name": "API Specialist",
                                       "role": "API Platform Engineer", "agent_id": "api-native-42",
                                       "capabilities": ["api"], "deliverables": ["API contract"]})
    write_yaml(tmp_path / ".agent-team/team.yaml", config)
    host = {"native_subagents": True, "evidence": "runtime inventory", "available_agents": [alias]}
    catalog = build_catalog(tmp_path, sources=[], host=host)
    entry = next(item for item in catalog if item["id"] == "api-team-role")
    assert entry["status"] == "available"
    assert entry["capabilities"] == ["api"]
    assert entry["deliverables"] == ["API contract"]
    assert not any(item["source"] == "host" and item["name"] == alias for item in catalog)


def test_approved_profile_refreshes_existing_member_and_preserves_scope(tmp_path):
    config = bootstrap(tmp_path)
    member = config["team"]["members"][0]
    member.update(write_scope=["api/"], custom_setting="preserve", prompt="Old instructions")
    write_yaml(tmp_path / ".agent-team/team.yaml", config)
    role = generate_role("implementer", "API Specialist", ["api"], ["API contract"])
    install_role(tmp_path, role, approved=True)
    updated = read_yaml(tmp_path / ".agent-team/team.yaml")["team"]["members"][0]
    assert updated["name"] == updated["role"] == "API Specialist"
    assert updated["capabilities"] == ["api"] and updated["deliverables"] == ["API contract"]
    assert updated["agent_id"] == "implementer" and updated["prompt"] == role["prompt"]
    assert updated["write_scope"] == ["api/"] and updated["custom_setting"] == "preserve"
    entry = next(item for item in build_catalog(tmp_path, sources=[]) if item["id"] == "implementer")
    assert entry["prompt"] == role["prompt"] and entry["capabilities"] == ["api"]
    assert recommend_roles([entry], ["api"])[0]["id"] == "implementer"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_entry_routes_complex_tasks_to_bundled_guide(platform):
    text = entry_text(platform)
    assert "Default to one agent" in text and "without loading the full team" in text
    assert "agent-team-runtime Skill" in text and "SKILL.md" in text
    assert "Reuse the existing" in text and "do not recreate" in text
    assert "existing user authorization and host restrictions" in text


def test_installed_platform_restriction_survives_native_rendering(tmp_path, role):
    bootstrap(tmp_path, "claude-code")
    role["platforms"] = ["claude-code"]
    install_role(tmp_path, role, "claude-code", approved=True)
    member = read_yaml(tmp_path / ".agent-team/team.yaml")["team"]["members"][-1]
    assert member["platforms"] == ["claude-code"]
    host = {"native_subagents": True, "evidence": "runtime inventory", "available_agents": [role["id"]]}
    entry = next(item for item in build_catalog(tmp_path, "codex", [], host) if item["id"] == role["id"])
    assert entry["platforms"] == ["claude-code"]
    assert entry["status"] == "unavailable" and not entry["platform_compatible"]
    assert recommend_roles([entry], ["security"]) == []


def test_explicit_definition_can_narrow_registered_platforms(tmp_path):
    config = bootstrap(tmp_path)
    path = tmp_path / "narrow.md"
    path.write_text("---\nname: Narrow\nplatforms: [claude-code]\n---\nReview code.")
    config["team"]["members"].append({"id": "narrow", "role": "Narrow", "definition": "narrow.md"})
    write_yaml(tmp_path / ".agent-team/team.yaml", config)
    entry = next(item for item in build_catalog(tmp_path, "codex", []) if item["id"] == "narrow")
    assert entry["platforms"] == ["claude-code"] and not entry["platform_compatible"]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_isolation_and_result_capabilities_are_unknown_without_evidence(platform):
    fields = ("shared_workspace", "worktree", "parallel_writes", "permission_constraints", "results_errors")
    assert all(capabilities(platform)[key] is None for key in fields)
    unsupported = {"shared_workspace": True, "worktree": True, "parallel_writes": True,
                   "permission_constraints": ["project only"], "results_errors": True}
    assert all(capabilities(platform, unsupported)[key] is None for key in fields)
    declared = capabilities(platform, dict(unsupported, evidence="host execution contract", native_subagents=False))
    assert declared["shared_workspace"] is True and declared["worktree"] is True
    assert declared["parallel_writes"] is True and declared["results_errors"] is True
    assert declared["permission_constraints"] == ["project only"]
    assert not declared["native_subagents"]


def test_catalog_rejects_project_team_directory_escaping_symlink(tmp_path):
    project, external = tmp_path / "project", tmp_path / "external"
    project.mkdir()
    external.mkdir()
    # Invalid content demonstrates containment is checked before parsing it.
    (external / "team.yaml").write_text("external: [invalid")
    (project / ".agent-team").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="Path escapes project"):
        build_catalog(project, sources=[])


def test_catalog_rejects_implicit_role_directory_escaping_symlink(tmp_path):
    project, external = tmp_path / "project", tmp_path / "external"
    project.mkdir()
    external.mkdir()
    (project / ".codex").mkdir()
    (project / ".codex/agents").symlink_to(external, target_is_directory=True)
    (external / "external-reviewer.md").write_text(
        "---\nname: External Reviewer\ncapabilities: [review]\n---\nExternal instructions.")
    with pytest.raises(ValueError, match="Path escapes project"):
        build_catalog(project, "codex", [])
    # An explicitly selected source may intentionally point outside the project.
    catalog = build_catalog(project, "generic", [project / ".codex/agents"])
    entry = next(item for item in catalog if item["id"] == "external-reviewer")
    assert entry["prompt"] == "External instructions." and entry["source"] == "local"
