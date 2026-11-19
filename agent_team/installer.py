"""Standard-library-only, self-contained Skill bundle installer."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import zipfile

from . import __version__

MANIFEST_NAME = ".agent-team-install.json"
REPOSITORY = "houchaoxu/agent-team-builder"


def bundle_manifest(files):
    return {"schema_version": 1, "repository": REPOSITORY, "version": __version__, "channel": "stable",
            "installed_at": time.time(),
            "files": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())}}


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
        if relative.as_posix() == MANIFEST_NAME:
            continue
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
    data = package / "data"
    if data.exists():
        _no_links(data)
        for path in data.rglob("*"):
            if path.is_symlink():
                raise ValueError("Runtime data contains a symlink: {}".format(path))
            if path.is_file():
                files["scripts/runtime/agent_team/data/" + path.relative_to(data).as_posix()] = path.read_bytes()
    if "SKILL.md" not in files or "scripts/run.py" not in files:
        raise ValueError("Incomplete Skill source")
    return files


def _same(destination, files):
    actual = {}
    for path in destination.rglob("*"):
        relative = path.relative_to(destination)
        if relative.as_posix() == MANIFEST_NAME:
            if path.is_symlink():
                raise ValueError("Installation manifest cannot be a symlink")
            continue
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
        (stage / MANIFEST_NAME).write_text(json.dumps(bundle_manifest(files), ensure_ascii=False,
                                                    sort_keys=True, indent=2) + "\n", encoding="utf-8")
        if destination.exists() or destination.is_symlink():
            raise ValueError("Skill destination appeared during installation; retry safely")
        stage.rename(destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return dict(result, status="installed")


def export_bundle_archive(destination, source_root=None):
    """Create a self-contained, importable Skill ZIP (SKILL.md at archive root)."""
    destination = _no_links(Path(destination))
    files = _files(source_root)
    manifest = bundle_manifest(files)
    # Stable bytes make repeated exports idempotent while retaining provenance.
    manifest.pop("installed_at", None)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, content)
        info = zipfile.ZipInfo(MANIFEST_NAME, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        bundle.writestr(info, json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    content = archive.getvalue()
    if destination.exists():
        if not destination.is_file() or destination.read_bytes() != content:
            raise ValueError("Skill archive destination differs; existing files will not be overwritten")
        return {"path": str(destination), "status": "unchanged", "sha256": hashlib.sha256(content).hexdigest(),
                "files": sorted(files)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + destination.name + "-", dir=str(destination.parent))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if destination.exists() or destination.is_symlink():
            raise ValueError("Skill archive destination appeared during export; retry safely")
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"path": str(destination), "status": "prepared", "sha256": hashlib.sha256(content).hexdigest(),
            "files": sorted(files)}


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--scope", choices=("project", "user"), default="project")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    from .platforms import PLATFORMS
    parser.add_argument("--platform", choices=PLATFORMS, default="codex")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args(argv)
    try:
        directories = {
            "codex": ".agents/skills/agent-team-runtime",
            "claude-code": ".claude/skills/agent-team-runtime",
            "trae": ".trae/skills/agent-team-runtime",
            "pi": ".agents/skills/agent-team-runtime",
        }
        if args.destination is None and args.platform not in directories and args.platform != "workbuddy":
            raise ValueError("This platform requires an explicit --destination")
        default_destination = ((Path.home() if args.scope == "user" else args.project)
                               / ".agent-team/exports/agent-team-runtime.zip"
                               if args.platform == "workbuddy" else
                               (Path.home() if args.scope == "user" else args.project) / directories[args.platform])
        destination = args.destination or default_destination
        destination = _no_links(destination)
        if args.approve:
            result = (export_bundle_archive(destination) if args.platform == "workbuddy"
                      else export_bundle(destination))
            if args.platform == "workbuddy":
                result.update(status="prepared_for_import", activation={
                    "state": "manual_import_required", "executed": False,
                    "instructions": "Import this ZIP in WorkBuddy's Skills UI and select the requested "
                                    + args.scope + " scope. "
                                    "The public docs do not specify automatic local project discovery."})
            elif result["status"] == "installed":
                result_path = destination / MANIFEST_NAME
                if result_path.exists():
                    manifest = json.loads(result_path.read_text(encoding="utf-8"))
                    manifest.update(scope=args.scope, platform=args.platform)
                    result_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                                           encoding="utf-8")
        else:
            result = {"status": "preview", "path": str(destination), "files": sorted(_files()),
                      "writes": [str(destination)], "network": False,
                      "dependencies": ["Python>=3.9", "optional runtime: PyYAML>=6,<7",
                                       "Python<3.11: tomli>=2"],
                      "next": "Agent may apply existing authorization using --approve"}
            if args.platform == "workbuddy":
                result["activation"] = {"state": "manual_import_required", "executed": False,
                                        "instructions": "The ZIP will need to be imported through WorkBuddy's Skills UI; "
                                                        "select Project scope after import."}
        result.update(scope=args.scope, platform=args.platform)
        result["installed_globally"] = args.scope == "user" and args.platform != "workbuddy"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
