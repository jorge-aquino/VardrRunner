# VardrRunner — Development

## Prerequisites
- Python **3.10+**
- `git`
- (Optional, for real runs) the external tools on your `PATH`: `httpx`, `subfinder`,
  `nuclei`, `nmap`. They are **not** needed to run the test suite — every subprocess call
  is mocked.

## Setup
```bash
git clone https://github.com/jorge-aquino/VardrRunner.git
cd VardrRunner
python -m venv venv

# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
# macOS / Linux
source venv/bin/activate

pip install -e .        # editable install; exposes the `vardrrunner` command
pip install pytest      # dev dependency
```

## Running the test suite
```bash
pytest tests -q
```
- **113 tests**, all hermetic: no network, no real subprocesses, no real filesystem state
  outside temp dirs.
- The suite must be **green before every commit** (Engineering Charter §3).
- Add tests in the **same commit** as any behavior change.

### What the tests cover
| File | Area |
|------|------|
| `tests/test_config.py` | config read/write, auth requirement |
| `tests/test_jobs.py` | queue list/run, claim race handling, execution core |
| `tests/test_daemon.py` | daemon start/stop/status, PID file, liveness probe |
| `tests/test_heartbeat.py` | heartbeat payload + posting |
| `tests/test_job_events.py` | lifecycle event emission |
| `tests/test_runner.py` | subprocess execution, output capture, failure handling |
| `tests/test_nmap.py` | nmap target normalization + profile |
| `tests/test_status.py` | tool detection + status output |

## Linting
Until a linter is standardized in CI, run a quick static check before committing:
```bash
python -m pyflakes vardrrunner
```
The intended direction is to adopt **ruff** (lint + format) — when added, CI will enforce it.

## Branch & commit workflow
1. Branch off `main` for any non-trivial change.
2. Implement **with tests**; keep the suite green.
3. Update docs and `CHANGELOG.md` in the **same commit** (Charter §2).
4. For a non-trivial design decision, add an ADR in `docs/adr/`.
5. Never add "Co-Authored-By: Claude" to commits.
6. Open a PR; CI must pass before merge.

## Releasing
1. Bump `__version__` in `vardrrunner/__init__.py` and `version` in `pyproject.toml`.
2. Move `Unreleased` notes into a dated version section in `CHANGELOG.md`; add a
   `changelog/vX.Y.Z.md` detail note.
3. Tag the release (`git tag vX.Y.Z`).

## Configuration during development
The CLI reads/writes `~/.vardrmap/config.json`. To point at a local backend:
```bash
vardrrunner login vardrmap     # enter http://localhost:8000 and a dev API key
```
Delete `~/.vardrmap/config.json` to reset auth.
