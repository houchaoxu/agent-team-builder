"""Agent-internal optional Python engine; never installs into system Python."""
import json
import os
from pathlib import Path
import subprocess
import sys
import venv


# Ignore PYTHONPATH and the working directory while retaining legitimate user-site
# dependencies already installed for this interpreter (unlike -I).
PROBE = "import sys; sys.path.pop(0); import yaml; " + ("import tomli" if sys.version_info < (3, 11) else "import tomllib")


def _safe(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("Runtime path contains a symlink: {}".format(part))
    return path


def locations():
    script = _safe(Path(os.path.abspath(__file__)))
    skill = script.parent.parent
    runtime = script.parent / "runtime"
    if not (runtime / "agent_team/__init__.py").is_file():
        runtime = skill.parent.parent
    if not (runtime / "agent_team/__init__.py").is_file():
        raise ValueError("Bundled runtime is missing")
    _safe(runtime / "agent_team")
    for path in (runtime / "agent_team").glob("*.py"):
        _safe(path)
    return skill, _safe(runtime)


def available(python):
    try:
        return subprocess.run([str(python), "-E", "-c", PROBE],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0
    except OSError:
        return False


def cached_python(skill):
    env = _safe(skill / ".cache/env")
    _safe(env / ("Scripts" if os.name == "nt" else "bin"))
    # venv's Python may itself be a legitimate link to the system interpreter.
    return env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def select_python(skill):
    if available(sys.executable):
        return Path(sys.executable)
    cached = cached_python(skill)
    if cached.exists() and available(cached):
        return cached
    return None


def setup(skill):
    selected = select_python(skill)
    if selected:
        return selected
    python = cached_python(skill)
    cache = _safe(skill / ".cache")
    cache.mkdir(exist_ok=True)
    lock = cache / "setup.lock"
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError("Runtime setup is already running; retry after it finishes")
    try:
        env = python.parent.parent
        if env.exists():
            raise ValueError("Cached environment is incomplete; Agent must inspect .cache/env before retrying")
        venv.EnvBuilder(with_pip=True).create(str(env))
        requirements = ["PyYAML>=6,<7"]
        if sys.version_info < (3, 11):
            requirements.append("tomli>=2")
        result = subprocess.run([str(python), "-I", "-m", "pip", "install",
                                 "--disable-pip-version-check", "--no-input", *requirements],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode or not available(python):
            raise ValueError("Dependency setup failed. Agent can use basic Skill mode or request environment/network approval. "
                             + result.stderr[-2000:])
        return python
    finally:
        lock.rmdir()


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        skill, runtime = locations()
        if args == ["--check"]:
            python = select_python(skill)
            print(json.dumps({"status": "ready" if python else "setup_required",
                              "python": str(python) if python else None,
                              "runtime": str(runtime), "network": False, "writes": [],
                              "next": None if python else "Agent may invoke --setup with environment authorization"}))
            return 0
        if args == ["--setup"]:
            python = setup(skill)
            print(json.dumps({"status": "ready", "python": str(python)}))
            return 0
        python = select_python(skill)
        if python is None:
            print(json.dumps({"status": "setup_required", "next": "Agent: invoke --setup or use basic Skill mode"}))
            return 3
        # Remove implicit cwd and ignore PYTHONPATH, preserving legitimate site packages.
        code = "import sys; sys.path[0] = sys.argv.pop(1); from agent_team.cli import main; raise SystemExit(main())"
        return subprocess.run([str(python), "-E", "-c", code, str(runtime), *args]).returncode
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
