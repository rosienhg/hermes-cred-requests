"""Shared fixtures: load the plugin's modules by path, in an isolated HERMES_HOME.

Nothing here needs the Hermes source tree. Tests that exercise the *env* destination
(``hermes_cli.config.save_env_value``) request the ``hermes_config`` fixture, which skips when the
Hermes source tree is not importable — see CONTRIBUTING.md.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
HERMES_REPO = Path(os.environ.get("HERMES_REPO", Path.home() / ".hermes" / "hermes-agent"))

API_PREFIX = "/api/plugins/hermes-cred-requests"


def load_module(name: str, path: Path):
    """Import a file as a module, registering it in sys.modules first (pydantic needs that to
    resolve the module's own string annotations)."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def store_module():
    return load_module("hermes_cred_requests_store", PLUGIN_ROOT / "credstore.py")


@pytest.fixture(scope="session")
def api():
    return load_module("hermes_cred_requests_api_under_test", PLUGIN_ROOT / "dashboard" / "plugin_api.py")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A throwaway HOME + HERMES_HOME, so env and file destinations stay inside tmp_path."""
    home = tmp_path / "home"
    (home / ".hermes").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HERMES_HOME", str(home / ".hermes"))
    return home


@pytest.fixture
def store(store_module, sandbox):
    """The store module, always bound to the sandboxed HERMES_HOME — never the real one."""
    return store_module


@pytest.fixture
def client(api, sandbox):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(api.router, prefix=API_PREFIX)
    return TestClient(app)


@pytest.fixture
def hermes_config(sandbox):
    """The real Hermes config module (needed for env destinations), or skip."""
    if str(HERMES_REPO) not in sys.path:
        sys.path.insert(0, str(HERMES_REPO))
    module = pytest.importorskip(
        "hermes_cli.config",
        reason=f"Hermes source tree not importable from {HERMES_REPO} (set HERMES_REPO)",
    )
    return module


def make_request(store, **overrides):
    """A one-field request pointing at an env var, with overridable everything."""
    params = {
        "title": "Test request",
        "why": "because the test says so",
        "fields": [{"name": "TOKEN", "label": "Token", "dest": {"kind": "env", "target": "TEST_TOKEN"}}],
    }
    params.update(overrides)
    return store.add_request(**params)


def file_field(path, label="Token file", name="token"):
    return {"name": name, "label": label, "dest": {"kind": "file", "target": str(path)}}