# Security policy

## Reporting a vulnerability

Report privately through GitHub's [private vulnerability
reporting](https://github.com/rosienhg/hermes-cred-requests/security/advisories/new) rather than a
public issue. Expect an acknowledgement within a few days.

Please include the version (`plugin.yaml`), how the dashboard is bound and authenticated, and the
smallest reproduction you can manage. **Never include a real credential** — a dummy value that shows
the same path is enough.

## What counts as a vulnerability here

This plugin moves a secret from a browser to a destination on disk. The interesting failure modes
are therefore about *reach* and *placement*:

- a value becoming reachable by the agent (response body, request store, log line, error message,
  session context, a file the agent reads back);
- a value landing somewhere other than the destination the request named — including through a
  symlink, a path-traversal in a destination, or a race between validation and write;
- a destination being writable with wider permissions than `0600`, or a new parent directory wider
  than `0700`;
- a request being fulfilable more than once, after expiry, or by an unauthenticated caller;
- a request filed by the agent that writes outside the validation rules (absolute path under
  `$HOME`, never inside `$HERMES_HOME`).

## What is out of scope

These are documented design decisions, not vulnerabilities (see the README's "What is protected, and
what is not"):

- **Plain HTTP on a trusted LAN.** The dashboard serves HTTP unless you put TLS in front of it. Auth
  is the control; the plugin inherits whatever the dashboard has. Reports that a LAN attacker can
  read plaintext traffic are expected behaviour of the default dashboard configuration.
- **A compromised browser or dashboard host.** The value is typed into the page and posted by it; if
  either end is owned, the value is owned.
- **The agent knowing a destination exists.** Request titles, `why` text and destinations are
  deliberately visible to both sides — that is what the request is.
- **No revocation.** The plugin cannot un-issue a credential you handed over. Rotate it at the
  source.
- **Values stored at the destination.** Once written, protection is the destination's
  (`~/.hermes/.env` at `0600`, or your file's own permissions).

## Supported versions

The latest `main` and the most recent tagged release receive fixes. This is a small plugin; there are
no backports to older releases.