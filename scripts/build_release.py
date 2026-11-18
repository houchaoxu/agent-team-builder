#!/usr/bin/env python3
"""Build the self-contained stable Release assets using only the standard library."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent_team import __version__
from agent_team.installer import export_bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--tag", help="Stable release tag, which must match the package version")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", __version__):
        parser.error("Only stable numeric package versions can be released")
    if args.tag is not None and args.tag != "v" + __version__:
        parser.error("Release tag must be v" + __version__)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "agent-team-runtime-skill.zip"
    with tempfile.TemporaryDirectory(prefix="agent-team-release-") as temporary:
        bundle = Path(temporary).resolve() / "agent-team-runtime"
        export_bundle(bundle, source_root=ROOT)
        manifest = json.loads((bundle / ".agent-team-install.json").read_text(encoding="utf-8"))
        if (manifest.get("schema_version") != 1
                or manifest.get("repository") != "houchaoxu/agent-team-builder"
                or manifest.get("version") != __version__):
            raise ValueError("Exported installation manifest does not match this release")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as release:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    release.write(path, "agent-team-runtime/" + path.relative_to(bundle).as_posix())
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum_path = output / (archive.name + ".sha256")
    checksum_path.write_text(checksum + "  " + archive.name + "\n", encoding="utf-8")
    print(json.dumps({"version": __version__, "archive": str(archive),
                      "checksum": str(checksum_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
