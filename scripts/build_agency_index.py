#!/usr/bin/env python3
"""Maintainer tool: build compact Agency cards from an existing local checkout.

Usage: python scripts/build_agency_index.py CHECKOUT [--output FILE]
End users use the packaged index and never need a checkout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

import yaml

ROLE_DIRS = ("academic design engineering finance game-development gis healthcare marketing "
             "paid-media product project-management research sales security spatial-computing "
             "specialized support testing").split()
SCHEMA = 1


def compact(text, limit):
    return re.sub(r"\s+", " ", str(text)).strip()[:limit]


def build(checkout, output):
    checkout, output = Path(checkout).resolve(), Path(output)
    revision = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Checkout must have a full Git revision")
    # A dirty checkout would misrepresent raw GitHub bytes at that revision.
    dirty = subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain"], text=True).strip()
    if dirty:
        raise ValueError("Build requires a clean upstream checkout")
    previous = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    old = {card["path"]: card for card in previous.get("roles", [])} if previous.get("schema_version") == SCHEMA else {}
    cards, reused = [], 0
    for directory in ROLE_DIRS:
        for path in sorted((checkout / directory).rglob("*.md")):
            if path.is_symlink() or path.stat().st_size > 256 * 1024:
                continue
            relative = path.relative_to(checkout).as_posix()
            if any(part in ("skills", "examples", "docs") for part in path.relative_to(checkout).parts):
                continue
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if relative in old and old[relative]["sha256"] == digest:
                cards.append(old[relative])
                reused += 1
                continue
            text = content.decode("utf-8-sig")
            match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
            if not match:
                continue
            metadata = yaml.safe_load(match.group(1))
            if not isinstance(metadata, dict) or not metadata.get("name") or not metadata.get("description"):
                continue
            identifier = "agency-" + re.sub(r"[^a-z0-9_-]+", "-", path.stem.lower()).strip("-")
            if len(identifier) > 80:
                identifier = identifier[:69].rstrip("-") + "-" + hashlib.sha256(relative.encode()).hexdigest()[:10]
            headings = [compact(re.sub(r"[^\w .+#/-]", "", heading), 60)
                        for heading in re.findall(r"^###?\s+(.+)$", match.group(2), re.M)]
            headings = [heading for heading in headings if heading and not any(word in heading.lower() for word in
                        ("identity", "memory", "personality", "communication", "critical rules"))]
            # No long instructions or code blocks in discovery cards. All readable
            # fields together stay below 600 characters (120 + 240 + 180 + 60).
            caps = [compact(directory.replace("-", " "), 60)]
            budget = 180 - len(caps[0])
            for heading in dict.fromkeys(headings):
                if budget < 12:
                    break
                heading = heading[:min(60, budget)]
                caps.append(heading)
                budget -= len(heading)
            cards.append({"id": identifier, "name": compact(metadata["name"], 120),
                          "description": compact(metadata["description"], 240),
                          "capabilities": caps, "deliverables": [], "path": relative, "sha256": digest})
    if len({card["id"] for card in cards}) != len(cards):
        raise ValueError("Duplicate Agency role identifiers")
    index = {"schema_version": SCHEMA, "repository": "msitarzewski/agency-agents", "revision": revision,
             "license": "MIT", "roles": sorted(cards, key=lambda card: card["id"])}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    (output.parent / "AGENCY-LICENSE.txt").write_bytes((checkout / "LICENSE").read_bytes())
    print("Built %s roles (%s unchanged cards reused), revision %s" % (len(cards), reused, revision))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout")
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "agent_team/data/agency-index.json"))
    args = parser.parse_args()
    build(args.checkout, args.output)
