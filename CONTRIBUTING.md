# Contributing to hermes-cred-requests

Thanks for taking a look. This is a small, security-adjacent plugin, so the bar for changes to the
write path is deliberately higher than the bar for everything else.

## Ground rules

- **Nothing in this plugin may store, log or return a value.** A value exists in the page, in
  transit, and at its destination. If a change makes a value reachable by either side of the
  request — a response body, the request store, a log line, an error message — it will not be merged.
- **One writer per destination.** Env writes go through `hermes_cli.config.save_env_value`; file
  writes go through `plugin_api._write_secret_file`. Do not add a second path to either.
- **Guards are load-bearing.** Path validation (`credstore.validate_file_target`), the env-name
  pattern, the symlink refusal, `0600`/`0700` modes, single-use on fulfil and expiry all have tests;
  a PR that relaxes one needs to say why, in the PR description.
- **Two dependencies, both optional at runtime.** The plugin itself uses only the standard library,
  FastAPI (already present in the dashboard) and one lazy import of `hermes_cli.config`. Don't add
  runtime dependencies; test-only ones are fine.

## Getting set up

```bash
git clone https://github.com/rosienhg/hermes-cred-requests
cd hermes-cred-requests
python -m venv .venv && . .venv/bin/activate
pip install pytest fastapi httpx

pytest -q
```

Tests never touch your real store or `.env`: the `sandbox` fixture binds `HOME` and `HERMES_HOME` to
a temporary directory, and every fixture that can write depends on it. If you add a fixture that
writes anywhere, make it depend on `sandbox` too — the first version of this suite didn't, and it
wrote nine requests into the author's live store before anyone noticed.

Two test groups:

- `tests/test_store.py` — pure store behaviour, runs anywhere.
- `tests/test_plugin_api.py` — the HTTP surface via a bare `FastAPI` app and `TestClient`. The
  env-destination tests call the real `hermes_cli.config.save_env_value` and skip unless the Hermes
  source tree is importable (`HERMES_REPO`, default `~/.hermes/hermes-agent`).
- `tests/test_packaging.py` — manifests agree, the bundle executes and registers the right name.

## Testing a backend change without restarting the dashboard

Plugin `plugin_api.py` routes mount **once, at dashboard startup**, so a live dashboard will not pick
up your edit. Iterate in-process instead — this is the same load sequence the dashboard performs:

```python
import importlib.util, sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient

path = Path("dashboard/plugin_api.py").resolve()
spec = importlib.util.spec_from_file_location("credreq_api", path)
api = importlib.util.module_from_spec(spec)
sys.modules["credreq_api"] = api          # required: module-level pydantic models resolve by name
spec.loader.exec_module(api)

app = FastAPI()
app.include_router(api.router, prefix="/api/plugins/hermes-cred-requests")
client = TestClient(app)
```

Assert the *destination*, not just the status code: read the file back and check its mode, or read
the env var's key out of `.env`. A 200 proves nothing on its own.

UI changes (`dashboard/dist/index.js`) need no restart — reload the dashboard page, and force
re-discovery with `GET /api/dashboard/plugins/rescan` if the manifest itself changed.

## Layout and the name contract

```
credstore.py             the store + guards (no HTTP, no Hermes import — keep it that way)
__init__.py              CLI registration (hermes credreq …)
dashboard/plugin_api.py  routes; mounted under /api/plugins/<manifest name>/
dashboard/dist/index.js  the tab, as a plain IIFE over window.__HERMES_PLUGIN_SDK__
```

**The plugin name is a contract**: `plugin.yaml:name`, `dashboard/manifest.json:name`, the
`register()` call in the bundle, the directory name, and the `plugins.enabled` entry must all be
`hermes-cred-requests`. The dashboard mounts a user plugin's backend only when the manifest name is
in `plugins.enabled`, and serves it under `/api/plugins/<manifest name>/`, so a mismatch produces a
tab that loads and then cannot reach its backend. `tests/test_packaging.py` enforces this. The tab's
URL path is independent (`/cred-requests`) and stays short on purpose.

## Pull requests

- One concern per PR; say what you changed and how you verified it, with the command and its output.
- Conventional commit subjects (`fix:`, `feat:`, `docs:`, `test:`, `chore:`) — the changelog is
  assembled from them.
- Update `CHANGELOG.md` under `## Unreleased` for anything user-visible.
- Bump nothing but `version` in `plugin.yaml` and `dashboard/manifest.json` (keep them equal) when a
  release is cut.
- Security-relevant changes should say, in the PR body, which guard they touch and why it stays
  intact.
- CI must be green: `pytest -q` on 3.10 and 3.12, `node --check` on the bundle, manifest validation.

## Reporting bugs and vulnerabilities

Bugs and feature ideas: a normal GitHub issue, with your Hermes version (`hermes --version`), the
dashboard's bind/auth mode, and what you expected versus what happened. **Do not paste real
credentials into an issue** — a redacted example is always enough.

Anything that looks like a way to make a value reachable by the agent, the store, a log, or a third
party: see [SECURITY.md](SECURITY.md) and report it privately instead of opening an issue.

## Code style

- Standard library typing (`from __future__ import annotations`), no runtime dependencies.
- Small functions, docstrings that explain *why* (the guards, the atomic write, the lazy import).
- The bundle is ES5-flavoured plain JS on purpose: it is a single file with no build step, loaded
  directly by the dashboard. No `import`, no bundler, no transpile — readable as shipped.
- Comments in the bundle should say what a reviewer cannot infer, not restate the code.