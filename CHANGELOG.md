# Changelog

All notable changes to VardrRunner are documented here.
This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Per-version detail notes live in [`changelog/`](changelog/).

## [Unreleased]
### Changed
- **Resilient API client.** The HTTP session now retries transient failures
  (connection errors and 429/500/502/503/504) with exponential backoff, so a
  long-running daemon survives network blips and brief backend restarts. Retries
  are limited to idempotent methods — POST/PATCH are never auto-retried, so a
  dropped response can't cause a double-claim, double-import, or duplicate event.
  Retry count and backoff are constructor-configurable.
- Requests now send a `User-Agent: vardrrunner/<version> (<os>)` header so the
  backend can attribute traffic to a runner and version.

## [0.18.0] — 2026-06-14
First release from the standalone repository. See
[changelog/v0.18.0.md](changelog/v0.18.0.md) for detail.

### Changed
- Extracted VardrRunner into its own repository from the VardrMap monorepo, preserving
  full commit history via `git subtree split`. See
  [docs/adr/0001-extract-vardrrunner-from-vardrmap.md](docs/adr/0001-extract-vardrrunner-from-vardrmap.md).
- **Corrected the package version** from a misleading `0.1.0` to `0.18.0` (the package
  already carried v0.17.x of features). Version is now single-sourced from
  `vardrrunner/__init__.py` and read dynamically by `pyproject.toml`; the heartbeat reports it.
- Replaced `pyflakes` with **ruff** (lint + format) and added **mypy** type checking; all
  three plus coverage now run in CI on Python 3.10–3.12.

### Added
- Standalone repo scaffolding: `CLAUDE.md` (with the shared VardrSec Engineering Charter),
  `README.md`, `docs/` (architecture, development, CLI reference, ADRs), `changelog/`,
  CI workflow, and `.gitignore`.
- `LICENSE` (MIT).
- `[project.optional-dependencies] dev` extra in `pyproject.toml` — `pip install -e ".[dev]"`.

---

## History before extraction
The features below shipped while VardrRunner lived inside the VardrMap repo. They are
recorded here for continuity; their commits are present in this repo's history.

### v0.17.1 — Daemon Windows fixes
- ctypes liveness probe (Windows `os.kill` was terminating the daemon)
- PID-file-removal graceful stop protocol; `DETACHED_PROCESS` detach; double-start guard

### v0.17.0 — Daemon
- `daemon start/stop/status`; polls jobs every 5 s, heartbeats every 60 s on a dedicated
  thread; `--detach` background mode with PID file; graceful SIGTERM shutdown
- Extracted `execute_pending_jobs()` so one-shot and daemon share one execution path

### v0.15.0 — Radar, AI triage, normalization
- nmap job type; `strip_url_to_host()` target normalization

### v0.14.0 — Service discovery
- Atomic job claim via `POST /jobs/{id}/claim`; nmap job type (safe profile);
  per-tool config validation

### v0.13.0 — Job events
- Emits `started/targets_resolved/running/uploaded/done/failed` lifecycle events

### v0.12.0 — Real heartbeat
- `POST /runner/heartbeat`; reports hostname, version, OS, per-tool availability;
  explicit `heartbeat` command + auto-heartbeat on `jobs run`

### v0.11.0 — Job dispatch
- subfinder job dispatch (wildcard extraction → subfinder → JSONL → httpx import)

### v0.9.0 — VardrRunner v1
- subfinder support for wildcard scope; `jobs list` / `jobs run`; missing tool marks job
  failed instead of silently skipping; `status` command
