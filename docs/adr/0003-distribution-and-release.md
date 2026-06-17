# ADR 0003 — Distribution and release process

- **Status:** Accepted
- **Date:** 2026-06-17

## Context
VardrRunner needs a repeatable, trustworthy way to ship. As a security tool that operators
run with their API keys (often unattended on a VPS), the supply chain matters: artifacts
should be verifiable, dependencies audited, and installs should not require cloning the repo.

## Decision
Releases are **tag-driven**. Pushing a `vX.Y.Z` tag triggers `release.yml`, which:

1. Builds an sdist + wheel with `python -m build`.
2. Generates a **CycloneDX SBOM** (`cyclonedx-py environment`).
3. Attests **build provenance** (`actions/attest-build-provenance`) for the artifacts.
4. Publishes a **GitHub Release** with the wheel, sdist, and SBOM attached + auto notes.
5. Optionally publishes to **PyPI via trusted publishing** (OIDC, no stored token) — gated
   behind the `PYPI_PUBLISH` repo variable so the rest of the pipeline runs green before PyPI
   is set up.

The version is single-sourced from `vardrrunner/__init__.py` (read dynamically by
`pyproject.toml`, ADR-adjacent to the v0.18.0 packaging work). CI additionally runs
`pip-audit` and a Linux/Windows/macOS test matrix, since the daemon is OS-sensitive.

Installation paths, in order of preference:
- **pipx** (`pipx install vardrrunner`) once on PyPI — isolated, ideal for a CLI.
- **From a GitHub Release** wheel (works today, before PyPI).
- **From source** (`pip install -e ".[dev]"`) for development.

## Consequences
- Every release has a verifiable provenance attestation and an SBOM, satisfying the
  supply-chain bar without manual steps.
- PyPI publishing is decoupled: the maintainer enables it by configuring a trusted publisher
  and setting `PYPI_PUBLISH=true`; nothing breaks in the meantime.
- A bad tag produces a bad release — the version bump + CHANGELOG roll remain a deliberate,
  reviewed PR step before the tag is pushed.

## Alternatives considered
- **Stored PyPI API token** — rejected; trusted publishing (OIDC) avoids a long-lived secret.
- **Manual `twine upload`** — rejected; not reproducible or attestable.
- **Homebrew/Scoop formulae** — deferred until there's PyPI/release demand; the GitHub Release
  wheel covers the gap.
