"""``hermes credreq`` — file a credential request for the user to fill in on the dashboard tab.

The agent (or a cron job, or a script) files a request here; the user opens the deep link, types
the secret into the Credential Requests tab, and the value goes straight to its destination
(``~/.hermes/.env`` or a 0600 file). Nothing in this path ever carries a value: the request record
holds only the *where*, and the browser posts the value to the dashboard backend.

    hermes credreq add --title "Mailbox password" --why "to read your mail" \
        --env MAILBOX_PASSWORD
    hermes credreq add --title "Deploy token" --why "to push releases" \
        --file ~/.config/acme/deploy-token:Deploy token
    hermes credreq list --json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_STORE_MODULE = "hermes_cred_requests_store"


def _store():
    """Load credstore.py by path — independent of how the host imported this plugin."""
    module = sys.modules.get(_STORE_MODULE)
    if module is not None:
        return module
    path = Path(__file__).resolve().parent / "credstore.py"
    spec = importlib.util.spec_from_file_location(_STORE_MODULE, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_STORE_MODULE] = module
    spec.loader.exec_module(module)
    return module


def _split_label(raw: str, default_label: str) -> tuple:
    """``VALUE:Label`` -> (value, label); a bare value keeps the default label."""
    if ":" in raw:
        value, _, label = raw.partition(":")
        return value.strip(), (label.strip() or default_label)
    return raw.strip(), default_label


def _fields_from_args(args) -> List[Dict[str, Any]]:
    fields: List[Dict[str, Any]] = []
    for raw in args.env or []:
        target, label = _split_label(raw, "")
        fields.append({"name": target, "label": label or target, "secret": True,
                       "dest": {"kind": "env", "target": target}})
    for raw in args.file or []:
        target, label = _split_label(raw, "")
        fields.append({"name": Path(target).name, "label": label or Path(target).name, "secret": True,
                       "dest": {"kind": "file", "target": target}})
    return fields


def _fields_from_spec(spec_path: str) -> Dict[str, Any]:
    raw = sys.stdin.read() if spec_path == "-" else Path(spec_path).expanduser().read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("spec must be a JSON object")
    return data


def cmd_add(args) -> int:
    store = _store()
    spec: Dict[str, Any] = {}
    if args.spec:
        spec = _fields_from_spec(args.spec)
    title = args.title or spec.get("title") or ""
    why = args.why or spec.get("why") or ""
    fields = _fields_from_args(args) + list(spec.get("fields") or [])
    payload = {
        "title": title,
        "why": why,
        "requester": args.requester,
        "ttl_days": args.ttl_days if args.ttl_days is not None else spec.get("ttl_days", 7),
        "fields": fields,
    }
    try:
        request = store.add_request(**payload)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    link = store.deep_link(request["id"])
    if args.json:
        print(json.dumps({"id": request["id"], "title": request["title"], "link": link,
                          "fields": [{"name": f["name"], "dest": f["dest"]} for f in request["fields"]],
                          "expires_at": request["expires_at"]}, indent=2))
        return 0
    print(f"request {request['id']} created: {request['title']}")
    for field in request["fields"]:
        dest = field["dest"]
        where = f"env {dest['target']}" if dest["kind"] == "env" else f"file {dest['target']}"
        print(f"  - {field['label']}  ->  {where}")
    print(f"\nfill it in here: {link}")
    return 0


def _print_request(request: Dict[str, Any], *, verbose: bool = False) -> None:
    store = _store()
    status = request.get("status", "pending")
    if request.get("expired"):
        status = "expired"
    print(f"{request['id']}  [{status}]  {request['title']}")
    if request.get("why"):
        print(f"    why: {request['why']}")
    print(f"    created {request.get('created_at', '')}  expires {request.get('expires_at', '')}")
    for field in request.get("fields", []):
        dest = field["dest"]
        where = f"env {dest['target']}" if dest["kind"] == "env" else f"file {dest['target']}"
        print(f"    wishes: {field['label']} ({field['name']}) -> {where}")
    for entry in request.get("saved", []):
        print(f"    saved {entry.get('field')} -> {entry.get('dest')} at {entry.get('at')}")
    if request.get("note"):
        print(f"    note: {request['note']}")
    if status == "pending":
        print(f"    link: {store.deep_link(request['id'])}")


def cmd_list(args) -> int:
    store = _store()
    requests = store.list_requests(include_closed=bool(args.all))
    if args.json:
        print(json.dumps({"url_base": store.url_base(), "pending": store.pending_count(),
                          "requests": requests}, indent=2))
        return 0
    if not requests:
        print("no credential requests")
        return 0
    for request in requests:
        _print_request(request)
    return 0


def cmd_show(args) -> int:
    store = _store()
    request = store.get_request(args.request_id)
    if request is None:
        print(f"error: no request {args.request_id}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(request, indent=2))
        return 0
    _print_request(request, verbose=True)
    return 0


def cmd_cancel(args) -> int:
    store = _store()
    request = store.cancel_request(args.request_id)
    if request is None:
        print(f"error: no request {args.request_id}", file=sys.stderr)
        return 1
    print(f"cancelled {request['id']} ({request['title']})")
    return 0


def cmd_url(args) -> int:
    """Show or set the base URL used in the links handed to the user."""
    store = _store()
    if args.base:
        base = args.base.strip().rstrip("/")
        if not base.startswith(("http://", "https://")):
            print("error: base must start with http:// or https://", file=sys.stderr)
            return 1
        data = store.load_store()
        data["url_base"] = base
        store.save_store(data)
    print(f"link base: {store.url_base()}")
    print(f"tab:       {store.url_base()}{store.TAB_PATH}")
    return 0


def setup_parser(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", required=True)

    add = actions.add_parser("add", help="File a request for a secret")
    add.add_argument("--title", help="What this secret is (short, human)")
    add.add_argument("--why", default="", help="One line on why it is needed / what it unlocks")
    add.add_argument("--requester", default="agent", help="Who is asking (default: agent)")
    add.add_argument("--ttl-days", type=int, default=None, help="Expire the request after N days (default 7)")
    add.add_argument("--env", action="append", default=[],
                     help="Env var destination as VAR[:Label]; repeatable. Written to ~/.hermes/.env")
    add.add_argument("--file", action="append", default=[],
                     help="File destination as ABSOLUTE_PATH[:Label]; repeatable. Written 0600")
    add.add_argument("--spec", help="JSON spec file (or '-' for stdin) with title/why/ttl_days/fields")
    add.add_argument("--json", action="store_true", help="Machine-readable output")

    listing = actions.add_parser("list", help="List requests")
    listing.add_argument("--all", action="store_true", help="Include filled and cancelled requests")
    listing.add_argument("--json", action="store_true", help="Machine-readable output")

    show = actions.add_parser("show", help="Show one request")
    show.add_argument("request_id")
    show.add_argument("--json", action="store_true", help="Machine-readable output")

    cancel = actions.add_parser("cancel", help="Cancel a pending request")
    cancel.add_argument("request_id")

    url = actions.add_parser("url", help="Show or set the base URL used in request links")
    url.add_argument("base", nargs="?", help="e.g. http://mybox.local or https://hermes.example.com")


def run(args) -> int:
    handlers = {"add": cmd_add, "list": cmd_list, "show": cmd_show, "cancel": cmd_cancel, "url": cmd_url}
    return handlers[args.action](args)


def register(ctx) -> None:
    ctx.register_cli_command(
        name="credreq",
        help="Ask the user for a secret via the dashboard's Credential Requests tab",
        setup_fn=setup_parser,
        handler_fn=run,
        description=(
            "File, list and cancel credential requests. A request names what is needed and where "
            "the value should land (an env var in ~/.hermes/.env, or a 0600 file); the user fills "
            "it in on the dashboard tab reached by the printed deep link, and the value never "
            "enters the agent conversation."
        ),
    )