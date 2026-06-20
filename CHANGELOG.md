# Changelog

All notable changes to VardrRunner are documented here.
This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Per-version detail notes live in [`changelog/`](changelog/).

## [Unreleased]

## [0.21.0] — 2026-06-20
Run-scoped pipeline isolation. See [changelog/v0.21.0.md](changelog/v0.21.0.md) for details.

### Added
- **Run-scoped pipeline isolation.** Each `pipeline run` now generates a short run ID
  (`8-hex`) printed at the start and end. After every stage completes, its discovered
  targets are extracted from the output and written to a local **handoff file**; the next
  stage reads from that file instead of the shared backend recon store. This prevents stale
  recon from earlier runs contaminating later stages.
- **`ToolHandler.extract_handoff_targets(output)`** — new method on every handler, returns
  the targets that stage produced for the next stage. `HttpxHandler` extracts URLs/hosts
  from its JSONL; `SubfinderHandler` and `DnsxHandler` extract hostnames. Terminal handlers
  (nuclei, nmap, naabu) return `[]` and fall back to backend resolution.
- **`ToolHandler.normalize_handoff_targets(targets)`** — new method that strips URL
  scheme/path for host-only tools (nmap, dnsx, naabu), matching what their
  `resolve_targets()` does for backend recon. Default is identity.
- **ADR 0005** documents the design decision. See `docs/adr/0005-run-scoped-pipelines.md`.

### Changed
- `commands/pipeline._run_stage()` return type changed from `bool` to
  `tuple[bool, Path | None]`. No public API change — `_run_stage` is internal.

## [0.20.1] — 2026-06-20
Reliability hardening. See [changelog/v0.20.1.md](changelog/v0.20.1.md) for details.

### Fixed
- **Recon pagination.** `api.recon()` now paginates in chunks of 500 instead of issuing one
  request with the caller's `limit`. Eliminates the live 422 seen at `limit=736` and makes
  large recon sets reliable for httpx, nuclei, naabu, and pipelines.
- **Tool failures are now fatal.** `runner._run_tool()` raises `ToolError` on any non-zero exit
  code; every `run_*` function signature changed from `-> int` to `-> None`. A failed httpx,
  nuclei, subfinder, dnsx, nmap, or naabu run marks the job **failed** with the exit code
  rather than silently drifting into "done".
- **`doctor` skips auth after an invalid backend URL.** `_check_auth()` now validates the URL
  before making any network call, returning a WARN instead of a noisy follow-up failure.
- **Corrupt config file is handled gracefully.** `config.load()` raises `InvalidConfigFile`
  (not a raw `JSONDecodeError`) on malformed JSON. `doctor._collect()` catches it, emits one
  clear FAIL check with a remediation hint, and continues running tool/disk/daemon checks.
- **`nmap` version detection fixed.** `tool_version()` now uses `--version` for nmap (was
  `-version`) and falls back to a `X.Y.Z`-style regex in addition to `vX.Y.Z`, so nmap,
  dnsx, and naabu report actual version numbers instead of "unknown".

## [0.20.0] — 2026-06-17
Secure credentials + broader recon coverage. See
[changelog/v0.20.0.md](changelog/v0.20.0.md) for the rollup.

### Added
- **dnsx + naabu tools.** Two new recon tools via the handler registry:
  - `dnsx` (`vardrrunner run dnsx`) resolves hosts and uploads only the **resolvable** ones as
    recon targets, so later httpx/nuclei passes don't waste time on dead names.
  - `naabu` (`vardrrunner run naabu`) does a fast top-ports scan and uploads open ports to the
    services API (`source: "naabu"`).
  - Two new pipelines: `deep` (subfinder → dnsx → httpx → nuclei) and `ports`
    (subfinder → dnsx → naabu). `doctor`/`status`/heartbeat pick up both tools automatically.
- **OS keychain credential storage.** `vardrrunner login` now stores your API key in the OS
  keychain (macOS Keychain, Windows Credential Locker, Linux Secret Service) by default, with
  the backend URL kept in `config.json`. Key resolution is `VARDRMAP_API_KEY` env > keychain >
  legacy config file. On a headless box with no keyring backend it falls back to the plaintext
  config file with a warning, so servers keep working. See
  [docs/adr/0004-credential-storage.md](docs/adr/0004-credential-storage.md).
- **`vardrrunner logout`** — removes the stored key from the keychain and config file, leaves
  the API URL in place, and warns if `VARDRMAP_API_KEY` is still set in the environment.
