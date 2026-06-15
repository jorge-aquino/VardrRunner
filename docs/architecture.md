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
| `vardrrunner/config.py` | Resolve credentials (env `VARDRMAP_URL`/`VARDRMAP_API_KEY` over `~/.vardrmap/config.json`); restrict file permissions; `validate_api_url()` enforces HTTPS; `require_auth()` guards commands. |
| `vardrrunner/configs.py` | Typed, validated tool configs (`HttpxConfig`, `NucleiConfig`, `NmapConfig`, `SubfinderConfig`). Raw backend dicts are parsed into frozen dataclasses up front; invalid values raise `ConfigError` and fail the job fast. |
| `vardrrunner/handlers.py` | One `ToolHandler` per job type (`parse_config`/`resolve_targets`/`execute`/`upload`) plus the `REGISTRY`. Adding a tool is a one-file change here (see ADR 0002). |
| `vardrrunner/runner.py` | Subprocess execution, stdout/stderr capture, timestamped run directories under `~/.vardrmap/runs`. |
| `vardrrunner/commands/auth.py` | `login` — prompt for and persist backend URL + API key. |
| `vardrrunner/commands/run.py` | `run httpx|subfinder|nuclei|nmap` — execute one tool, upload results. |
| `vardrrunner/commands/imports.py` | `import nuclei|httpx|ffuf` — push an existing output file. |
| `vardrrunner/commands/jobs.py` | `jobs list|run` — owns the uniform job *lifecycle* (`_execute_one`): capability → config → targets → claim → events → upload → done/fail, delegating specifics to a `handlers` registry entry. |
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

Credentials may instead come from `VARDRMAP_URL` / `VARDRMAP_API_KEY` env vars, which take
precedence over the file (useful for containers, CI, and headless VPS daemons). The backend
URL must be HTTPS (except `localhost`, or with `VARDRRUNNER_ALLOW_INSECURE=1`) so the key is
never sent in cleartext. The API key is the runner's only credential; it is never logged or printed.

## Design invariants
- **All HTTP goes through `api.py`.** No ad-hoc requests elsewhere.
- **All backend data is untrusted.** Validate and normalize before it reaches a subprocess.
- **Every tool run is time-bounded.** A hung tool is killed and the job marked failed — the
  daemon never blocks forever.
- **Failures are loud.** A missing/failed tool fails the job; it is never skipped silently.
- **No backend coupling.** The runner must build, test, and run without the backend present
  (tests mock every HTTP and subprocess call).
