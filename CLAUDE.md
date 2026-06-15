# VardrRunner — Claude Instructions

## What this project is
VardrRunner is the local automation runner for the VardrSec product family. It is a
Python CLI (Typer + Rich) that runs security tooling on the operator's own machine and
syncs results to a VardrSec backend (today: VardrMap) **purely over HTTP**.

It is a **client**, not a service: the runner polls the backend for work
(`GET /jobs/pending`), claims jobs atomically (`POST /jobs/{id}/claim`), executes the
tool locally, streams lifecycle events back (`POST /jobs/{id}/events`), uploads results,
and heartbeats so the backend knows it is alive. There is zero code coupling to the
backend — they only ever talk JSON over the wire. Extracted from the VardrMap monorepo
on 2026-06-14 with full history (see `docs/adr/0001-extract-vardrrunner-from-vardrmap.md`).

This is not "just another CLI." It is built to a product-grade bar — see the
**Engineering Charter** below, which is shared verbatim across every VardrSec repo.

## Where things live
- `vardrrunner/` — the Python package (source of truth)
  - `cli.py` — Typer app; wires every sub-command
  - `api.py` — thin HTTP client (`requests.Session`); the only thing that talks to a backend
  - `config.py` — reads/writes `~/.vardrmap/config.json` (holds the API key — treat as secret)
  - `runner.py` — subprocess execution, output capture, run directory management
  - `commands/` — one module per command group: `auth`, `daemon`, `heartbeat`, `imports`, `jobs`, `programs`, `run`, `status`
- `tests/` — pytest suite (113 tests). **Every subprocess and HTTP call is mocked** — tests never touch the network or spawn real tools.
- `docs/` — architecture, development setup, CLI reference, and ADRs (see Documentation rules)
- `docs/adr/` — Architecture Decision Records, one per non-trivial decision
- `changelog/` — per-version detail notes; `CHANGELOG.md` at root is the rolled-up index
- `.github/workflows/` — CI (lint + full test suite on every push)
- `scratch/` — gitignored; throwaway experiments only, never committed

## Hard rules — never break these
- Never add "Co-Authored-By: Claude" to commits
- Run the full test suite (and the linter) before every commit — keep the suite green
- Every behavior-changing change updates docs **and** `CHANGELOG.md` in the same commit
- The runner talks to backends **only** through `api.py` — no scattered HTTP calls
- Never log, print, or commit the API key; `~/.vardrmap/config.json` is a secret
- Tools the runner shells out to are external input — validate/normalize args, never build shell strings from unsanitized server data

## Security expectations
- The API key lives in `~/.vardrmap/config.json` (0600 on Unix) or the `VARDRMAP_API_KEY`
  env var; never echo it
- The backend URL must be HTTPS (except `localhost`) so the key is never sent in cleartext;
  `config.validate_api_url` enforces this at login and on every authenticated call
- Treat all data from the backend as untrusted: validate job payloads, normalize targets
  (e.g. `strip_url_to_host` for nmap) before passing them to a subprocess
- Never use `shell=True` with interpolated server data; pass argv lists
- Every tool run is bounded by a timeout; a missing, failed, or **timed-out** tool marks the
  job **failed** with a clear reason — never silently skip and never hang the daemon

## Documentation rules
A change is **behavior-changing** if it adds, removes, or modifies a command, flag,
config key, backend endpoint the runner calls, or operator-visible behavior.

- New or changed command/flag → `docs/cli.md`
- New module, data flow, or backend interaction → `docs/architecture.md`
- New setup step, env var, or dependency → `docs/development.md`
- Any non-trivial design decision → a new ADR in `docs/adr/`
- Any feature, fix, or behavior change → `CHANGELOG.md` (+ a `changelog/vX.Y.Z.md` note)

Documentation-only, test-only, and pure-refactor commits may note
"No user-facing docs change needed" in the commit summary.

## Verification before commit
```
# from repo root, in the activated venv — mirrors CI
ruff check vardrrunner tests           # lint
ruff format --check vardrrunner tests  # formatting
mypy vardrrunner                       # type check
pytest tests --cov=vardrrunner --cov-fail-under=60   # all 113 must pass
```
Autofix lint + format with `ruff check --fix vardrrunner tests && ruff format vardrrunner tests`.

## Running locally
```
python -m venv venv
.\venv\Scripts\Activate.ps1     # Windows
pip install -e ".[dev]"         # installs the `vardrrunner` command + dev tools

vardrrunner login vardrmap      # stores api_url + api_key in ~/.vardrmap/config.json
vardrrunner heartbeat           # confirm connectivity
vardrrunner daemon start        # continuous worker: polls jobs + heartbeats
```

## Command surface (see docs/cli.md for detail)
- `login vardrmap` — authenticate and persist config
- `run httpx|subfinder|nuclei` — run a tool locally, upload results
- `import nuclei|httpx|ffuf` — import an existing output file
- `jobs list|run` — inspect and execute the backend job queue (one-shot)
- `daemon start|stop|status` — long-running background worker (poll + heartbeat)
- `heartbeat` — send a single heartbeat
- `status` — show local config, version, and detected tool availability

---

## Engineering Charter — shared across all VardrSec repos
<!-- This section is identical in VardrMap, VardrRunner, and VardrVault.
     Edit it in one repo, then mirror the change to the other two. -->

Every VardrSec repo is built to a product-grade bar: **revolutionary in intent, clean in
execution, lean in performance, and fully documented at every step.** Treat nothing here
as "just a script."

### 1. Organization — a place for everything
- One concern per module, one responsibility per function. No god files.
- Fixed homes: source, tests, docs, changelog, and ADRs each live in a predictable place.
- No stray files at the repo root. Experiments go in `scratch/` (gitignored) or are deleted.
- Dead code, commented-out blocks, and unused dependencies are removed, not parked.
- Every public symbol explains *why* it exists, not just *what* it does.

### 2. Track everything
- `CHANGELOG.md` follows Keep a Changelog + SemVer; updated with every behavior change.
- Every non-trivial design decision gets an ADR in `docs/adr/` (use the template).
- No undocumented releases; every version is dated and described.
- Committed TODOs reference a tracked issue, or they don't get committed.

### 3. Tests are non-negotiable — on every repo
- Every behavior-changing change ships with tests in the **same commit**.
- The suite is always green. Never commit failing or skipped tests without a written reason.
- Cover logic, edge cases, and failure paths — coverage of meaning, not line-count vanity.
- CI runs the full suite on every push; a red build blocks merge.

### 4. Clean code
- Clear names over clever ones. Small functions. Early returns over deep nesting.
- No premature abstraction and no copy-paste — refactor at the third duplication.
- Errors are handled explicitly and surfaced with context, never silently swallowed.
- Match surrounding style; run the formatter and linter before every commit.

### 5. Lean & smooth performance
- Measure before optimizing. Keep hot paths allocation-light and I/O batched.
- Prefer streaming/pagination over loading everything into memory.
- Dependencies are a liability — each new one must earn its place.
- Build, startup, and test times are part of the product; watch for regressions.

### 6. Full software lifecycle, every time
Plan → design (ADR if non-trivial) → implement **with** tests → document → review →
release (changelog + tag) → maintain. No step is skipped, even for small changes.
