# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-09-24

First release.

### Added

- **Dashboard tab** (*Credential Requests*, `/cred-requests`, after *Sessions*): pending requests as
  fillable cards with masked inputs, a per-field reveal, pending/history sections, a 15-second
  refresh, and a deep-link highlight for `?req=<id>`.
- **`hermes credreq` CLI**: `add`, `list`, `show`, `cancel`, `url` — files a request, prints the
  destinations and the deep link to hand over.
- **Two destination kinds**: an env var written to `~/.hermes/.env` through Hermes's own writer, or a
  file written `0600` with exactly the bytes typed (parent directory created `0700` when new).
- **Multi-field requests** via `--spec` JSON, for credential pairs (client id + secret, username +
  password) and per-field hints.
- **Store** at `$HERMES_HOME/credential-requests.json` (`0600`, atomic replace) holding destinations
  and timestamps only — never a value.
- **Guards**: absolute-path and `$HOME` confinement on file destinations, refusal inside
  `$HERMES_HOME`, refusal to write through a symlink, POSIX env-name validation, `16 KiB` per value,
  single-use fulfil (409 on repeat), expiry (`ttl_days`, default 7, clamped to 90), and a
  `*.corrupt` fallback so a damaged store cannot take the dashboard down.
- **Backend routes** under `/api/plugins/hermes-cred-requests/` (`GET /requests`, `POST /fulfill`,
  `POST /cancel`), behind the dashboard's auth gate, that write server-side so the value never
  reaches the agent's context.
- **Tests** (36) covering the store, guards, lifecycle, both destinations, the single-use contract,
  partial-save handling, manifest/bundle consistency; plus CI (pytest on 3.10 and 3.12, `node --check`
  on the bundle, manifest and name-contract validation).

[Unreleased]: https://github.com/rosienhg/hermes-cred-requests/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/rosienhg/hermes-cred-requests/releases/tag/v1.0.0