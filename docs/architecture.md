# VardrRunner — Architecture

## Role in the VardrSec system
VardrRunner is a **stateless local client**. A VardrSec backend (VardrMap today) owns the
queue, the database, and the UI. The runner owns *execution*: it runs tools on the
operator's machine and reports back. The two are fully decoupled and communicate only via
JSON over HTTP — there is no shared code, no shared database, and no import dependency in
either direction.

```
┌─────────────────────────┐         HTTP (JSON)         ┌──────────────────────────┐
│        VardrMap          │  <───────────────────────  │       VardrRunner         │
│  (backend + DB + UI)     │   poll / claim / events     │   (this repo, local CLI)  │
│                          │   heartbeat / upload        │                           │
│  GET  /jobs/pending      │  ───────────────────────>   │   runs httpx/subfinder/   │
│  POST /jobs/{id}/claim   │                             │   nuclei/nmap locally     │
│  POST /jobs/{id}/events  │                             │                           │
│  POST /runner/heartbeat  │                             │                           │
└─────────────────────────┘                             └──────────────────────────┘
```

## Package layout
| Path | Responsibility |
|------|----------------|
| `vardrrunner/cli.py` | Typer application; defines command groups and wires them together. Thin — delegates to `commands/`. |
| `vardrrunner/api.py` | The **only** module that performs HTTP. A `requests.Session` wrapper exposing typed methods; raises `requests.HTTPError` on non-2xx. Retries transient failures (connection errors, 429/5xx) with exponential backoff on idempotent methods only (never POST/PATCH); sends a `User-Agent: vardrrunner/<version>` header. |
| `vardrrunner/config.py` | Read/write `~/.vardrmap/config.json` (`api_url`, `api_key`); restricts file permissions; `require_auth()` guards commands. |
| `vardrrunner/runner.py` | Subprocess execution, stdout/stderr capture, timestamped run directories under `~/.vardrmap/runs`. |
| `vardrrunner/commands/auth.py` | `login` — prompt for and persist backend URL + API key. |
| `vardrrunner/commands/run.py` | `run httpx|subfinder|nuclei` — execute one tool, upload results. |
| `vardrrunner/commands/imports.py` | `import nuclei|httpx|ffuf` — push an existing output file. |
| `vardrrunner/commands/jobs.py` | `jobs list|run` — one-shot queue inspection and execution; `execute_pending_jobs()` is the shared execution core. |
| `vardrrunner/commands/daemon.py` | `daemon start|stop|status` — continuous worker (poll + heartbeat) with PID file and graceful shutdown. |
| `vardrrunner/commands/heartbeat.py` | `heartbeat` — send a single heartbeat. |
| `vardrrunner/commands/status.py` | `status` — local config, version, detected tool availability. |
| `vardrrunner/commands/programs.py` | program lookup helpers used by other commands. |

## Job execution lifecycle
1. **Poll** — `GET /jobs/pending` returns queued jobs for this operator.
2. **Claim** — `POST /jobs/{id}/claim` atomically transitions `pending → running`; a `409`
   means another runner won the race, so this runner skips it.
3. **Resolve targets** — expand scope (e.g. wildcard → subfinder), normalize (e.g.
   `strip_url_to_host` for nmap). Emits `targets_resolved`.
4. **Execute** — `runner.py` spawns the tool as an argv list (never `shell=True` with server
   data), capturing output to a run directory. Emits `running`.
5. **Upload** — parse tool output and POST results to the backend. Emits `uploaded`.
6. **Report** — emit `done` or, on any failure (including a missing tool), `failed` with a
   clear reason. The job is never left silently incomplete.

Events are posted via `POST /jobs/{id}/events` so the backend Terminal can render live logs.

## Heartbeat
On daemon start and every 60 s thereafter, the runner sends `POST /runner/heartbeat` with
hostname, runner version, OS, and per-tool availability + versions. The backend marks a
runner **online** if `last_seen` is within 5 minutes. Heartbeats are upserted per
`(owner, hostname)`, so multiple machines show up independently in the backend's Bridge.

## Daemon model
`daemon start` launches a dedicated worker thread that interleaves job polling (5 s) and
heartbeats (60 s). `--detach` spawns a `DETACHED_PROCESS` and writes a PID file; `stop`
removes the PID file as a cooperative shutdown signal and the daemon exits gracefully.
Windows liveness is checked via a ctypes probe (plain `os.kill` on Windows is
`TerminateProcess` and would kill the daemon it was meant to check).

## Configuration & secrets
All local state lives under `~/.vardrmap/`:
- `config.json` — `api_url` + `api_key` (secret; 0600 on Unix)
- `runs/` — timestamped tool output directories

The API key is the runner's only credential. It is never logged or printed.

## Design invariants
- **All HTTP goes through `api.py`.** No ad-hoc requests elsewhere.
- **All backend data is untrusted.** Validate and normalize before it reaches a subprocess.
- **Failures are loud.** A missing/failed tool fails the job; it is never skipped silently.
- **No backend coupling.** The runner must build, test, and run without the backend present
  (tests mock every HTTP and subprocess call).
