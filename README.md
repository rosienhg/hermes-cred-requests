# hermes-cred-requests

**Hand your agent a secret without ever pasting it into the chat.**

A [Hermes Agent](https://hermes-agent.nousresearch.com/docs/) dashboard plugin. When the agent needs
a credential — an API key, a password, a token, a service-account file — it *files a request*. You
open the dashboard tab, type the value into a masked field, hit save, and the value is written
straight to its destination: an environment variable in `~/.hermes/.env`, or a `0600` file.

The value never enters the conversation, never enters the agent's context, and is never stored by
the plugin. The agent learns only *that* it arrived.

```
  agent                                     you
    │                                        │
    │  hermes credreq add --env ACME_API_KEY │
    │───────────────────────────────────────▶│   request queued (name + destination only)
    │                                        │
    │  "I need an Acme API key:              │
    │   http://mybox.local/cred-requests     │
    │   ?req=cr-20260924-105601-7470"        │
    │───────────────────────────────────────▶│   tap the deep link
    │                                        │   type the value into the masked field
    │                                        │   press Save
    │                                        │        │
    │                                        │        ▼
    │                                        │   POST /api/plugins/hermes-cred-requests/fulfill
    │                                        │        │
    │                                        │        ▼
    │  ACME_API_KEY=… in ~/.hermes/.env ◀────┼── server-side write (0600)
    │  (by name, never by value)             │   value goes no further
```

The same tab works when you are driving the agent from a phone over a messaging platform, which is
where it earns its keep: the reply carries the link, you tap it, and the password prompt that used
to be "SSH in and paste this command" is now one field on a web page.

## Why this exists

The usual ways to give an agent a credential are all bad:

- **Paste it in chat** — it lands in the transcript, the session store, the model context and every
  log that copies them. Rotating it afterwards is the responsible move, which means you do it often
  and resentfully.
- **Give the agent your password manager** — one credential now unlocks everything, and the agent
  holds it.
- **Type into the agent's own UI while it watches** — fine when you are sitting in front of it, no
  help at all when you are on your phone.

This plugin makes the *request* the agent's job and the *value* yours, with the narrowest possible
channel between them: a name, a destination, and a masked input on a page you already trust.

## What is protected, and what is not

Being explicit, because this is a credential path:

**Protected**

- The value is not in the agent's context, the conversation, the session database, or the plugin's
  store — the request record keeps destinations and timestamps only.
- The write happens in the dashboard backend, not in the agent's terminal session.
- The routes sit behind the dashboard's own authentication (anonymous callers get a 401 before the
  plugin is reached).
- Destination writes are `0600`; a new parent directory is created `0700`.
- Writes through a symlink are refused, so a planted link cannot redirect the value elsewhere.
- File destinations must be absolute, must resolve inside your home directory, and are refused
  inside `$HERMES_HOME` (use an env destination for that — it keeps the Hermes home to one writer).
- Requests expire (7 days by default) and are single-use: a second save is rejected rather than
  silently overwriting the first.

**Not protected**

- **The transport.** The dashboard serves plain HTTP on your LAN by default. On a WPA2/WPA3 home
  network that is the same trust level as your other local traffic, but it is not TLS. If the
  dashboard is reachable by anyone you would not hand the password to, it is reachable by them here
  too. For anything beyond a trusted network, put TLS and an identity provider in front of the
  dashboard (Cloudflare Tunnel + Access, or a self-hosted OIDC provider) before you use this tab.
- **Your browser, the dashboard process, and their memory.** The value is typed into a page and
  posted by that page. A compromised browser or a compromised dashboard host gets the value.
- **The destination.** Once written, the value lives wherever you sent it, with the protection that
  destination has. `~/.hermes/.env` is protected by file mode and the Hermes home's permissions.
- **Revocation.** The plugin cannot revoke anything. Prefer credentials you can name and rotate per
  service, and rotate them if you change your mind about the agent having them.

## Install

Requires Hermes Agent `>= 0.21.0` and the dashboard extras (`hermes dashboard` must run — see the
[Hermes docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard)).

