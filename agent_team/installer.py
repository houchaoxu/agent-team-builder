"""Standard-library-only, self-contained Skill bundle installer."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


def skill_source(package_root=None):
    package = Path(package_root or Path(__file__).parent).resolve()
    source = package / "skill"
    if source.is_dir():
        return source
    # Installed bundle: <skill>/scripts/runtime/agent_team/installer.py
    source = package.parent.parent.parent
    if (source / "SKILL.md").is_file():
        return source
    raise ValueError("Skill resources are missing")


def _no_links(path):
    path = Path(os.path.abspath(str(path.expanduser())))
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError("Symlink paths are not supported: {}".format(component))
    return path


def _files(source_root=None):
    package = _no_links(Path(source_root or Path(__file__).parent))
    if (package / "agent_team").is_dir():
        package = package / "agent_team"
    source = skill_source(package)
    files = {}
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if any(part in ("__pycache__", ".cache") for part in relative.parts):
            continue
        if relative.parts[:2] == ("scripts", "runtime"):
            continue
        if path.is_symlink():
            raise ValueError("Skill source contains a symlink: {}".format(path))
        if path.is_file():
            files[relative.as_posix()] = path.read_bytes()
    for path in package.glob("*.py"):
        if path.is_symlink():
            raise ValueError("Runtime source contains a symlink: {}".format(path))
        files["scripts/runtime/agent_team/" + path.name] = path.read_bytes()
    if "SKILL.md" not in files or "scripts/run.py" not in files:
        raise ValueError("Incomplete Skill source")
    return files


def _same(destination, files):
    actual = {}
    for path in destination.rglob("*"):
        relative = path.relative_to(destination)
        # A provisioned venv legitimately contains interpreter symlinks. Its
        # mutable contents are not part of the exported bundle manifest.
        if relative.parts[0] == ".cache" and len(relative.parts) > 1:
            continue
        if path.is_symlink():
            raise ValueError("Existing Skill contains a symlink: {}".format(path))
        if any(part in (".cache", "__pycache__") for part in relative.parts):
            continue
        if path.is_file():
            actual[relative.as_posix()] = path.read_bytes()
    return actual == files


def export_bundle(destination, source_root=None):
    """Install atomically; an identical installation is safe to repeat."""
    destination = _no_links(Path(destination))
    files = _files(source_root)
    result = {"path": str(destination), "files": sorted(files),
              "installed_globally": False, "runner": str(destination / "scripts/run.py")}
    if destination.exists():
        if not destination.is_dir() or not _same(destination, files):
            raise ValueError("Skill destination differs; existing files will not be overwritten")
        return dict(result, status="unchanged")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="." + destination.name + "-", dir=str(destination.parent)))
    try:
        for relative, content in files.items():
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        if destination.exists() or destination.is_symlink():
            raise ValueError("Skill destination appeared during installation; retry safely")
        stage.rename(destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return dict(result, status="installed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--scope", choices=("project", "user"), default="project")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--platform", choices=("codex", "claude-code", "cursor", "gemini-cli", "generic"), default="codex")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.destination is None and args.platform != "codex":
            raise ValueError("This platform requires an explicit --destination")
        destination = args.destination or ((Path.home() if args.scope == "user" else args.project)
                                           / ".agents/skills/agent-team-runtime")
        destination = _no_links(destination)
        if args.approve:
            result = export_bundle(destination)
        else:
            result = {"status": "preview", "path": str(destination), "files": sorted(_files()),
                      "writes": [str(destination)], "network": False,
                      "dependencies": ["Python>=3.9", "optional runtime: PyYAML>=6,<7",
                                       "Python<3.11: tomli>=2"],
                      "next": "Agent may apply existing authorization using --approve"}
        result.update(scope=args.scope, platform=args.platform)
        result["installed_globally"] = args.scope == "user"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
