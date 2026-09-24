#!/usr/bin/env python3
"""Validate the plugin manifests and the name contract.

The plugin name is load-bearing in four places: ``plugin.yaml``, the dashboard manifest, the
directory name and the ``plugins.enabled`` entry. The dashboard mounts a user plugin's backend only
when the manifest name is in ``plugins.enabled`` and serves it under ``/api/plugins/<manifest
name>/``, so a mismatch produces a tab that renders and then cannot reach its backend.

    python scripts/check_manifests.py [plugin-root]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - CI installs pyyaml; the reader below is dependency-free
    yaml = None


def read_plugin_yaml(path: Path) -> dict:
    """Top-level `key: value` reader, so this script needs no YAML dependency to be useful."""
    if yaml is not None:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    fields = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith((" ", "#")) and ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip().strip('"')
    return fields


def main(argv: list) -> int:
    root = Path(argv[1] if len(argv) > 1 else ".").resolve()
    manifest = json.loads((root / "dashboard" / "manifest.json").read_text(encoding="utf-8"))
    plugin = read_plugin_yaml(root / "plugin.yaml")

    problems = []
    if plugin.get("name") != manifest.get("name"):
        problems.append(f"plugin.yaml name={plugin.get('name')!r} != manifest name={manifest.get('name')!r}")
    if root.name != manifest.get("name"):
        problems.append(
            f"directory {root.name!r} != plugin name {manifest.get('name')!r} "
            "(the dashboard mounts a user plugin's backend by that name)"
        )
    if plugin.get("version") != manifest.get("version"):
        problems.append(f"version mismatch: plugin.yaml {plugin.get('version')!r} vs manifest {manifest.get('version')!r}")
    if not str(manifest.get("tab", {}).get("path", "")).startswith("/"):
        problems.append("manifest tab.path must start with '/'")
    for key in ("entry", "api"):
        rel = manifest.get(key)
        if not rel:
            problems.append(f"manifest is missing '{key}'")
        elif not (root / "dashboard" / rel).is_file():
            problems.append(f"declared file missing: dashboard/{rel}")

    if problems:
        print("manifest check failed:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"name contract ok: {manifest['name']} v{manifest['version']} (tab {manifest['tab']['path']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))