```bash
# From the plugin catalog / git, straight into the plugin directory (recommended)
hermes plugins install rosienhg/hermes-cred-requests --enable

# …or by hand, which is the same thing with more typing
git clone https://github.com/rosienhg/hermes-cred-requests ~/.hermes/plugins/hermes-cred-requests
hermes plugins enable hermes-cred-requests
```

The **directory name must be `hermes-cred-requests`** — the dashboard mounts a user plugin's backend
only when the plugin is enabled under the name the directory resolves to. If the tab loads but shows
"could not reach the backend", that mismatch is almost always why.

Restart the dashboard so the backend routes mount:

```bash
sudo systemctl restart hermes-dashboard.service     # system service
# or: hermes dashboard                                # if you run it in the foreground
```

The **Credential Requests** tab now appears in the dashboard navigation (after *Sessions*).
UI-only changes to this plugin need only a page reload; the backend mounts at startup.

### Point the links at something your phone can reach

Request links are built from a base URL, default `http://hermes.local` (the mDNS name of the box
running Hermes). Set it to whatever your devices actually use:

```bash
hermes credreq url                          # show the current base and tab URL
hermes credreq url http://192.168.1.50      # LAN IP
hermes credreq url https://hermes.example.com
```

Sign in to the dashboard once on your phone so the link opens the tab instead of the login page.

## Using it

### Agent side

```bash
# one env var
hermes credreq add --title "Acme API key" --why "to call the Acme API for you" \
    --env ACME_API_KEY

# one file, written exactly as typed, 0600
hermes credreq add --title "Deploy token" --why "to push releases" \
    --file ~/.config/acme/deploy-token:Deploy token

# several values at once (client id + secret, username + password, …)
hermes credreq add --spec examples/acme-api.spec.json
```

Each `add` prints the request id, where each value will land, and the deep link to hand over. In a
terminal session you pass the link on; from a messaging session the link goes in the reply; from a
cron job or a script, `hermes send -t <platform> "…"` delivers it.

### Your side

Open the link, type the values, press **Save securely**. The request card turns into a green
confirmation naming the destinations, and the pending list updates for every other open tab within
15 seconds.

The tab shows three things: **pending** requests as fillable cards, a **history** list of filled,
cancelled and expired requests (titles and destinations, never values), and a note on how env
values are picked up.

### CLI reference

| Command | What it does |
| --- | --- |
| `hermes credreq add --title … --env VAR[:Label]` | Queue a request writing an env var to `~/.hermes/.env` |
| `hermes credreq add --title … --file PATH[:Label]` | Queue a request writing a file (absolute path, or `~`-relative) |
| `hermes credreq add --spec FILE` | Queue a multi-field request from JSON (`-` reads stdin) |
| `hermes credreq list [--all] [--json]` | Pending requests by default; `--all` includes closed ones |
| `hermes credreq show ID [--json]` | One request, with destinations and timestamps |
| `hermes credreq cancel ID` | Close a pending request |
| `hermes credreq url [BASE]` | Show or set the base URL used in links |

`add` flags: `--title`, `--why`, `--requester`, `--ttl-days` (default 7, clamped to 90), `--env`,
`--file`, `--spec`, `--json`.

### Request spec

```json
{
  "title": "Acme API credentials",
  "why": "so I can call the Acme API on your behalf",
  "ttl_days": 7,
  "fields": [
    {
      "name": "client_id",
      "label": "Client ID",
      "secret": false,
      "hint": "the public identifier, from the Acme dashboard",
      "dest": { "kind": "env", "target": "ACME_CLIENT_ID" }
    },
    {
      "name": "client_secret",
      "label": "Client secret",
      "dest": { "kind": "env", "target": "ACME_CLIENT_SECRET" }
    }
  ]
}
```

`secret` defaults to `true` (masked input with a per-field reveal); `hint` is shown under the label;
`dest.kind` is `env` or `file`. See [`examples/acme-api.spec.json`](examples/acme-api.spec.json).

### Where values land

