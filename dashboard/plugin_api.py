"""Credential-request dashboard backend, mounted at ``/api/plugins/hermes-cred-requests/``.

The browser posts a filled-in request here and this module writes each value straight to its
destination — ``~/.hermes/.env`` through Hermes's own writer (``hermes_cli.config.save_env_value``,
so quoting, 0600 mode and the in-process env publish are the same as any other key), or a 0600 file.
Values are never returned, never logged and never stored: the request record keeps only *where* a
value went. The dashboard's auth gate covers these routes (an anonymous caller gets a 401 from the
auth middleware before this router is reached).
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter()

MAX_VALUE_BYTES = 16 * 1024
_STORE_MODULE = "hermes_cred_requests_store"


def _store():
    """Load the plugin's store module by path (independent of plugin-import mechanics)."""
    module = sys.modules.get(_STORE_MODULE)
    if module is not None:
        return module
    path = Path(__file__).resolve().parent.parent / "credstore.py"
    spec = importlib.util.spec_from_file_location(_STORE_MODULE, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_STORE_MODULE] = module
    spec.loader.exec_module(module)
    return module


class FulfillBody(BaseModel):
    id: str
    values: Dict[str, str] = Field(default_factory=dict)


class CancelBody(BaseModel):
    id: str


# --- writers -----------------------------------------------------------------

def _write_env(target: str, value: str) -> None:
    from hermes_cli.config import save_env_value

    save_env_value(target, value)


def _write_secret_file(target: str, value: str) -> None:
    """Write exactly the bytes the user typed, 0600, creating the directory 0700 if it is new."""
    path = Path(target)
    if path.is_symlink():
        raise RuntimeError(f"refusing to write through a symlink: {target}")
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value)
    os.chmod(path, 0o600)


# --- routes ------------------------------------------------------------------

@router.get("/requests")
def list_requests() -> Dict[str, Any]:
    store = _store()
    requests = store.list_requests(include_closed=True)
    pending = [r for r in requests if r.get("status") == "pending" and not r.get("expired")]
    return {
        "url_base": store.url_base(),
        "tab_path": store.TAB_PATH,
        "pending_count": len(pending),
        "requests": requests,
    }


@router.post("/fulfill")
def fulfill(body: FulfillBody) -> Dict[str, Any]:
    store = _store()
    request = store.get_request(body.id)
    if request is None:
        raise HTTPException(status_code=404, detail="no such request")
    if request.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"request is already {request.get('status')}")
    if request.get("expired"):
        store.cancel_request(request["id"])
        raise HTTPException(status_code=409, detail="request expired")

    fields: List[Dict[str, Any]] = request.get("fields") or []
    known = {f["name"] for f in fields}
    unknown = [key for key in body.values if key not in known]
    if unknown:
        raise HTTPException(status_code=400, detail="unknown field(s): " + ", ".join(sorted(unknown)))
    missing = [f["label"] for f in fields if not str(body.values.get(f["name"], "")).strip()]
    if missing:
        raise HTTPException(status_code=400, detail="still missing: " + ", ".join(missing))
    oversized = [f["label"] for f in fields if len(body.values[f["name"]].encode("utf-8")) > MAX_VALUE_BYTES]
    if oversized:
        raise HTTPException(status_code=400, detail="too long: " + ", ".join(oversized))

    saved: List[Dict[str, str]] = []
    failures: List[str] = []
    for field in fields:
        value = body.values[field["name"]]
        dest = field["dest"]
        try:
            if dest["kind"] == "env":
                _write_env(dest["target"], value)
            else:
                _write_secret_file(dest["target"], value)
            saved.append({"field": field["name"], "dest": f"{dest['kind']}:{dest['target']}",
                          "at": store.now_iso()})
        except Exception as exc:  # noqa: BLE001 — surfaced to the user, values never included
            log.warning("cred-requests: write failed for %s -> %s: %s", field["name"], dest, exc)
            failures.append(f"{field['label']}: {exc}")

    if failures:
        if saved:
            store.record_saved(request["id"], saved, note="partial save: " + "; ".join(failures))
        raise HTTPException(status_code=500, detail="could not save — " + "; ".join(failures))

    store.mark_filled(request["id"], saved)
    body.values.clear()
    return {"ok": True, "saved": [{"field": s["field"], "dest": s["dest"]} for s in saved]}


@router.post("/cancel")
def cancel(body: CancelBody) -> Dict[str, Any]:
    store = _store()
    request = store.cancel_request(body.id)
    if request is None:
        raise HTTPException(status_code=404, detail="no such request")
    return {"ok": True, "id": request["id"], "status": request["status"]}