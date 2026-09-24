"""Request store for the credential-request workflow (shared by the CLI and the dashboard API).

A *request* records what the agent needs and where the value should land — never the value.
The browser posts the value straight to its destination (``~/.hermes/.env`` via Hermes's own
writer, or a 0600 file), so a secret exists only in the page, in transit over the LAN, and at
its destination. Nothing here reads a value back.

Store: ``$HERMES_HOME/credential-requests.json`` (0600), atomic replace on every write.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA_VERSION = 1
DEFAULT_TTL_DAYS = 7
DEFAULT_URL_BASE = "http://hermes.local"
TAB_PATH = "/cred-requests"

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# --- paths -------------------------------------------------------------------

def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def store_path() -> Path:
    return hermes_home() / "credential-requests.json"


# --- store io ----------------------------------------------------------------

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _empty_store() -> Dict[str, Any]:
    return {"version": SCHEMA_VERSION, "url_base": DEFAULT_URL_BASE, "requests": []}


def load_store() -> Dict[str, Any]:
    path = store_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("requests"), list):
            data.setdefault("url_base", DEFAULT_URL_BASE)
            data.setdefault("version", SCHEMA_VERSION)
            return data
        raise ValueError("store is not an object with a 'requests' list")
    except FileNotFoundError:
        return _empty_store()
    except Exception:
        # A corrupt store must not take the dashboard or the CLI down; keep the bad file aside.
        try:
            path.rename(path.with_name(path.name + ".corrupt"))
        except OSError:
            pass
        return _empty_store()


def save_store(store: Dict[str, Any]) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# --- destinations ------------------------------------------------------------

def validate_file_target(raw: str) -> str:
    """Absolute path under the user's home, never inside ``$HERMES_HOME`` (env is the way in).

    The *parent* is resolved, so a symlinked directory cannot smuggle the write out of home.
    """
    if not raw:
        raise ValueError("file destination needs a path")
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        raise ValueError(f"file destination must be an absolute path: {raw}")
    parent = candidate.parent
    try:
        parent_resolved = parent.resolve()
    except OSError as exc:
        raise ValueError(f"cannot resolve destination directory {parent}: {exc}") from exc
    home = Path.home().resolve()
    hermes_dir = hermes_home().resolve()
    if parent_resolved != home and home not in parent_resolved.parents:
        raise ValueError(f"file destination must live under {home}: {raw}")
    if parent_resolved == hermes_dir or hermes_dir in parent_resolved.parents:
        raise ValueError("refusing a file destination inside the Hermes home — use an env destination")
    if candidate.is_dir():
        raise ValueError(f"destination is a directory: {raw}")
    return str(parent_resolved / candidate.name)


def normalize_field(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Validate one field spec: ``{name?, label?, hint?, secret?, dest:{kind,target}}``."""
    if not isinstance(spec, dict):
        raise ValueError("each field must be an object")
    dest = spec.get("dest") or {}
    kind = str(dest.get("kind") or "").strip()
    target = str(dest.get("target") or "").strip()
    if kind == "env":
        if not _ENV_NAME_RE.match(target):
            raise ValueError(f"invalid env var name: {target!r}")
    elif kind == "file":
        target = validate_file_target(target)
    else:
        raise ValueError(f"dest.kind must be 'env' or 'file', got {kind!r}")
    name = str(spec.get("name") or (target if kind == "env" else Path(target).name)).strip()
    if not name:
        raise ValueError("field needs a name")
    return {
        "name": name,
        "label": str(spec.get("label") or name),
        "hint": str(spec.get("hint") or ""),
        "secret": bool(spec.get("secret", True)),
        "dest": {"kind": kind, "target": target},
    }


# --- requests ----------------------------------------------------------------

def add_request(
    *,
    title: str,
    why: str = "",
    fields: Iterable[Dict[str, Any]],
    ttl_days: int = DEFAULT_TTL_DAYS,
    requester: str = "agent",
) -> Dict[str, Any]:
    title = str(title or "").strip()
    if not title:
        raise ValueError("a request needs a title")
    normalized = [normalize_field(f) for f in fields]
    if not normalized:
        raise ValueError("a request needs at least one field")
    names = [f["name"] for f in normalized]
    if len(set(names)) != len(names):
        raise ValueError("field names must be unique")
    try:
        ttl = max(1, min(int(ttl_days or DEFAULT_TTL_DAYS), 90))
    except (TypeError, ValueError):
        ttl = DEFAULT_TTL_DAYS

    store = load_store()
    now = utc_now()
    request = {
        "id": f"cr-{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}",
        "created_at": _iso(now),
        "expires_at": _iso(now + timedelta(days=ttl)),
        "title": title,
        "why": str(why or "").strip(),
        "requester": str(requester or "agent"),
        "status": "pending",          # pending | filled | cancelled
        "filled_at": None,
        "cancelled_at": None,
        "note": "",
        "fields": normalized,
        "saved": [],                  # destinations only — never values
    }
    store["requests"].insert(0, request)
    save_store(store)
    return request


def list_requests(*, include_closed: bool = True) -> List[Dict[str, Any]]:
    requests = load_store()["requests"]
    for request in requests:
        request["expired"] = is_expired(request)
    if include_closed:
        return requests
    return [r for r in requests if r.get("status") == "pending" and not r.get("expired")]


def get_request(request_id: str) -> Optional[Dict[str, Any]]:
    for request in load_store()["requests"]:
        if request.get("id") == request_id:
            request["expired"] = is_expired(request)
            return request
    return None


def is_expired(request: Dict[str, Any]) -> bool:
    if request.get("status") != "pending":
        return False
    try:
        expires_at = datetime.fromisoformat(str(request.get("expires_at")))
    except (TypeError, ValueError):
        return False
    return expires_at < utc_now()


def _update(request_id: str, **changes: Any) -> Optional[Dict[str, Any]]:
    store = load_store()
    for request in store["requests"]:
        if request.get("id") == request_id:
            request.update(changes)
            save_store(store)
            return request
    return None


def cancel_request(request_id: str) -> Optional[Dict[str, Any]]:
    return _update(request_id, status="cancelled", cancelled_at=_iso(utc_now()))


def mark_filled(request_id: str, saved: List[Dict[str, str]], note: str = "") -> Optional[Dict[str, Any]]:
    return _update(request_id, status="filled", filled_at=_iso(utc_now()), saved=saved, note=note)


def url_base() -> str:
    return str(load_store().get("url_base") or DEFAULT_URL_BASE).rstrip("/")


def now_iso() -> str:
    return _iso(utc_now())


def record_saved(request_id: str, saved: List[Dict[str, str]], note: str = "") -> Optional[Dict[str, Any]]:
    """Record destinations that were written without closing the request (partial save)."""
    return _update(request_id, saved=saved, note=note)


def deep_link(request_id: str) -> str:
    return f"{url_base()}{TAB_PATH}?req={request_id}"


def pending_count() -> int:
    return len(list_requests(include_closed=False))