| Destination | Behaviour |
| --- | --- |
| `env` | Written with Hermes's own writer (`hermes_cli.config.save_env_value`), so quoting, file mode and the in-process env publish match every other key. A new session loads it at startup; a session that is already running needs `/reload`, or source it in the command that needs it (`set -a; . ~/.hermes/.env; set +a`). |
| `file` | Exactly the bytes you typed — no newline added. `0600`, parent directory created `0700` if new. |

Request state lives in `$HERMES_HOME/credential-requests.json` (`0600`), including the `url_base`
you set. Delete it to start fresh; a corrupt file is renamed to `*.corrupt` rather than breaking the
dashboard.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| No **Credential Requests** tab | Plugin not enabled (`hermes plugins enable hermes-cred-requests`), or the manifest isn't at `~/.hermes/plugins/hermes-cred-requests/dashboard/manifest.json`. Force a rescan with `curl -s localhost:9119/api/dashboard/plugins/rescan` (add your auth) and reload the page. |
| Tab loads, says "could not reach the backend" | The backend routes are not mounted: enable the plugin under the exact directory name and restart the dashboard. `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9119/api/plugins/hermes-cred-requests/requests` returns **401** when mounted behind the auth gate and **404** when not mounted. |
| Link opens the login page | Sign in on that device once; the deep link then resumes. |
| Link doesn't open at all off your home network | The default base is an mDNS `.local` name, which is LAN-only. Point it at a name that resolves from where you are (`hermes credreq url`). |
| "still missing: …" on save | Every field in the request must be filled; a request is all-or-nothing unless one destination fails mid-write. |
| "request is already filled" | Requests are single-use. File a new one. |
| A partial save happened | The response and the request's history line name what landed; fix the failing destination and file a new request for it. |
| Env value "not visible" to the agent | The running session predates the write: `/reload`, or source `.env` in the command. New sessions pick it up automatically. |

## Development

```bash
git clone https://github.com/rosienhg/hermes-cred-requests
cd hermes-cred-requests
python -m venv .venv && . .venv/bin/activate
pip install pytest fastapi httpx        # httpx is what FastAPI's TestClient needs

pytest -q          # 36 tests; env-destination tests skip unless the Hermes tree is importable
```

Tests bind `HOME` and `HERMES_HOME` to a temporary directory, so they never touch your real store or
`.env`. The env-destination tests additionally exercise the real `hermes_cli.config.save_env_value`
and run when the Hermes source tree is present (point `HERMES_REPO` at it if it isn't at
`~/.hermes/hermes-agent`).

The backend is testable without a dashboard restart — load `dashboard/plugin_api.py` by path, mount
its `router` in a bare FastAPI app, and drive it with `TestClient`. See `CONTRIBUTING.md`.

```
hermes-cred-requests/
├── plugin.yaml                 plugin manifest (name, version, requires_hermes)
├── __init__.py                 `hermes credreq` CLI, registered via ctx.register_cli_command
├── credstore.py                the request store + destination guards (no HTTP, no Hermes import)
├── dashboard/
│   ├── manifest.json           tab config: /cred-requests, after:sessions, icon KeyRound
│   ├── plugin_api.py           routes under /api/plugins/hermes-cred-requests/
│   └── dist/index.js           the tab UI — a plain IIFE over window.__HERMES_PLUGIN_SDK__
├── examples/acme-api.spec.json
└── tests/
```

No build step: the dashboard plugin is a hand-written bundle using the Plugin SDK
(`window.__HERMES_PLUGIN_SDK__`), so the file you read is the file that runs.

## Uninstall

```bash
hermes plugins disable hermes-cred-requests
rm -rf ~/.hermes/plugins/hermes-cred-requests
rm -f ~/.hermes/credential-requests.json
```

Credentials you already handed over stay where they were written — remove the env vars from
`~/.hermes/.env` and delete the file destinations yourself. Rotate anything you no longer want the
agent to hold.

## License

MIT — see [LICENSE](LICENSE).

Maintainers: [@rosienhg](https://github.com/rosienhg), [@nickkhg](https://github.com/nickkhg),
[@srgrn](https://github.com/srgrn). Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).