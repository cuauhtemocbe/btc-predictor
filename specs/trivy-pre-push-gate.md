---
title: Trivy Fail-Closed CVE Gate (Pre-Push)
status: completed
created: 2026-09-14
updated: 2026-09-14
issue: "meta-projects#41"
---

# Trivy Fail-Closed CVE Gate (Pre-Push)

## Objective

Add a fail-closed Trivy vulnerability gate to the pre-push git hook so that a CRITICAL, fixable CVE in a dependency blocks `git push` locally, before it can reach `main` and Railway's auto-deploy. This is one repo's rollout of a fleet-wide standard being applied across projects (meta-projects issue #41).

## Context

This repo does **not** use `.githooks/` or Husky. Git hooks are managed entirely by the Python [pre-commit](https://pre-commit.com/) framework, configured in `.pre-commit-config.yaml` and activated via `pre-commit install --hook-type pre-push` (see `scripts/setup-hooks.sh` and `scripts/hooks/README.md`). `pre-commit` — not any hand-written script — owns and regenerates `.git/hooks/pre-push`; a hand-written hook file there would be silently clobbered on the next `pre-commit install` or conflict with it.

Today the `pre-push` stage runs a single local hook, `pytest-docker` (`- repo: local` block in `.pre-commit-config.yaml`, entry `scripts/hooks/run-tests.sh`), which brings up the Docker Compose stack and runs the full pytest suite (~94s). There is no dependency vulnerability check anywhere in the local hook chain — `gitleaks` (pre-commit stage) covers secrets, `ruff`/`ruff-format` cover lint/style, `mypy-docker` covers types, but nothing checks `poetry.lock` / `shared/poetry.lock` for known CVEs before code leaves the developer's machine.

The `trivy-scan` Claude Code skill (`.claude/skills/trivy-scan/`) already documents how to install and run Trivy interactively (`.claude/skills/trivy-scan/setup.md`), including an environment-check step (`trivy --version`) and a Docker-based fallback for machines without a local Trivy install. This spec adds a **non-interactive, scriptable** wrapper (`scripts/hooks/trivy-scan.sh`) that the pre-push hook can call unattended — if Trivy isn't on `PATH`, the hook fails closed (exit 1) rather than skipping the check, and points the developer at the existing setup skill instead of duplicating install instructions.

A local scan of this repo (`trivy fs . --scanners vuln --severity CRITICAL --ignore-unfixed`) run before and during this change confirms the gate starts from a clean baseline: 0 findings across `poetry.lock` and `shared/poetry.lock`.

## Requirements

### Functional Requirements

- [x] `scripts/hooks/trivy-scan.sh` exists, is executable, and scans the repo filesystem for CRITICAL, fixable vulnerabilities using `trivy fs . --scanners vuln --severity CRITICAL --exit-code 1 --ignore-unfixed --quiet`
- [x] The script fails closed: if `trivy` is not found on `PATH`, it exits non-zero (does not silently pass) and points the developer at `.claude/skills/trivy-scan/setup.md`
- [x] A new `trivy-cve-gate` hook is registered in `.pre-commit-config.yaml`, in the same `- repo: local` block as `pytest-docker`, with `stages: [pre-push]`
- [x] `trivy-cve-gate` runs **before** `pytest-docker` in that block so the fast CVE check fails fast, ahead of the slower Docker test suite
- [x] `scripts/hooks/README.md` and `scripts/setup-hooks.sh` mention the new Trivy step in their pre-push descriptions, matching existing style (additive only)
- [x] No changes to `pytest-docker`, `mypy-docker`, `run-mypy.sh`, or any post-push / Railway monitoring scripts

### Non-Functional Requirements

- [x] Fail-closed: an unfixable-to-skip state (Trivy missing, or a CRITICAL fixable CVE present) blocks the push rather than defaulting to pass
- [x] Fast: Trivy's filesystem/lockfile scan is lightweight (seconds, not the ~94s of the Docker pytest run) and runs first so failures surface quickly
- [x] No change to the existing `.pre-commit-config.yaml` activation model — still driven entirely by `pre-commit install --hook-type pre-push`, no `.githooks/`, no `core.hooksPath` changes, no hand-written `.git/hooks/pre-push`

## Architecture

### Components

1. **`scripts/hooks/trivy-scan.sh`** — standalone, non-interactive shell script. Checks for `trivy` on `PATH`; if missing, prints a pointer to the setup skill and exits 1. Otherwise runs `trivy fs . --scanners vuln --severity CRITICAL --exit-code 1 --ignore-unfixed --quiet` and propagates its exit code.
2. **`.pre-commit-config.yaml`** — new `trivy-cve-gate` local hook entry, ordered before `pytest-docker` inside the existing pre-push `- repo: local` block, `language: system`, `pass_filenames: false`, `always_run: true`, `stages: [pre-push]`.
3. **Docs** — `scripts/hooks/README.md` (Pre-push bullet list) and `scripts/setup-hooks.sh` (setup completion echo output) updated to mention the Trivy gate, so the documented hook chain matches the configured one.

```
git push
  └─ pre-commit (pre-push stage)
       ├─ trivy-cve-gate   (scripts/hooks/trivy-scan.sh)   ← new, runs first
       └─ pytest-docker    (scripts/hooks/run-tests.sh)    ← unchanged
```

### Data Model

Not applicable — no database or schema changes.

### External Dependencies

- [Trivy](https://trivy.dev/) — vulnerability scanner, expected on the developer's `PATH`; install instructions already documented in `.claude/skills/trivy-scan/setup.md`. No new Python/Poetry dependency.

## User Stories

Originating issue: meta-projects#41 — fleet-wide rollout of a fail-closed Trivy pre-push CVE gate across projects. This spec is the btc-predictor-specific implementation.

## Testing Strategy

### Unit Tests
Not applicable — this is a shell script wrapping an external CLI tool invoked by a git hook, not application code with a pytest suite.

### Integration Tests
- `pre-commit run --hook-stage push trivy-cve-gate --all-files` — confirms the hook is registered correctly and runs the script.
- `trivy fs . --scanners vuln --severity CRITICAL --ignore-unfixed` run directly against the repo — confirms a clean baseline (0 findings in `poetry.lock` and `shared/poetry.lock`) so the gate doesn't immediately block pushes on landing.

### E2E / Manual Verification
- `pre-commit run --hook-stage push --all-files` run locally to confirm both `trivy-cve-gate` and `pytest-docker` execute in order under the real pre-push stage.
- Push the feature branch and open a PR to confirm the hook doesn't interfere with normal push behavior on a clean repo.

## Boundaries & Constraints

### In Scope
- `scripts/hooks/trivy-scan.sh` (new script)
- `.pre-commit-config.yaml` (new local hook entry, pre-push stage)
- `scripts/hooks/README.md` and `scripts/setup-hooks.sh` (additive doc mentions)
- This spec file

### Out of Scope
- Changing severity thresholds, adding HIGH/MEDIUM scanning, or scanning secrets/misconfigurations in this hook (Trivy's `vuln` scanner + `CRITICAL` only, matching the fleet-wide rollout spec)
- CI-hosted Trivy scanning (this is a local pre-push gate only; a hosted CI equivalent, if wanted, is a separate future spec)
- Any change to `scripts/hooks/monitor-railway.sh`, `run-mypy.sh`, or post-push hooks
- Auto-installing Trivy — the hook fails closed and points to the setup skill instead

### Technical Constraints
- Must use the `pre-commit` framework's existing `- repo: local` hook mechanism — no `.githooks/`, no `core.hooksPath` changes, no hand-written `.git/hooks/pre-push`
- Must not reorder or modify the existing `pytest-docker` or `mypy-docker` hooks
- Script must be POSIX-shell-compatible (`#!/usr/bin/env bash`, `set -uo pipefail`) and executable (`chmod +x`)

## Success Criteria

- [x] `scripts/hooks/trivy-scan.sh` exists, is executable, and fails closed when `trivy` is missing or a CRITICAL fixable CVE is found
- [x] `trivy-cve-gate` is registered in `.pre-commit-config.yaml`, ordered before `pytest-docker`, `stages: [pre-push]`
- [x] `scripts/hooks/README.md` and `scripts/setup-hooks.sh` document the new step
- [x] `trivy fs . --scanners vuln --severity CRITICAL --ignore-unfixed` confirms a clean baseline (0 findings) at implementation time
- [x] `pre-commit run --hook-stage push trivy-cve-gate --all-files` passes in isolation. Running the full `--hook-stage push --all-files` (both hooks) also exercised `pytest-docker`, which failed with 82 `psycopg2.errors.UndefinedTable: relation "predictions" does not exist` errors — a pre-existing stale local Docker Postgres volume/migration-state issue, unrelated to this change and not touched by this diff; `trivy-cve-gate` itself passed cleanly ahead of it in the same run. Left for CI (fresh database) and human review to confirm on a clean environment.
- [x] No existing hook (`pytest-docker`, `mypy-docker`, `gitleaks`, `ruff`) or unrelated script (`monitor-railway.sh`, `run-mypy.sh`) was modified

## Implementation Plan

Single-phase change, no separate plan file needed given the small, well-bounded scope:
1. Write this spec.
2. Add `scripts/hooks/trivy-scan.sh`, `chmod +x`.
3. Register `trivy-cve-gate` in `.pre-commit-config.yaml` ahead of `pytest-docker`.
4. Update `scripts/hooks/README.md` and `scripts/setup-hooks.sh`.
5. Verify with a local Trivy scan and `pre-commit run --hook-stage push --all-files`.
6. Open a PR against `main` referencing meta-projects#41.

## Changelog

<!-- Only used once this spec has shipped (status reached `completed`) and gets touched again. Before editing Requirements/Architecture above, append a dated entry here using delta markers, so the audit trail survives the in-place rewrite. Leave empty until the first post-completion change. -->
