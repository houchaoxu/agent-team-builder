"""Pinned upstream artifacts and the approval boundary are verified separately."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest
import yaml

from agent_team import agency, agency_install as bridge
from agent_team.cli import main
from agent_team.marketplace import build_catalog, tomllib
from agent_team.runtime import plan_task
from agent_team.storage import bootstrap, read_yaml


REVISION = "8ae6164602c95ca78828b148b9052460ee426885"
ROLE_ONE = "agency-testing-bridge-one"
ROLE_TWO = "agency-testing-bridge-two"
UNIX_COMMANDS = ("bash", "perl", "awk", "sed", "find", "mktemp", "cp", "sort", "grep", "tr", "wc")
real_upstream = pytest.mark.skipif(
    os.name == "nt" or any(shutil.which(command) is None for command in UNIX_COMMANDS),
    reason="Actual upstream shell integration needs a usable Bash/Unix environment",
)


@pytest.fixture
def library(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    documents, cards = {}, []
    for suffix, name, marker in (("one", "Bridge One", "ONLY_ROLE_ONE"),
                                 ("two", "Bridge Two", "ONLY_ROLE_TWO")):
        relative = "testing/testing-bridge-%s.md" % suffix
        body = ("---\nname: %s\ndescription: Review implementation with clear evidence\n"
                "color: blue\n---\n\n# %s\n\n%s\n" % (name, name, marker)).encode("utf-8")
        documents[relative] = body
        cards.append({"id": "agency-testing-bridge-" + suffix, "name": name,
                      "description": "Review implementation with clear evidence",
                      "capabilities": ["review"], "deliverables": ["review report"],
                      "path": relative, "sha256": hashlib.sha256(body).hexdigest()})
    index = {"schema_version": 1, "repository": agency.REPOSITORY,
             "revision": REVISION, "license": "MIT", "roles": cards}
    monkeypatch.setattr(agency, "load_index", lambda: copy.deepcopy(index))
    downloads = []

    def download(url):
        relative = url.split("/" + REVISION + "/", 1)[1]
        downloads.append(relative)
        return documents[relative]

    monkeypatch.setattr(agency, "_download", download)
    project = tmp_path / "project"
    project.mkdir()
    bootstrap(project)
    return {"project": project, "home": home, "downloads": downloads, "index": index}


@pytest.fixture
def staged_codex(monkeypatch):
    data = b'name = "Bridge One"\ndescription = "Review"\ndeveloper_instructions = "ONLY_ROLE_ONE"\n'
    monkeypatch.setattr(bridge, "_stage", lambda *args: {"bridge-one.toml": data})
    return data


def test_tool_contract_has_explicit_scope_and_plugin_limits(library):
    result = bridge.supported_tools()
    tools = {tool["id"]: tool for tool in result["tools"]}
    assert len(tools) == 20 and result["revision"] == REVISION
    assert {key for key, tool in tools.items() if tool["installation_supported"]} == set(bridge.DESTINATIONS)
    assert not tools["hermes"]["installation_supported"]
    assert tools["hermes"]["kind"] == "plugin"
    for key in ("kimi", "osaurus", "openclaw"):
        assert tools[key]["scopes"] == ["user"]
    for tool in tools.values():
        assert tool["native_available"] is None
        if tool["installer"] != "agency-upstream":
            continue
        for scope in tool["scopes"]:
            assert tool["upstream_scope"][scope] is True


@real_upstream
@pytest.mark.parametrize("tool", sorted(set(bridge.DESTINATIONS) - bridge.SKILL_TARGETS))
def test_real_upstream_selected_role_preview_approval_and_repeat(library, tool):
    root = library["project"]
    scope = "project" if "project" in bridge.DESTINATIONS[tool] else "user"
    original_registry = (root / ".agent-team/team.yaml").read_bytes()
    preview = bridge.install_agency_role(root, ROLE_ONE, tool, scope=scope)
    assert preview["action"] == "preview" and not preview["installed"]
    assert preview["confirmation"]["requires_user_response"]
    assert preview["confirmation"]["default_selection"] is None
    assert all(not Path(path).exists() for path in preview["targets"])
    assert not (root / preview["path"]).exists()
    assert (root / ".agent-team/team.yaml").read_bytes() == original_registry
    assert not preview["native_available"] and preview["status"] != "available"
    assert library["downloads"] == ["testing/testing-bridge-one.md"]

    result = bridge.install_agency_role(root, ROLE_ONE, tool, scope=scope, approved=True, offline=True)
    assert result["installed"] and result["installer"]["tool"] == tool
    assert result["installer"]["backend"] == "agency-upstream"
    assert not result["native_available"] and not result["activation"]["executed"]
    contents = [Path(entry["path"]).read_text(encoding="utf-8") for entry in result["files"]]
    assert any("ONLY_ROLE_ONE" in content for content in contents)
    assert all("ONLY_ROLE_TWO" not in content for content in contents)
    assert all("agent-team-agency-" not in content for content in contents)
    for target in result["targets"]:
        path = Path(target)
        assert path.is_file()
        content = path.read_text(encoding="utf-8")
        if path.suffix == ".toml":
            assert tomllib.loads(content)
        elif path.name == "agent.yaml":
            data = yaml.safe_load(content)
            assert data and (path.parent / "system.md").is_file()
        elif content.startswith("---\n"):
            assert isinstance(yaml.safe_load(content.split("---", 2)[1]), dict)
    members = read_yaml(root / ".agent-team/team.yaml")["team"]["members"]
    installed = [member for member in members if member["id"] == ROLE_ONE]
    assert len(installed) == 1 and installed[0]["agent_ids"][tool] == result["agent_id"]
    assert not any(member["id"] == ROLE_TWO for member in members)
    assert bridge.install_agency_role(root, ROLE_ONE, tool, scope=scope, approved=True, offline=True)["action"] == "unchanged"
    if tool == "openclaw":
        assert result["installer"]["mechanism"] == "converter-only"
        assert result["activation"]["state"] == "registration_required"
        assert {Path(path).name for path in result["targets"]} == {"SOUL.md", "AGENTS.md", "IDENTITY.md"}
    if tool == "vibe":
        assert {Path(path).suffix for path in result["targets"]} == {".md", ".toml"}


@real_upstream
@pytest.mark.parametrize("tool,filename", [("aider", "CONVENTIONS.md"), ("windsurf", ".windsurfrules")])
def test_combined_roster_keeps_previous_role_and_persistent_sources(library, tool, filename):
    root = library["project"]
    bridge.install_agency_role(root, ROLE_ONE, tool, approved=True)
    preview = bridge.install_agency_role(root, ROLE_TWO, tool)
    assert any(entry["action"] == "update" for entry in preview["files"] if entry["relative"] == filename)
    bridge.install_agency_role(root, ROLE_TWO, tool, approved=True)
    content = (root / filename).read_text(encoding="utf-8")
    assert "Bridge One" in content and "Bridge Two" in content
    if tool == "aider":
        for suffix in ("one", "two"):
            relative = ".agent-team/agency-sources/%s/testing/testing-bridge-%s.md" % (REVISION, suffix)
            assert relative in content and (root / relative).is_file()
    else:
        assert "ONLY_ROLE_ONE" in content and "ONLY_ROLE_TWO" in content
    (root / filename).write_text(content + "\nUser edit\n", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        bridge.install_agency_role(root, ROLE_TWO, tool, approved=True)
    assert (root / filename).read_text(encoding="utf-8").endswith("User edit\n")


@pytest.mark.parametrize("tool,scope", [("kimi", "project"), ("osaurus", "project"),
                                       ("openclaw", "project"), ("cursor", "user"),
                                       ("aider", "user"), ("windsurf", "user")])
def test_unsupported_scope_never_silently_changes_scope(library, monkeypatch, tool, scope):
    monkeypatch.setattr(bridge, "_stage", lambda *args: pytest.fail("Must not run installer"))
    with pytest.raises(ValueError, match="does not support"):
        bridge.install_agency_role(library["project"], ROLE_ONE, tool, scope=scope, approved=True)
    assert library["downloads"] == []
    assert not any(library["home"].iterdir())


def test_hermes_plugin_not_misrepresented_as_role_installation(library, monkeypatch):
    monkeypatch.setattr(bridge, "_stage", lambda *args: pytest.fail("Must not execute plugin installer"))
    with pytest.raises(ValueError, match="router plugin"):
        bridge.install_agency_role(library["project"], ROLE_ONE, "hermes", scope="user", approved=True)
    assert library["downloads"] == []


def test_missing_bash_reports_requirement_without_native_writes(library, monkeypatch):
    monkeypatch.setattr(bridge.shutil, "which", lambda command: None)
    with pytest.raises(ValueError, match="requires Bash"):
        bridge.install_agency_role(library["project"], ROLE_ONE, "codex", approved=True)
    assert not (library["project"] / ".codex").exists()


def test_conflict_preserves_existing_file_and_registry(library, staged_codex):
    root = library["project"]
    target = root / ".codex/agents/bridge-one.toml"
    target.parent.mkdir(parents=True)
    target.write_text("Personal definition", encoding="utf-8")
    registry = root / ".agent-team/team.yaml"
    original = registry.read_bytes()
    with pytest.raises(ValueError, match="refusing to overwrite"):
        bridge.install_agency_role(root, ROLE_ONE, "codex", approved=True)
    assert target.read_text() == "Personal definition" and registry.read_bytes() == original
    assert not (root / ".agent-team/roles" / (ROLE_ONE + ".md")).exists()


def test_registry_write_failure_rolls_back_all_new_files(library, staged_codex, monkeypatch):
    root = library["project"]
    preview = bridge.install_agency_role(root, ROLE_ONE, "codex")
    original = (root / ".agent-team/team.yaml").read_bytes()

    def fail_write(*args):
        raise OSError("simulated registry failure")

    monkeypatch.setattr(bridge, "write_yaml", fail_write)
    with pytest.raises(OSError, match="simulated registry failure"):
        bridge.install_agency_role(root, ROLE_ONE, "codex", approved=True)
    assert all(not Path(entry["path"]).exists() for entry in preview["files"])
    assert (root / ".agent-team/team.yaml").read_bytes() == original


def test_availability_requires_explicit_current_host_inventory(library, staged_codex):
    root = library["project"]
    forged = {"native_subagents": True, "available_agents": ["Bridge One"]}
    assert not bridge.install_agency_role(root, ROLE_ONE, "codex", host=forged)["native_available"]
    real = dict(forged, evidence="Current host tool lists Bridge One")
    assert bridge.install_agency_role(root, ROLE_ONE, "codex", host=real)["native_available"]


def test_registry_changed_during_staging_prevents_promotion(library, staged_codex, monkeypatch):
    root = library["project"]
    registry = root / ".agent-team/team.yaml"

    def stage(*args):
        registry.write_bytes(registry.read_bytes() + b"\n# concurrent change\n")
        return {"bridge-one.toml": staged_codex}

    monkeypatch.setattr(bridge, "_stage", stage)
    with pytest.raises(ValueError, match="registry changed"):
        bridge.install_agency_role(root, ROLE_ONE, "codex", approved=True)
    assert registry.read_text().endswith("# concurrent change\n")
    assert not (root / ".codex").exists()


def test_symlink_destination_never_writes_outside_scope(library, staged_codex):
    root = library["project"]
    outside = root.parent / "external"
    outside.mkdir()
    try:
        (root / ".codex").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation requires permissions on this platform")
    with pytest.raises(ValueError, match="escapes project|symlink"):
        bridge.install_agency_role(root, ROLE_ONE, "codex", approved=True)
    assert not any(outside.iterdir())


def test_cli_routes_agency_scope_and_builtin_without_shell(library, staged_codex, capsys, monkeypatch):
    root = library["project"]
    assert main(["--project", str(root), "--platform", "codex", "role", "install", "--agency", ROLE_ONE]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["installer"]["backend"] == "agency-upstream" and not preview["installed"]
    assert main(["--project", str(root), "--platform", "codex", "role", "install", "--agency", ROLE_ONE,
                 "--scope", "user", "--approve"]) == 0
    installed = json.loads(capsys.readouterr().out)
    assert installed["installed"] and installed["installer"]["scope"] == "user"
    assert (library["home"] / ".codex/agents/bridge-one.toml").is_file()
    assert not (root / ".codex/agents/bridge-one.toml").exists()
    monkeypatch.setattr(bridge, "_stage", lambda *args: pytest.fail("Builtin must not invoke upstream"))
    assert main(["--project", str(root), "--platform", "codex", "role", "install", "--agency", ROLE_TWO,
                 "--installer", "builtin", "--approve"]) == 0
    builtin = json.loads(capsys.readouterr().out)
    assert builtin["installed"] and (root / builtin["target"]).is_file()
    assert main(["--project", str(root), "role", "tools"]) == 0
    assert len(json.loads(capsys.readouterr().out)["tools"]) == 20


@pytest.mark.parametrize("tool,scope,path", [
    ("trae", "project", ".trae/skills/%s/SKILL.md"),
    ("pi", "project", ".agents/skills/%s/SKILL.md"),
    ("workbuddy", "project", ".agent-team/workbuddy-imports/%s.zip"),
])
def test_skill_host_role_preview_and_install_are_distinct_from_native_agents(library, tool, scope, path):
    root = library["project"]
    host = {"native_subagents": True, "evidence": "Session lists UI Designer",
            "available_agents": ["UI Designer", ROLE_ONE]}
    preview = bridge.install_agency_role(root, ROLE_ONE, tool, scope=scope, host=host)
    assert preview["action"] == "preview" and preview["confirmation"]["requires_user_response"]
    assert preview["target"] == str(root / (path % ROLE_ONE))
    assert preview["installer"]["backend"] == "agent-team-skill-adapter"
    assert preview["skill_available"] and not preview["native_available"]
    assert preview["activation"]["executed"] is False
    assert not Path(preview["target"]).exists()
    assert library["downloads"] == ["testing/testing-bridge-one.md"]
    installed = bridge.install_agency_role(root, ROLE_ONE, tool, scope=scope, host=host, approved=True, offline=True)
    assert installed["installed"] and not installed["native_available"]
    assert installed["activation"]["executed"] is False
    assert installed["agent_id"] == ROLE_ONE
    member = next(item for item in read_yaml(root / ".agent-team/team.yaml")["team"]["members"]
                  if item["id"] == ROLE_ONE)
    assert member["agent_kinds"][tool] == "skill"
    if tool == "workbuddy":
        import base64
        import io
        import zipfile
        data = Path(installed["target"]).read_bytes()
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            skill = package.read("SKILL.md").decode("utf-8")
        preview_file = preview["files"][0]
        assert base64.b64decode(preview_file["content_base64"]) == data
        assert preview["activation"]["state"] == "manual_import_required"
        assert installed["activation"]["state"] == "manual_import_required"
    else:
        skill_path = Path(installed["target"])
        assert skill_path.is_file()
        skill = skill_path.read_text(encoding="utf-8")
        assert installed["activation"]["state"] == "skill_discovery_required"
    assert "agent_team_role_id: " + ROLE_ONE in skill
    assert "ONLY_ROLE_ONE" in skill
    repeated = bridge.install_agency_role(root, ROLE_ONE, tool, scope=scope,
                                          host=host, approved=True, offline=True)
    assert repeated["action"] == "unchanged"


def test_workbuddy_user_scope_stages_under_home_and_stays_unimported(library):
    root = library["project"]
    result = bridge.install_agency_role(root, ROLE_ONE, "workbuddy", scope="user", approved=True)
    assert result["installed"] and result["installer"]["scope"] == "user"
    assert Path(result["target"]).is_relative_to(library["home"])
    assert result["activation"]["state"] == "manual_import_required"
    assert result["activation"]["executed"] is False


def test_vendor_hash_failure_happens_before_execution(library, monkeypatch, tmp_path):
    vendor = tmp_path / "vendor"
    shutil.copytree(bridge.VENDOR, vendor)
    (vendor / "scripts/install.sh").write_text("tampered", encoding="utf-8")
    monkeypatch.setattr(bridge, "VENDOR", vendor)
    monkeypatch.setattr(bridge, "_stage", lambda *args: pytest.fail("Unverified script must not execute"))
    with pytest.raises(ValueError, match="SHA-256"):
        bridge.install_agency_role(library["project"], ROLE_ONE, "codex", approved=True)
    assert library["downloads"] == []


def test_exclusive_creation_race_preserves_concurrent_external_file(library, staged_codex, monkeypatch):
    root = library["project"]
    target = root / ".codex/agents/bridge-one.toml"
    original_open = Path.open
    raced = []

    def concurrent_open(path, mode="r", *args, **kwargs):
        if path == target and mode == "xb" and not raced:
            raced.append(True)
            with original_open(path, "wb") as stream:
                stream.write(b"Concurrent external definition")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", concurrent_open)
    with pytest.raises(FileExistsError):
        bridge.install_agency_role(root, ROLE_ONE, "codex", approved=True)
    assert target.read_bytes() == b"Concurrent external definition"


@real_upstream
def test_combined_roster_registry_failure_restores_previous_content(library, monkeypatch):
    root = library["project"]
    bridge.install_agency_role(root, ROLE_ONE, "windsurf", approved=True)
    target = root / ".windsurfrules"
    original = target.read_bytes()
    registry = (root / ".agent-team/team.yaml").read_bytes()

    def fail_write(*args):
        raise OSError("simulated registry failure")

    monkeypatch.setattr(bridge, "write_yaml", fail_write)
    with pytest.raises(OSError, match="simulated registry failure"):
        bridge.install_agency_role(root, ROLE_TWO, "windsurf", approved=True)
    assert target.read_bytes() == original
    assert (root / ".agent-team/team.yaml").read_bytes() == registry


def test_project_native_output_does_not_duplicate_canonical_agency_role(library, staged_codex):
    root = library["project"]
    installed = bridge.install_agency_role(root, ROLE_ONE, "codex", approved=True)
    host = {"native_subagents": True, "evidence": "Current tools list Bridge One",
            "available_agents": [installed["agent_id"]]}
    catalog = build_catalog(root, "codex", sources=[], host=host)
    matches = [role for role in catalog if role["name"] == "Bridge One"]
    assert len(matches) == 1 and matches[0]["id"] == ROLE_ONE
    assert matches[0]["agent_id"] == installed["agent_id"]
    assert matches[0]["native_available"]
    assert not any(role["id"] == "bridge-one" for role in catalog)


def _fake_native_outputs(tool):
    """Portable copies of the upstream shapes; shell matrix tests verify originals."""
    frontmatter = b"---\nname: bridge-one\ndescription: Review implementation\n---\nONLY_ROLE_ONE\n"
    if tool == "opencode":
        return {"bridge-one.md": frontmatter}
    if tool == "kimi":
        return {"bridge-one/agent.yaml": b"version: 1\nagent:\n  name: bridge-one\n  system_prompt_path: ./system.md\n",
                "bridge-one/system.md": b"ONLY_ROLE_ONE\n"}
    if tool == "vibe":
        return {"agents/bridge-one.toml": b'agent_type = "agent"\nsystem_prompt_id = "bridge-one"\n',
                "prompts/bridge-one.md": b"ONLY_ROLE_ONE\n"}
    if tool == "osaurus":
        return {"agency-bridge-one/SKILL.md": frontmatter.replace(b"name: bridge-one", b"name: agency-bridge-one")}
    raise AssertionError(tool)


@pytest.mark.parametrize("tool", ["opencode", "kimi", "vibe", "osaurus"])
def test_user_installation_reused_across_projects_without_native_alias_duplicate(library, monkeypatch, tool):
    root = library["project"]
    monkeypatch.setattr(bridge, "_stage", lambda *args: _fake_native_outputs(tool))
    preview = bridge.install_agency_role(root, ROLE_ONE, tool, scope="user")
    record_path = library["home"] / (".agent-team/agency-roles/%s/%s.json" % (tool, ROLE_ONE))
    assert str(record_path) in preview["confirmation"]["targets"]
    assert not record_path.exists()
    installed = bridge.install_agency_role(root, ROLE_ONE, tool, scope="user", approved=True)
    assert record_path.is_file()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["tool"] == tool and record["role"]["id"] == ROLE_ONE
    if tool in bridge.SKILL_TARGETS:
        assert record["role"]["agent_kinds"][tool] == "skill"
    assert len(record["files"]) == len(_fake_native_outputs(tool))
    second = root.parent / "second-project"
    second.mkdir()
    bootstrap(second, tool)
    host = {"native_subagents": True, "evidence": "Actual host inventory lists installed role",
            "available_agents": [installed["agent_id"]]}
    catalog = build_catalog(second, tool, host=host)
    matches = [role for role in catalog if role["name"] == "Bridge One"]
    assert len(matches) == 1 and matches[0]["id"] == ROLE_ONE
    assert matches[0]["agent_id"] == installed["agent_id"]
    assert matches[0]["source_platform"] == tool
    assert matches[0]["installed_for_platform"] and matches[0]["native_available"]
    assert matches[0]["source_path"] == str(record_path)
    assert "ONLY_ROLE_ONE" in matches[0]["prompt"]
    assert not any(role["id"] in ("bridge-one", "agency-bridge-one") for role in catalog)
    assert not (second / ".agent-team/cache/agency").exists()
    assert library["downloads"] == ["testing/testing-bridge-one.md"]


@pytest.mark.parametrize("tool", ["opencode", "kimi", "vibe", "osaurus"])
def test_changed_native_artifact_invalidates_user_role_record(library, monkeypatch, tool):
    root = library["project"]
    monkeypatch.setattr(bridge, "_stage", lambda *args: _fake_native_outputs(tool))
    result = bridge.install_agency_role(root, ROLE_ONE, tool, scope="user", approved=True)
    # Change the last artifact: multi-file installation validation must not only
    # inspect the primary definition before claiming the stored profile is valid.
    target = Path(result["targets"][-1])
    original = target.read_bytes()
    target.write_bytes(original + b"\nUser edit\n")
    second = root.parent / "second-project"
    second.mkdir()
    bootstrap(second, tool)
    with pytest.warns(RuntimeWarning, match="Native user role files changed"):
        catalog = build_catalog(second, tool)
    assert not any(role["id"] == ROLE_ONE for role in catalog)
    assert target.read_bytes() == original + b"\nUser edit\n"


@pytest.mark.parametrize("tool,relative", [("opencode", ".config/opencode/agents"),
                                          ("qwen", ".qwen/agents"), ("zcode", ".zcode/agents"),
                                          ("copilot", ".github/agents"), ("copilot", ".copilot/agents")])
def test_extra_native_user_directories_require_explicit_source(library, tool, relative):
    directory = library["home"] / relative
    directory.mkdir(parents=True)
    (directory / "custom-extra.md").write_text(
        "---\nname: Custom Extra\ndescription: Independent local role\n---\nInspect local code.\n", encoding="utf-8")
    root = library["project"]
    for platform in ("generic", "codex"):
        assert not any(role["id"] == "custom-extra" for role in build_catalog(root, platform))
    assert not any(role["id"] == "custom-extra" for role in build_catalog(root, tool))
    role = next(role for role in build_catalog(root, tool, sources=[directory]) if role["id"] == "custom-extra")
    assert role["source"] == "local" and role["installation_required"]
    assert not role["native_available"]


@pytest.mark.parametrize("native", [False, True])
def test_selected_user_role_can_be_planned_in_new_project_without_reinstallation(library, monkeypatch, native):
    monkeypatch.setattr(bridge, "_stage", lambda *args: _fake_native_outputs("kimi"))
    installed = bridge.install_agency_role(library["project"], ROLE_ONE, "kimi", scope="user", approved=True)
    second = library["project"].parent / "second-project"
    second.mkdir()
    bootstrap(second, "kimi")
    registry = second / ".agent-team/team.yaml"
    original_registry = registry.read_bytes()
    user_files = {path: path.read_bytes() for path in library["home"].rglob("*") if path.is_file()}
    # An unrelated broken role proves planning only opens the selected record.
    unrelated = library["home"] / ".agent-team/agency-roles/kimi/unselected.json"
    unrelated.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(bridge, "_stage", lambda *args: pytest.fail("Planning must not reinstall a role"))
    monkeypatch.setattr(agency, "_download", lambda *args: pytest.fail("Planning must not download a role"))
    monkeypatch.setattr("agent_team.marketplace.build_catalog", lambda *args, **kwargs: pytest.fail("No capability gap needs a catalog scan"))
    spec = {"title": "Review selected implementation", "scores": dict.fromkeys(
        ("independence", "complexity", "specialization", "parallel_benefit"), 80),
        "acceptance_criteria": ["Review findings include concrete evidence"],
        "work_items": [{"id": "review", "role": ROLE_ONE, "goal": "Review current implementation",
                        "capabilities": ["review"], "deliverables": ["review report"],
                        "write_scope": [], "read_only": True, "depends_on": []}]}
    host = ({"native_subagents": True, "evidence": "Current Kimi host exposes the installed agent",
             "available_agents": [installed["agent_id"]]} if native else None)
    result = plan_task(second, spec, host=host)
    execution = result["execution"]
    assert execution["capability_gaps"] == [] and execution["retained_by_main"] == []
    assert execution["strategy"] == ("native_subagents" if native else "sequential_handoffs")
    assert execution["agents"][0]["member_id"] == ROLE_ONE
    assert execution["agents"][0]["configured_agent_id"] == installed["agent_id"]
    if native:
        assert execution["agents"][0]["agent_id"] == installed["agent_id"]
    assert "ONLY_ROLE_ONE" in execution["handoffs"][0]["prompt"]
    assert registry.read_bytes() == original_registry
    assert all(path.read_bytes() == data for path, data in user_files.items())
    assert not (second / ".agent-team/roles").exists()
    assert not (second / ".agent-team/cache").exists()


@pytest.mark.parametrize("malformation", ["record-list", "record-null", "role-list", "role-null",
                                          "files-list", "files-string", "files-empty", "hash-list",
                                          "hash-int", "hash-invalid"])
def test_malformed_user_record_warns_and_does_not_hide_other_valid_roles(library, monkeypatch, malformation):
    monkeypatch.setattr(bridge, "_stage", lambda *args: _fake_native_outputs("kimi"))
    bridge.install_agency_role(library["project"], ROLE_ONE, "kimi", scope="user", approved=True)
    directory = library["home"] / ".agent-team/agency-roles/kimi"
    good_path = directory / (ROLE_ONE + ".json")
    good = json.loads(good_path.read_text(encoding="utf-8"))
    bad = copy.deepcopy(good)
    if malformation == "record-list":
        bad = []
    elif malformation == "record-null":
        bad = None
    elif malformation.startswith("role-"):
        bad["role"] = [] if malformation == "role-list" else None
    elif malformation.startswith("files-"):
        bad["files"] = {"files-list": [], "files-string": "not-a-mapping", "files-empty": {}}[malformation]
    else:
        key = next(iter(bad["files"]))
        bad["files"][key] = {"hash-list": [], "hash-int": 42, "hash-invalid": "not-a-sha256"}[malformation]
    # Sort before the valid record to prove one bad entry doesn't abort iteration.
    (directory / "aaa-invalid.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.warns(RuntimeWarning, match="Skipping invalid Agency user role record"):
        roles = list(bridge.installed_user_roles("kimi"))
    assert [role["id"] for role in roles] == [ROLE_ONE]
    assert good_path.read_text(encoding="utf-8") == json.dumps(good, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
