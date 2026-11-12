"""Agent-internal bootstrap. Preview by default; --approve installs the Skill."""
import importlib.util
from pathlib import Path


if __name__ == "__main__":
    spec = importlib.util.spec_from_file_location(
        "agent_team_installer", Path(__file__).parent / "agent_team/installer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raise SystemExit(module.main())
