# ADR 0002 — Tool-handler registry for job execution

- **Status:** Accepted
- **Date:** 2026-06-15

## Context
`execute_pending_jobs` had grown to ~290 lines of `if tool_type == "subfinder" / "nmap" /
"httpx"` branches. Each branch re-implemented the same lifecycle — claim, emit
started/targets_resolved/running/uploaded/done, handle failure — with subtle, drift-prone
differences (e.g. one branch's tool run wasn't wrapped in failure handling until a later fix;
config values were parsed inconsistently with scattered `int(cfg.get(...))`). Adding a tool
meant editing the middle of a long function.

## Decision
Introduce a `ToolHandler` abstraction (one class per job type) in `handlers.py`. Each handler
declares five things about its tool: `parse_config`, `resolve_targets`, `running_label`,
`execute`, and `upload`. A single uniform lifecycle in `commands/jobs.py` (`_execute_one`)
drives every handler:

1. look up the handler in `REGISTRY` (unknown type → fail)
2. capability check (`tool_available` → fail before claiming)
3. typed config validation (`ConfigError` → fail)
4. target resolution (exception → fail)
5. empty targets → done
6. claim → emit `started` / `targets_resolved`
7. `execute` → gate on output → `upload` → emit `uploaded`
8. one success path (`_complete_done`) and one failure path (`_fail_job`)

Handlers are registered in a `REGISTRY` dict keyed by job type.

## Consequences
- The executor dropped from ~290 lines to ~90; every tool now gets identical
  claim/event/failure handling for free, removing the drift risk.
- **Adding a tool is a one-file change** — write a handler, register it. This is the seam the
  planned recon pipelines and additional tools (naabu, dnsx, katana) will build on.
- Each handler is unit-testable in isolation (`tests/test_handlers.py`).
- Behavior preserved: all prior job/event/nmap tests pass unchanged except two internal patch
  targets that moved with `_resolve_targets` into `handlers`.

## Alternatives considered
- **Keep the branch-per-tool function** — rejected; it was the source of the duplication and drift.
- **Plugin/entry-point system for third-party tools** — deferred; the in-repo registry is simpler
  and sufficient until external tools need to register out-of-tree.
