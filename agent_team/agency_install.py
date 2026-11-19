"""Stage pinned upstream installers; promote only reviewed, selected artifacts.

Upstream scripts never run against the real home or destination. Native host
registration and plugin activation remain separate from copying definitions.
"""
import copy
import base64
import io
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import warnings
import zipfile

from . import agency
from .adapters import capabilities, render_role
from .storage import project_lock, read_yaml, safe_path, validate_team, write_yaml

VENDOR = Path(__file__).parent / "data/agency-installer"
SKILL_TARGETS = {"trae", "pi", "workbuddy"}
# install.sh --path is a directory, whereas tools.json dest describes files.
DESTINATIONS = {
    "claude-code": {"project": [".claude/agents"], "user": [".claude/agents"]},
    "codex": {"project": [".codex/agents"], "user": [".codex/agents"]},
    "gemini-cli": {"project": [".gemini/agents"], "user": [".gemini/agents"]},
    "copilot": {"project": [".github/agents"], "user": [".github/agents", ".copilot/agents"]},
    "qwen": {"project": [".qwen/agents"], "user": [".qwen/agents"]},
    "cursor": {"project": [".cursor/rules"]},
    "opencode": {"project": [".opencode/agents"], "user": [".config/opencode/agents"]},
    "antigravity": {"project": [".agents/skills"], "user": [".gemini/config/skills"]},
    "osaurus": {"user": [".osaurus/skills"]},
    "aider": {"project": ["."]}, "windsurf": {"project": ["."]},
    "kimi": {"user": [".config/kimi/agents"]},
    "openclaw": {"user": [".openclaw/agency-agents"]},
    "trae": {"project": [".trae/skills"], "user": [".trae/skills"]},
    "pi": {"project": [".agents/skills"], "user": [".agents/skills"]},
    "workbuddy": {"project": [".agent-team/workbuddy-imports"],
                  "user": [".agent-team/workbuddy-imports"]},
    "vibe": {"project": [".vibe"], "user": [".vibe"]},
    "zcode": {"project": [".zcode/agents"], "user": [".zcode/agents"]},
    "dsh": {"project": [".dsh/skills"], "user": [".dsh/skills"]},
}


def _skill_zip(files):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, content)
    return archive.getvalue()


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _vendor_files():
    manifest = json.loads((VENDOR / "manifest.json").read_text(encoding="utf-8"))
    if manifest["repository"] != agency.REPOSITORY or manifest["revision"] != agency.load_index()["revision"]:
        raise ValueError("Agency installer and role index must use the same pinned revision")
    files = {}
    for relative, digest in manifest["files"].items():
        path = _strict_path(VENDOR, relative)
        data = path.read_bytes()
        if _hash(data) != digest:
            raise ValueError("Agency installer SHA-256 verification failed: " + relative)
        files[relative] = data
    return manifest, files


def supported_tools():
    manifest, files = _vendor_files()
    tools = json.loads(files["tools.json"])["tools"]
    result = [dict(id=key, name=value["label"], format=value["format"],
                   kind=value["installKind"], scopes=list(DESTINATIONS.get(key, {})),
                   upstream_scope=value["scope"], destinations=value["dest"],
                   installer="agency-upstream", installation_supported=key in DESTINATIONS,
                   native_available=None,
                   note=("Hermes installs and enables a router plugin, not a single role; "
                         "plugin/config integration is not supported by this role installer."
                         if key == "hermes" else
                         "Workspace files only; native OpenClaw registration is a separate action."
                         if key == "openclaw" else
                         "Selected roles share one managed roster; existing user content is preserved."
                         if value["installKind"] == "roster" else
                         "Files require host discovery; installation does not prove invocation."))
              for key, value in tools.items()]
    result.extend([
        dict(id="trae", name="TRAE", format="Agent Skills (SKILL.md)", kind="skill",
             scopes=["project", "user"], destinations=DESTINATIONS["trae"],
             installer="agent-team-skill-adapter", installation_supported=True, native_available=None,
             note="Creates a discoverable Skill; it does not create a native callable custom Agent. "
                  "Project rules or the .agents Skills directory may need enabling in TRAE settings."),
        dict(id="pi", name="Pi", format="Agent Skills (SKILL.md)", kind="skill",
             scopes=["project", "user"], destinations=DESTINATIONS["pi"],
             installer="agent-team-skill-adapter", installation_supported=True, native_available=None,
             note="Creates a discoverable Skill; native subagent calls require a separately available extension."),
        dict(id="workbuddy", name="WorkBuddy", format="Agent Skill import package (SKILL.md)", kind="skill-package",
             scopes=["project", "user"], destinations=DESTINATIONS["workbuddy"],
             installer="agent-team-skill-adapter", installation_supported=True, native_available=None,
             note="Stages a role Skill for manual import through WorkBuddy's Skills UI; public docs do not specify "
                  "a stable local project discovery path."),
    ])
    return {"repository": manifest["repository"], "revision": manifest["revision"],
            "prerequisites": ["Bash 3.2+", "standard Unix utilities", "Perl for upstream TOML conversion"],
            "tools": result}


