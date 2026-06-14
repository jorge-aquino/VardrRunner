# ADR 0001 — Extract VardrRunner from the VardrMap monorepo

- **Status:** Accepted
- **Date:** 2026-06-14

## Context
VardrRunner began life as the `runner/` directory inside the VardrMap monorepo. It is a
Python CLI that runs security tooling locally and syncs to the VardrMap backend. As the
runner matured (job queue worker, real heartbeat, daemon mode), two facts became clear:

1. **There is zero code coupling to the backend.** The runner imports nothing from
   `backend/`, the backend imports nothing from the runner, and the only communication is
   JSON over HTTP. They are already independent programs.
2. **The runner deserves its own lifecycle.** It is installed separately (`pip install -e`),
   has its own version, its own test suite (113 tests), and is intended to grow into
   product-grade software — not remain a sub-folder.

The original VardrMap roadmap already listed "VardrRunner: extract to a separate repo when
the API stabilizes."

## Decision
Move VardrRunner into its own repository (`jorge-aquino/VardrRunner`), preserving full git
history. The extraction was performed with `git subtree split --prefix=runner` against a
throwaway clone of VardrMap, then merged into the new repo — so VardrMap's working tree was
never disturbed during extraction. The runner continues to integrate with VardrMap **only**
over the existing HTTP API; nothing about job dispatch changes.

Removal of `runner/` from VardrMap (and the corresponding CI/docs cleanup) is a **separate,
deliberate change**, not part of this extraction.

## Consequences
- VardrRunner has independent versioning, CI, documentation, and release cadence.
- The runner can eventually be published to PyPI and installed without cloning VardrMap.
- Two repos must be kept in sync at the **API contract** level; the contract is the only
  coupling, and it is documented on the backend side.
- VardrMap will, in a follow-up, remove `runner/` and repoint its CI and docs. Until then,
  the code exists in both places — the new repo is the source of truth going forward.

## Alternatives considered
- **Keep a vendored copy in VardrMap as well.** Rejected: two sources of truth drift apart,
  and co-location buys nothing because the two communicate only over HTTP.
- **Copy files without history.** Rejected: loses authorship and the rationale embedded in
  past commits; `subtree split` preserves both at no real cost.
