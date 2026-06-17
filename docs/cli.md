# VardrRunner — CLI Reference

All commands are sub-commands of `vardrrunner`. Run any command with `--help` for its
exact flags. Commands that talk to the backend require a prior `login` (they exit with a
helpful message otherwise).

```
vardrrunner [COMMAND] [SUBCOMMAND] [OPTIONS]
```

---

## `login`
Authenticate to a Vardr product and persist credentials to `~/.vardrmap/config.json`.

```bash
vardrrunner login vardrmap
```
Prompts for the backend URL and API key. The key is stored locally (0600 on Unix) and is
treated as a secret.

---

## `status`
Show local configuration, runner version, and which external tools are detected on `PATH`
(with versions where available). Does not require auth for the local parts. This is the
quick human glance — *"show me where I stand."*

```bash
vardrrunner status
```

---

## `doctor`
Deep preflight before unattended use — *"validate this machine."* Unlike `status`, `doctor`
is built for scripts: it **exits 0 only when the runner is healthy enough to work**, exits
non-zero on any actionable failure, and prints a remediation hint per problem.

```bash
vardrrunner doctor && vardrrunner daemon start --detach   # gate provisioning on health
vardrrunner doctor --json                                  # machine-readable report
```

Checks: credential source (env vs file), backend URL validity (HTTPS), config-file
permissions, API auth, daemon PID health (running / stale), run-dir writability, free disk,
tool versions, and per-pipeline readiness. **Failures** (no creds, bad URL, auth failure,
unwritable run dir, critically low disk, zero tools) set a non-zero exit; missing individual
tools and low-ish disk are **warnings** that don't block.

---

## `heartbeat`
Send a single heartbeat to the backend (hostname, version, OS, tool availability). Useful
to confirm connectivity and that the backend's Bridge sees this machine.

```bash
vardrrunner heartbeat
```

---

## `run` — run a tool locally and upload results
```bash
vardrrunner run httpx     --program <id> [options]
vardrrunner run subfinder --program <id> [options]
vardrrunner run nuclei    --program <id> [options]
vardrrunner run nmap      --program <id> [--top-ports N] [--timing 0-4] [options]
```
Executes the named tool against the program's scope, captures output into a timestamped
run directory under `~/.vardrmap/runs`, and uploads parsed results to the backend.
`run nmap` performs safe-profile service discovery (normalizes URLs to hosts, never uses
`-A`/`-O`/`-p-`/`--script`/`-T5`) and uploads open ports to the services API.

Every tool run is bounded by a timeout (default 1800 s; set `VARDRRUNNER_TOOL_TIMEOUT`); a
hung tool is killed rather than blocking.

---

## `import` — import an existing output file
```bash
vardrrunner import nuclei --program <id> --file <path>
vardrrunner import httpx  --program <id> --file <path>
vardrrunner import ffuf   --program <id> --file <path>
```
Pushes results from a tool output file (JSON/JSONL) you already have, without running the
tool. `-f` is shorthand for `--file`.

---

## `pipeline` — chain tools into one recon workflow
```bash
vardrrunner pipeline list                              # show available pipelines
vardrrunner pipeline run recon --program <id> [options]
```
A pipeline runs an ordered chain of tools, each uploading its results so the next stage
pulls them from the recon store. Built-in pipelines:

| Name | Chain |
|------|-------|
| `recon` | subfinder (enumerate subdomains from wildcard scope) → httpx (probe) → nuclei (scan) |
| `quick` | subfinder → httpx |

Options for `pipeline run`:
- `--severity high,critical` — nuclei severity filter for the scan stage
- `--yes` / `-y` — skip the confirmation prompt
- `--continue-on-error` — keep going if a stage fails (default: stop)

The pipeline preflights that every tool in the chain is installed, and stops early if a
stage produces no targets (e.g. no subdomains discovered).

---

## `jobs` — one-shot queue operations
```bash
vardrrunner jobs list     # show pending/running jobs for your account
vardrrunner jobs run      # claim and execute all currently pending jobs, then exit
```
`jobs run` auto-sends a heartbeat first, then for each pending job: claims it
(`POST /jobs/{id}/claim`, skipping on `409`), resolves targets, executes, and reports
lifecycle events. This is the same execution core the daemon uses.

---

## `daemon` — continuous background worker
```bash
vardrrunner daemon start [--detach]   # poll jobs (5 s) + heartbeat (60 s) continuously
vardrrunner daemon stop               # cooperative graceful shutdown (removes PID file)
vardrrunner daemon status             # report whether the daemon is running
```
- `--detach` runs the daemon as a detached background process and writes a PID file.
- A double-start guard prevents two daemons from running at once.
- Shutdown is cooperative: `stop` removes the PID file; the daemon notices and exits
  cleanly (graceful SIGTERM handling on Unix, ctypes liveness probe on Windows).

---

## Exit behavior
- Commands requiring auth exit with a clear "Not logged in. Run: `vardrrunner login vardrmap`"
  message when no config is present.
- A missing or failing tool marks the corresponding job **failed** with a reason — the
  runner never silently skips work.
