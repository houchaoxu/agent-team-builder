#!/usr/bin/env python3
"""Maintainer: vendor reviewed installer files from the index's clean checkout.

Run build_agency_index.py first when intentionally changing upstream revision.
Review upstream script changes and the target/scope contract before committing.
End users receive these files in the Skill; they do not clone upstream.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

FILES = ("scripts/install.sh", "scripts/convert.sh", "scripts/lib.sh", "divisions.json", "tools.json")
DATA = Path(__file__).resolve().parents[1] / "agent_team/data"


def build(checkout, data=DATA):
    checkout, data = Path(checkout).resolve(), Path(data)
    revision = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain"], text=True).strip()
    if dirty or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Installer build requires a clean pinned upstream checkout")
    index = json.loads((data / "agency-index.json").read_text(encoding="utf-8"))
    if index["revision"] != revision:
        raise ValueError("Build the role index at this same revision before vendoring its installer")
    files = {}
    for name in FILES:
        path = checkout / name
        if path.is_symlink():
            raise ValueError("Upstream installer files must not be symlinks")
        # Read Git blobs so a clean core.autocrlf checkout cannot change hashes.
        files[name] = subprocess.check_output(["git", "-C", str(checkout), "show", "HEAD:" + name])
    target = data / "agency-installer"
    manifest = {"repository": "msitarzewski/agency-agents", "revision": revision, "license": "MIT",
                "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}}
    for name, content in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("Vendored %s installer files at %s; review scripts and scope mappings before release" % (len(files), revision))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--data", type=Path, default=DATA)
    args = parser.parse_args()
    build(args.checkout, args.data)
