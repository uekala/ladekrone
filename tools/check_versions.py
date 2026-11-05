#!/usr/bin/env python3
"""Check that the Home Assistant manifest, changelog and release tag agree."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads(
    (ROOT / "custom_components" / "ladekrone" / "manifest.json").read_text(encoding="utf-8")
)
version = manifest.get("version")
if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
    raise SystemExit(f"Invalid manifest version: {version!r}")

changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
headings = re.findall(r"^##\s+(\d+\.\d+\.\d+)(?:\s|$)", changelog, re.MULTILINE)
if not headings:
    raise SystemExit("CHANGELOG.md has no version heading")
if headings[0] != version:
    raise SystemExit(f"CHANGELOG.md starts at {headings[0]}, but manifest.json says {version}")

ref = os.environ.get("GITHUB_REF", "")
if ref.startswith("refs/tags/"):
    tag_version = ref.removeprefix("refs/tags/").removeprefix("v")
    if tag_version != version:
        raise SystemExit(f"Tag {ref!r} does not match manifest version {version}")

print(f"Ladekrone version {version}: manifest, changelog and tag are consistent.")
