# ADR 0005 — Run-scoped pipeline isolation via local handoff files

- **Status:** Accepted
- **Date:** 2026-06-20

## Context

Pipeline stages with `source="recon"` fetch targets by calling `client.recon()`, which
reads from the program's shared recon store. Every recon record ever imported — from any
prior run, any tool, any time — is visible. This means a `subfinder → httpx → nuclei`
pipeline doesn't scan only the hosts subfinder found *this run*; it scans those hosts
**plus everything already in the store**. The contamination is silent and grows over time.

A live example: after a few weeks of scanning, the recon store holds 736 hosts. A new
pipeline run discovers 12 new hosts. httpx receives 748, not 12. The operator sees
"nuclei scanned 748 targets" with no indication that 736 of them were stale.

## Decision

Introduce **local handoff files** to pass targets between pipeline stages without going
through the backend recon store.

After a successful stage:
1. The handler's `extract_handoff_targets(output)` parses the tool's output and returns
   a flat `list[str]` of targets (URLs or hostnames) for the next stage.
2. If the list is non-empty, the pipeline writes it to `run_dir/handoff.txt`.
3. The next stage checks for a handoff file. If one exists and `source == "recon"`, it
   reads targets from the file instead of calling `client.recon()`.
4. After reading, it calls `handler.normalize_handoff_targets(targets)` to strip URL
   scheme/path for tools that need bare host/IP input (nmap, dnsx, naabu).

If `extract_handoff_targets` returns `[]` (nuclei, nmap, naabu — terminal tools that
don't produce inputs for downstream tools), the next stage falls back to `client.recon()`
as before. This preserves backward compatibility.

Each pipeline run gets a `uuid4().hex[:8]` **run ID** printed at start and end. It
enables log correlation and is the hook for future backend run-filtering.

## Alternatives considered

**Backend run ID / batch ID** — tag every uploaded recon record with a `pipeline_run_id`
and filter `GET /recon?pipeline_run_id=...` at the source. Cleaner in theory; requires
coordinated backend changes and a VardrMap deploy before Runner can use it. Deferred
because: (a) it can't be shipped Runner-side alone, (b) local handoff solves the same
isolation problem immediately, and (c) the local file can be kept as a reliable fallback
even after backend run IDs land.

**Offset/timestamp filter on recon** — only read recon created after the pipeline
started. Fragile: clock skew, immediate re-uploads, and recon pre-created by the operator
can all cause incorrect filtering.

**Stage subdirectories** — give each stage a named subdirectory inside a shared pipeline
run directory. Cleaner for large pipelines; adds path-management complexity and would
break existing test helpers that patch `_make_run_dir` to a single `tmp_path`. The current
per-stage `run_dir` + a `handoff.txt` file in it achieves the same isolation without
restructuring the directory layout.

## Consequences

- Pipeline targets are isolated to the run: no stale recon contamination.
- Operators see run IDs in output, making log correlation straightforward.
- `_run_stage` return type changed from `bool` to `tuple[bool, Path | None]` (internal).
- Direct `run` commands and the daemon job runner are unaffected — they bypass the
  pipeline command and call `resolve_targets()` directly.
- Future backend run-ID support can use the existing `run_id` as the tag value and drop
  the local handoff in favour of server-side filtering once VardrMap is ready.
