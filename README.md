# VardrRunner

**The local automation runner for the VardrSec product family.**

VardrRunner runs your security tooling on *your* machine and syncs the results to a
VardrSec backend (today: [VardrMap](https://github.com/jorge-aquino/VardrMap)) over HTTP.
It is a thin, fast, dependency-light client: it polls the backend for queued scan jobs,
claims them atomically, executes the tool locally, streams live progress back, uploads
results, and heartbeats so the backend always knows which machines are online.

> **Why local?** Recon and scanning tools belong on the operator's box — their bandwidth,
> their IP, their tool versions. The backend orchestrates and stores; the runner does the
> work. The two are fully decoupled and only ever exchange JSON.

---

## Features
- **Job queue worker** — poll, atomically claim, execute, and report scan jobs
- **Daemon mode** — `daemon start` runs a continuous background worker (poll every 5 s,
  heartbeat every 60 s) with detached mode, PID file, and graceful shutdown
- **Tool runners** — `httpx`, `subfinder`, `nuclei` (more coming), each capturing output
  into a timestamped run directory
- **Importers** — pull existing `nuclei` / `httpx` / `ffuf` output files into the backend
- **Real heartbeat** — reports hostname, version, OS, and per-tool availability so the
  backend's Bridge shows live machine status
- **Live job events** — emits `started → targets_resolved → running → uploaded → done/failed`
  so the backend Terminal shows real-time logs
- **Safe by default** — missing tools fail the job loudly, targets are normalized before
  use, and the API key is stored locally with restrictive permissions

## Requirements
- Python **3.10+**
- The external tools you intend to run, on your `PATH` (e.g. `httpx`, `subfinder`, `nuclei`, `nmap`)
- A VardrSec backend URL and an API key (`vmap_…` for VardrMap)

## Install
```bash
git clone https://github.com/jorge-aquino/VardrRunner.git
cd VardrRunner
python -m venv venv
# Windows
.\venv\Scripts\Activate.ps1
# macOS/Linux
source venv/bin/activate
pip install -e .
```
This installs the `vardrrunner` command into the active environment.

## Quick start
```bash
vardrrunner login vardrmap     # prompts for backend URL + API key, saves to ~/.vardrmap/config.json
vardrrunner status             # show config, version, and which tools are detected
vardrrunner heartbeat          # confirm the backend can see this machine
vardrrunner daemon start       # run the continuous worker (poll jobs + heartbeat)
```

### One-shot usage
```bash
vardrrunner jobs list                          # show the backend queue
vardrrunner jobs run                            # claim + execute all pending jobs once
vardrrunner run subfinder --program-id 12 ...   # run a single tool and upload results
vardrrunner import nuclei --program-id 12 -f out.jsonl
```

See **[docs/cli.md](docs/cli.md)** for the full command reference.

## Configuration
Config lives at `~/.vardrmap/config.json` and holds your `api_url` and `api_key`.
**Treat this file as a secret** — it contains your key in plaintext (permissions are
restricted to the owner on Unix).

For containers, CI, or a headless VPS, set credentials via environment variables instead
(they take precedence over the file):

| Variable | Purpose |
|----------|---------|
| `VARDRMAP_URL` | Backend base URL (must be `https://`, except `localhost`) |
| `VARDRMAP_API_KEY` | Your `vmap_` API key |
| `VARDRRUNNER_TOOL_TIMEOUT` | Per-tool run timeout in seconds (default 1800); a hung tool is killed and the job marked failed |
| `VARDRRUNNER_ALLOW_INSECURE` | Set to `1` to permit a plain-HTTP backend URL (not recommended) |

The runner refuses to send your API key over plain HTTP to a non-local host, so a mistyped
`http://` URL can't leak your key.

## Documentation
- [docs/architecture.md](docs/architecture.md) — how the runner is structured and how it talks to the backend
- [docs/development.md](docs/development.md) — local setup, testing, and contribution workflow
- [docs/cli.md](docs/cli.md) — complete command and flag reference
- [docs/adr/](docs/adr/) — Architecture Decision Records
- [CHANGELOG.md](CHANGELOG.md) — version history

## Development & testing
```bash
pip install -e ".[dev]"   # editable install + dev tools (pytest, ruff, mypy)
ruff check vardrrunner tests           # lint
ruff format --check vardrrunner tests  # formatting
mypy vardrrunner                       # type check
pytest tests              # 113 tests; all subprocess + HTTP calls are mocked
```
CI runs lint, format, types, and tests with coverage on Python 3.10–3.12 for every push.
Contributions follow the **Engineering Charter** in [CLAUDE.md](CLAUDE.md): clean code,
tests in the same commit, docs updated, and the suite always green.

## License
[MIT](LICENSE) © 2026 Jorge Aquino.

---
*Part of the VardrSec product family — [VardrMap](https://github.com/jorge-aquino/VardrMap) · VardrRunner · VardrVault.*