def _strict_path(root, relative):
    path = safe_path(root, relative)
    # Reject links even if their target currently remains inside the scope.
    current = Path(root).resolve()
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Agency install destination contains a symlink: " + str(current))
    return path


def _run(command, cwd, env):
    try:
        result = subprocess.run(command, cwd=str(cwd), env=env, capture_output=True,
                                encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Agency upstream command could not finish: %s" % exc) from exc
    if result.returncode:
        raise ValueError("Agency upstream command failed: " + (result.stderr + result.stdout)[-3000:])


def _stage(profiles, tool, vendor_files):
    if tool in SKILL_TARGETS:
        output = {}
        for profile in profiles:
            rendered = render_role(profile, tool)
            if tool == "workbuddy":
                output[profile["id"] + ".zip"] = _skill_zip({"SKILL.md": rendered["content"].encode("utf-8")})
            else:
                output[profile["id"] + "/SKILL.md"] = rendered["content"].encode("utf-8")
        return output
    bash = shutil.which("bash")
    if not bash:
        raise ValueError("Agency installer requires Bash and Unix utilities (Windows: Git Bash/WSL). "
                         "Use an available Bash environment or explicitly choose --installer builtin for a portable profile.")
    with tempfile.TemporaryDirectory(prefix="agent-team-agency-") as temporary:
        stage = Path(temporary).resolve()
        repo, output, home = stage / "upstream", stage / "output", stage / "home"
        for relative, data in vendor_files.items():
            path = repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (repo / "integrations").mkdir()
        home.mkdir()
        for profile in profiles:
            path = repo / profile["upstream"]["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            # fetch_role already verified the raw cache. Preserve attribution in
            # standalone native outputs as well as the canonical team profile.
            with path.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(profile["prompt"])
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR") if key in os.environ}
        env.update(HOME=str(home), TMPDIR=str(stage), XDG_CONFIG_HOME=str(home / ".config"),
                   LC_ALL="C", NO_COLOR="1")
        if tool not in ("claude-code", "copilot"):
            _run([bash, str(repo / "scripts/convert.sh"), "--tool", tool], repo, env)
        if tool == "openclaw":
            # Upstream install.sh invokes the real openclaw executable when it
            # exists. Use its converter outputs without registration side effects.
            output = repo / "integrations/openclaw"
        else:
            command = [bash, str(repo / "scripts/install.sh"), "--tool", tool,
                       "--agent", Path(profiles[-1]["upstream"]["path"]).stem,
                       "--path", str(output), "--no-interactive", "--no-convert"]
            _run(command, repo, env)
        files = {}
        for path in sorted(output.rglob("*")):
            if path.is_symlink():
                raise ValueError("Agency upstream output contains a symlink")
            if path.is_file():
                if len(files) >= 100 or path.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError("Agency upstream output exceeds the installation limit")
                files[path.relative_to(output).as_posix()] = path.read_bytes()
        if not files:
            raise ValueError("Agency upstream installer produced no role files")
        return files


def _activation(tool, agent_id, targets, scope=None):
    if tool == "workbuddy":
        return {"state": "manual_import_required", "executed": False,
                "instructions": "This ZIP is an import artifact, not an installed WorkBuddy skill. "
                                "Import it in WorkBuddy's Skills UI and choose the " + (scope or "selected") + " scope; verify it appears "
                                "in the current project before use."}
    if tool in ("trae", "pi"):
        instructions = ("The Skill file is installed. Verify TRAE discovers it; TRAE may require enabling the "
                        ".trae/skills or .agents/skills location in Settings. " if tool == "trae" else
                        "The Skill file is installed under .agents/skills, which Pi discovers. Use /reload or "
                        "restart if the current session already scanned Skills. ")
        return {"state": "skill_discovery_required", "executed": False,
                "instructions": instructions +
                                "A Skill is not a native callable subagent; verify delegation separately."}
    if tool == "openclaw":
        workspace = str(Path(targets[0]).parent)
        return {"state": "registration_required", "executed": False,
                "instructions": "Workspace files are installed. Ask for explicit native registration/restart "
                                "authorization and inspect actual OpenClaw state before invoking it.",
                "registration_command": ["openclaw", "agents", "add", agent_id,
                                         "--workspace", workspace, "--non-interactive"]}
    return {"state": "host_verification_required", "executed": False,
            "instructions": "Verify host discovery and actual invocation. Refresh/reopen if the host requires it; "
                            "otherwise use the canonical role instructions for an explicit handoff."}


def installed_user_roles(tool, role_ids=None):
    """Read only this host's managed records, with all native artifacts verified."""
    home = Path.home().resolve()
    directory = _strict_path(home, ".agent-team/agency-roles/" + tool)
    if not directory.is_dir():
        return
    paths = sorted(directory.glob("*.json")) if role_ids is None else [
        directory / (identifier + ".json") for identifier in role_ids
        if isinstance(identifier, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", identifier)]
    for index, path in enumerate(paths):
        if index >= 300:
            warnings.warn("Agency user role scan stopped after 300 records", RuntimeWarning)
            break
        try:
            _strict_path(home, path.relative_to(home))
            if not path.exists():
                continue
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("User role record exceeds 2 MB")
            record = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(record, dict) or record.get("schema_version") != 1 or record.get("tool") != tool
                    or not isinstance(record.get("files"), dict) or not record["files"]
                    or not isinstance(record.get("role"), dict)):
                raise ValueError("Invalid managed user role record")
            for relative, digest in record["files"].items():
                if not isinstance(relative, str) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise ValueError("Invalid native file hash in user role record")
                native = _strict_path(home, relative)
                if native.stat().st_size > 2 * 1024 * 1024 or _hash(native.read_bytes()) != digest:
                    raise ValueError("Native user role files changed: " + relative)
            role = record["role"]
            render_role(role, "generic")
            if role["id"] != path.stem or role.get("platforms") != [tool]:
                raise ValueError("User role identity or platform does not match its managed record")
            for field in ("capabilities", "deliverables"):
                values = role.get(field)
                if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                    raise ValueError("Invalid %s in managed user role record" % field)
            yield dict(role, source="installed", source_path=str(path),
                       source_platform=tool, managed_paths=[str(home / name) for name in record["files"]])
        except (ValueError, OSError, KeyError, TypeError) as exc:
            warnings.warn("Skipping invalid Agency user role record %s: %s" % (path, exc), RuntimeWarning)


def install_agency_role(root, role_id, tool, scope="project", approved=False, host=None, offline=False):
    if tool not in DESTINATIONS:
        raise ValueError("Agency single-role installation is not supported for %s; inspect role tools. "
                         "Hermes requires separate router plugin/config integration." % tool)
    if scope not in DESTINATIONS[tool]:
        raise ValueError("%s does not support %s scope in the upstream contract. "
                         "Ask the user to select a supported scope; do not silently switch to user scope." % (tool, scope))
    root = Path(root).resolve()
    destination = root if scope == "project" else Path.home().resolve()
    manifest, vendor_files = _vendor_files()
    profile = agency.fetch_role(root, role_id, platform=tool, offline=offline)
    config_path = _strict_path(root, ".agent-team/team.yaml")
    if not config_path.is_file():
        raise ValueError("Initialize the project before installing a role.")
    original = config_path.read_bytes()
    config = validate_team(read_yaml(config_path))
    key = tool + ":" + scope
    previous = config.get("agency_installations", {}).get(key, {})
    role_ids = list(dict.fromkeys(previous.get("roles", []) + [role_id]))
    profiles = ([profile if identifier == role_id else
                 agency.fetch_role(root, identifier, platform=tool, offline=offline)
                 for identifier in role_ids]
                if tool in ("aider", "windsurf") else [profile])
    outputs = _stage(profiles, tool, vendor_files)
    native_id = role_id if tool in SKILL_TARGETS else Path(next(iter(outputs))).stem
    if tool in ("antigravity", "osaurus", "dsh", "kimi", "openclaw"):
        native_id = next(iter(outputs)).split("/")[0]
    elif tool == "codex":
        from .marketplace import tomllib
        native_id = tomllib.loads(next(iter(outputs.values())).decode("utf-8"))["name"]
    elif tool in ("claude-code", "copilot"):
        native_id = profile["name"]
    elif tool == "vibe":
        native_id = next(Path(name).stem for name in outputs if name.startswith("agents/"))
    writes = {}
    for prefix in DESTINATIONS[tool][scope]:
        for relative, data in outputs.items():
            writes[(Path(prefix) / relative).as_posix()] = data
    if tool == "aider":
        data = writes["CONVENTIONS.md"].decode("utf-8")
        for item in profiles:
            source = item["upstream"]["path"]
            persistent = ".agent-team/agency-sources/" + manifest["revision"] + "/" + source
            data = data.replace(source, persistent)
            writes[persistent] = item["prompt"].encode("utf-8")
        writes["CONVENTIONS.md"] = data.encode("utf-8")
    canonical = render_role(profile, "generic")
    files = [(destination, relative, data) for relative, data in writes.items()]
    if scope == "user":
        # A small per-role record makes multi-file/Skill installations reusable
        # from another project without scanning all host directories or relying
        # on the first project's cache/registry.
        reusable = {key: profile[key] for key in ("id", "name", "description", "capabilities", "deliverables", "prompt", "upstream")}
        reusable.update(platforms=[tool], agent_id=native_id)
        if tool in SKILL_TARGETS:
            reusable["agent_kinds"] = {tool: "skill"}
        record = {"schema_version": 1, "tool": tool, "role": reusable,
                  "files": {name: _hash(data) for name, data in writes.items()}}
        relative = ".agent-team/agency-roles/%s/%s.json" % (tool, role_id)
        files.append((destination, relative, (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")))
    files.append((root, canonical["path"], canonical["content"].encode("utf-8")))
    old_hashes = previous.get("files", {})
    entries = []
    for base, relative, data in files:
        path = _strict_path(base, relative)
        existing = path.read_bytes() if path.is_file() else None
        if path.exists() and not path.is_file():
            raise ValueError("Role destination is not a file: " + str(path))
        update = existing is not None and existing != data
        # Only managed combined rosters may change existing content. A manually
        # edited roster is a conflict, even after --approve.
        if update and not (tool in ("aider", "windsurf") and base == destination
                           and _hash(existing) == old_hashes.get(relative)):
            raise ValueError("Role file already exists with different content; refusing to overwrite: " + str(path))
        action = "update" if update else "unchanged" if existing is not None else "create"
        entry = {"path": str(path), "relative": relative, "sha256": _hash(data), "action": action}
        if relative.endswith(".zip"):
            entry["content_base64"] = base64.b64encode(data).decode("ascii")
            with zipfile.ZipFile(io.BytesIO(data)) as package:
                entry["archive_files"] = [{"path": name, "content": package.read(name).decode("utf-8")}
                                           for name in package.namelist()]
        else:
            entry["content"] = data.decode("utf-8")
        entries.append(entry)
    verified = capabilities(tool, host)
    native = (False if tool in SKILL_TARGETS else verified["native_subagents"] and any(
        name in verified["available_agents"] for name in (native_id, role_id, profile["name"])))
    targets = [str(_strict_path(destination, name)) for name in writes]
    backend = "agent-team-skill-adapter" if tool in SKILL_TARGETS else "agency-upstream"
    mechanism = ("manual-import-package" if tool == "workbuddy" else
                 "skill-file" if tool in ("trae", "pi") else
                 "converter-only" if tool == "openclaw" else "convert-and-install")
    result = {"id": role_id, "name": profile["name"], "source": "agency", "upstream": profile["upstream"],
              "installer": {"backend": backend, "revision": manifest["revision"],
                            "tool": tool, "scope": scope, "mechanism": mechanism},
              "path": canonical["path"], "target": targets[0], "targets": targets,
              "files": entries, "agent_id": native_id,
              "permissions": ["write selected %s role files" % scope, "update project team registry"],
              "approved": approved is True, "installed": False, "action": "preview",
              "status": "available" if native else "unavailable", "native_available": native,
              "skill_available": tool in SKILL_TARGETS,
              "activation": _activation(tool, native_id, targets, scope)}
    if approved is not True:
        result["confirmation"] = {"kind": "role_installation", "role_id": role_id, "name": profile["name"],
                                  "tool": tool, "scope": scope, "target": result["target"],
                                  "targets": [entry["path"] for entry in entries] + [str(config_path)],
                                  "permissions": result["permissions"], "requires_user_response": True,
                                  "default_selection": None,
                                  "options": [{"id": "install", "label": "Install this role"},
                                              {"id": "cancel", "label": "Do not install"}],
                                  "instructions": "Show exact files, scope and activation requirements. Only an explicit "
                                                  "user response confirming this preview permits --approve; role "
                                                  "selection, prior broad authorization and silence are not approval."}
        return result
    with project_lock(root):
        if _strict_path(root, ".agent-team/team.yaml").read_bytes() != original:
            raise ValueError("Team registry changed while preparing installation; generate a fresh preview")
        updated = copy.deepcopy(config)
        members = updated.get("team", updated).setdefault("members", [])
        member = next((item for item in members if item["id"] == role_id), None)
        if member is None:
            member = {"id": role_id}
            members.append(member)
        elif member.get("upstream", {}).get("sha256") != profile["upstream"]["sha256"]:
            raise ValueError("Role id already refers to a different profile; refusing to overwrite its registry entry")
        member.update(role=profile["name"], name=profile["name"], definition=canonical["path"],
                      description=profile["description"], capabilities=profile["capabilities"],
                      deliverables=profile["deliverables"], upstream=profile["upstream"], status="installed")
        member["platforms"] = list(dict.fromkeys(member.get("platforms", []) + [tool]))
        member.setdefault("agent_ids", {})[tool] = native_id
        if tool in SKILL_TARGETS:
            member.setdefault("agent_kinds", {})[tool] = "skill"
        member["agent_id"] = native_id
        records = updated.setdefault("agency_installations", {})
        records[key] = {"roles": role_ids, "files": dict(old_hashes, **{name: _hash(data) for name, data in writes.items()})}
        validate_team(updated)
        backups = []
        try:
            for (base, relative, data), entry in zip(files, entries):
                path = _strict_path(base, relative)
                existing = path.read_bytes() if path.is_file() else None
                # Recheck every artifact after lock, including user-scoped files.
                if (existing is None and entry["action"] != "create") or (
                        existing is not None and _hash(existing) != (
                            old_hashes.get(relative) if entry["action"] == "update" else entry["sha256"])):
                    raise ValueError("Role destination changed; generate a fresh preview: " + str(path))
                if existing == data:
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                if existing is None:
                    with path.open("xb") as stream:
                        backups.append((path, None))
                        stream.write(data)
                else:
                    backups.append((path, existing))
                    agency._atomic_bytes(path, data)
            write_yaml(config_path, updated)
        except BaseException:
            for path, data in reversed(backups):
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    agency._atomic_bytes(path, data)
            raise
    result.update(installed=True, action="unchanged" if all(e["action"] == "unchanged" for e in entries) else "installed")
    return result
