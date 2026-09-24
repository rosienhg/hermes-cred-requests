"""Packaging contract: the names agree, the declared files exist, the bundle really registers.

The plugin name is a contract across five places (plugin.yaml, the dashboard manifest, the bundle's
`register()` call, the directory name, and the `plugins.enabled` entry). The dashboard mounts a user
plugin's backend only when the manifest name is enabled and serves it under
`/api/plugins/<manifest name>/`, so a mismatch yields a tab that loads and then cannot reach its
backend — the kind of failure that is invisible until someone uses it. Hence a test.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import PLUGIN_ROOT

EXPECTED_NAME = "hermes-cred-requests"


def _manifest() -> dict:
    return json.loads((PLUGIN_ROOT / "dashboard" / "manifest.json").read_text(encoding="utf-8"))


def _plugin_yaml() -> dict:
    """Minimal top-level `key: value` reader — the repo has no YAML runtime dependency."""
    fields = {}
    for line in (PLUGIN_ROOT / "plugin.yaml").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith((" ", "#")) and ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip().strip('"')
    return fields


def test_directory_name_matches_the_plugin_name():
    assert PLUGIN_ROOT.name == EXPECTED_NAME, (
        f"this plugin must be installed as a directory named {EXPECTED_NAME!r}; "
        f"found {PLUGIN_ROOT.name!r} — rename it or the dashboard will not mount the backend"
    )


def test_plugin_yaml_and_dashboard_manifest_agree():
    assert _plugin_yaml()["name"] == _manifest()["name"] == EXPECTED_NAME


def test_manifests_declare_what_the_dashboard_needs():
    manifest = _manifest()
    assert manifest["tab"]["path"].startswith("/")
    assert manifest["entry"] and (PLUGIN_ROOT / "dashboard" / manifest["entry"]).is_file()
    assert manifest["api"] and (PLUGIN_ROOT / "dashboard" / manifest["api"]).is_file()
    assert manifest["icon"] == "KeyRound"

    yaml_fields = _plugin_yaml()
    assert yaml_fields["version"] == manifest["version"]
    assert yaml_fields["requires_hermes"].startswith(">=")
    assert yaml_fields["kind"] == "standalone"


def test_bundle_executes_and_registers_the_manifest_name(tmp_path):
    """Run the shipped bundle under node with a stubbed SDK — it must register exactly once, under
    the manifest's name (that name is also the backend's URL prefix)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the bundle smoke test needs it")

    driver = tmp_path / "driver.js"
    driver.write_text(
        """
const fs = require("fs");
const manifest = JSON.parse(fs.readFileSync("dashboard/manifest.json", "utf8"));
const registered = [];
const slots = [];
global.window = {
  __HERMES_PLUGIN_SDK__: { React: { createElement: () => null }, hooks: {}, components: {}, utils: {} },
  __HERMES_PLUGINS__: {
    register: (name) => registered.push(name),
    registerSlot: (name, slot) => slots.push([name, slot]),
  },
};
eval(fs.readFileSync("dashboard/dist/index.js", "utf8"));
if (registered.length !== 1) throw new Error("expected exactly one register() call, got " + registered.length);
if (registered[0] !== manifest.name) throw new Error("registered as " + registered[0] + ", manifest says " + manifest.name);
console.log(JSON.stringify({ registered, slots, api: "/api/plugins/" + manifest.name }));
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [node, str(driver)], cwd=PLUGIN_ROOT, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["registered"] == [EXPECTED_NAME]
    assert payload["api"] == f"/api/plugins/{EXPECTED_NAME}"


def test_bundle_never_touches_a_value_in_the_page_flow():
    """Cheap invariant worth keeping: the tab posts values and reads none back — no `reveal`, no
    value-bearing GET, and no secret persisted in local/session storage."""
    bundle = (PLUGIN_ROOT / "dashboard" / "dist" / "index.js").read_text(encoding="utf-8")
    for forbidden in ("localStorage", "sessionStorage", "/reveal", "document.cookie"):
        assert forbidden not in bundle, f"{forbidden} must not appear in the tab bundle"