### Changed
- `doctor` reports the **credential source** (`environment` / `keychain` / `config file`)
  without exposing the secret, and only warns about config-file permissions when the file
  actually holds a plaintext key.

## [0.19.0] — 2026-06-17
First feature release from the standalone repo. See
[changelog/v0.19.0.md](changelog/v0.19.0.md) for the rollup.

### Added
- **`vardrrunner doctor`.** A deep preflight for unattended/VPS use, distinct from `status`'s
  quick glance: it exits 0 only when the runner is healthy enough to work, exits non-zero on
  actionable failures, and prints remediation per problem (so `doctor && daemon start` gates
  provisioning). Checks credential source, backend URL validity, config-file permissions, API
  auth, daemon PID health, run-dir writability, free disk, tool versions, and pipeline
  readiness. `--json` emits a machine-readable report.
- **Recon pipelines.** `vardrrunner pipeline run recon --program <id>` chains tools in one
  command — `recon` = subfinder → httpx → nuclei, `quick` = subfinder → httpx. Each stage
  uploads its results so the next pulls them from the recon store; the run preflights tool
  availability, validates the nuclei `--severity` filter up front, stops early on an empty
  stage, and supports `--continue-on-error`. `vardrrunner pipeline list` shows the chains.
  Built on the handler registry — a pipeline is just an ordered list of `Stage(tool, source)`.
- **Typed, validated job configs.** Tool configs (`limit`, `status_code`, `severity`,
  `templates`, `top_ports`, `timing`, `timeout`) are parsed into frozen dataclasses
  (`configs.py`) and validated up front. A malformed or drifted backend payload now fails
  the job fast with a clear message (e.g. out-of-range nmap timing, unknown nuclei severity)
  instead of blowing up mid-execution. A `JobEnvelope` likewise validates the job wrapper
  (`id`/`tool_type`/`target_source`/`program_id`).
- **`vardrrunner run nmap`.** Direct service-discovery command (safe profile only), matching
  the existing nmap *job* support. `status` now lists every allowlisted tool (incl. nmap),
  so it can't drift from what the runner actually supports.
- **Environment-variable config.** `VARDRMAP_URL` and `VARDRMAP_API_KEY` override the
  config file (precedence: env > file), so containers, CI, and headless VPS daemons don't
  need a config file. `status` reflects the resolved source.
- **Per-tool run timeout.** Every tool subprocess now runs under a wall-clock limit
  (default 1800 s; override per job via `config.timeout`, or globally via
  `VARDRRUNNER_TOOL_TIMEOUT`). A hung tool is killed and the job marked **failed** instead
  of freezing the daemon forever.

### Changed
- **Tool-handler registry.** `execute_pending_jobs` (~290 lines of per-tool `if` branches)
  is refactored into a `ToolHandler` per job type (`handlers.py`) driven by one uniform
  lifecycle (`_execute_one`): capability check → config → targets → claim → events → upload
  → done/fail. Every tool now gets identical claim/event/failure handling, and adding a tool
  is a one-file change. See
  [docs/adr/0002-tool-handler-registry.md](docs/adr/0002-tool-handler-registry.md).
- **Direct `run` commands share the typed-config/handler path.** `run httpx|subfinder|nuclei|nmap`
  now validate their options through the same configs and reuse the same handlers as jobs and
  pipelines, so `run nmap --timing 9` is rejected (not silently clamped) and `run nuclei
  --severity bogus` fails before any work. Target resolution moved to `targets.py`.
- **Resilient API client.** The HTTP session now retries transient failures
  (connection errors and 429/500/502/503/504) with exponential backoff, so a
  long-running daemon survives network blips and brief backend restarts. Retries
  are limited to idempotent methods — POST/PATCH are never auto-retried, so a
  dropped response can't cause a double-claim, double-import, or duplicate event.
  Retry count and backoff are constructor-configurable. Requests also send a
  `User-Agent: vardrrunner/<version> (<os>)` header for backend attribution.

### Fixed
- **Pipeline `--continue-on-error` is now complete** — it also covers tool-execution and
  upload failures, not just target resolution and timeouts.
- **Malformed job envelopes fail cleanly.** A job missing a required field is marked failed
  (or skipped if it has no id) via `JobEnvelope`, instead of risking a `KeyError` mid-loop.

### Security
- **HTTPS enforced for the backend URL.** The runner refuses to send your `vmap_` API key
  over plain HTTP to a non-local host (allowed for `localhost`, or with
  `VARDRRUNNER_ALLOW_INSECURE=1`). Validated at login and on every authenticated call.

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
