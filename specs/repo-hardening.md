---
title: Repo Hardening — Python Version Alignment, Hosted CI, Branch Protection
status: draft
created: 2026-08-07
updated: 2026-08-07
issues: "#32, #33, #49"
---

# Repo Hardening: Python Version Alignment, Hosted CI, Branch Protection

## Objective

Close the three remaining gaps between the repo's actual state and its documented development standards: an inconsistent Python version constraint across Poetry packages (#32), no hosted CI to catch broken code before it reaches `main` (#33), and no branch protection to stop a bad push or force-push from reaching the branch Railway auto-deploys from (#49).

## Context

### Current State

- **Python version drift (#32)**: root `pyproject.toml` and `shared/pyproject.toml` both pin `python = "^3.12"`, while `api-service/pyproject.toml` and `workers/fetch_price/pyproject.toml` pin `^3.13`. The Dockerfile base image (`python:3.13-slim`) and `[tool.mypy] python_version = "3.13"` both target 3.13. `workers/daily` has no `pyproject.toml` of its own (it rides on the root package). Poetry may be resolving/locking dependencies against the 3.12 floor for two of the four packages while the actual runtime everywhere is 3.13.
- **No hosted CI (#33)**: `.github/` currently only has `dependabot.yml` (which already anticipates a `github-actions` update ecosystem — someone planned for workflows to exist). All quality gating today is local-only: `.pre-commit-config.yaml` runs `ruff` + `ruff-format` on commit and `scripts/hooks/run-mypy.sh` (mypy --strict on `shared/`) + `scripts/hooks/run-tests.sh` (pytest via Docker) on push. `scripts/validate.sh` is the single source of truth those hooks and `make validate` both call — lint, format check, `pytest --cov` with `--cov-fail-under=90`. Nothing runs this in a hosted environment, so a contributor who skips hooks (or a direct push) can land broken code with no independent verification.
- **No branch protection (#49)**: `gh api repos/cuauhtemocbe/btc-predictor/branches/main/protection` returns `404 Branch not protected`. `main` is what Railway auto-deploys from on every push (see CLAUDE.md → Railway Deploy), so an accidental force-push or bad merge goes straight to production with nothing in GitHub stopping it.

### Why bundle these three

#49's own Definition of Done says: "Note added for future work: wire required status checks once issue #33 (hosted CI) exists." Since #33 is being built in this same spec, branch protection can require the CI status check from day one instead of landing as a two-phase follow-up. #32 is small and unrelated in principle, but the CI workflow built for #33 needs a correct, consistent Python version to build against — sequencing it first avoids standing up CI against a config that's already known to be wrong.

### Scope decision: no GitHub Actions deploy workflow

Issue #33's original text proposes `.github/workflows/deploy.yml` and a Railway deployment token as a GitHub secret. CLAUDE.md documents that Railway already auto-deploys `api` on every push to `main` via its own native GitHub integration ("Deploy api service (automatic on push to main): `git push origin main`"). Adding a parallel GitHub Actions deploy workflow would duplicate that integration and risk racing or double-deploying. This spec builds **only** the CI quality-gate workflow (`ci.yml`); deploy stays exactly as it is today, owned by Railway. If this is wrong, flag it before approval — swapping the deploy mechanism is a bigger change than this spec is scoped for.

### Scope decision: no scheduled mutation-testing workflow

Issue #33 also lists "mutation testing runs on schedule" as a scenario. Cosmic Ray runs already exist as a manual/documented process (CLAUDE.md → Mutation Testing section, `mutation_testing_report.md`). A full Cosmic Ray run is slow and not part of the fast feedback loop this spec is targeting. Out of scope here; can be a separate future spec if wanted.

## Requirements

### Functional Requirements

- [ ] `pyproject.toml` (root) and `shared/pyproject.toml` both specify `python = "^3.13"`
- [ ] `poetry.lock` (root) is regenerated (`poetry lock --no-update`) to reflect the 3.13 constraint
- [ ] `docker compose build` succeeds with the updated lock file
- [ ] `.github/workflows/ci.yml` exists and runs on every `push` and `pull_request` targeting `main`
- [ ] CI brings up the same Docker Compose stack used locally (`postgres` + `api`) and runs `scripts/validate.sh` (or the equivalent ruff lint / ruff format check / pytest --cov steps it wraps) — no separate, hand-maintained copy of those commands
- [ ] CI reports a named status check (e.g. `CI / quality-gate`) visible on PRs and commits
- [ ] Branch protection is enabled on `main`:
  - Force-pushes to `main` are blocked
  - Deletion of `main` is blocked
  - The `CI / quality-gate` status check from `ci.yml` is required to pass before a PR can merge
  - `enforce_admins: false`, so the repo owner can still push directly when needed
- [ ] The `enforce_admins: false` exception is documented explicitly in `CLAUDE.md` (not left implicit)

### Non-Functional Requirements

- [ ] CI feedback time: full `ci.yml` run completes in a comparable window to the local `docker compose exec api pytest` run (~94s test suite) plus container build/startup — should not become a multi-minute bottleneck that discourages pushing
- [ ] No behavior change for local development: `docker compose`, `pre-commit`, and `scripts/validate.sh` continue to work exactly as documented in CLAUDE.md
- [ ] No change to the deploy path: Railway continues to auto-deploy `api` from `main` exactly as today

## Architecture

### Components

1. **Python version alignment** — edit `pyproject.toml` and `shared/pyproject.toml`, regenerate `poetry.lock`, verify `docker compose build`.
2. **`.github/workflows/ci.yml`** — GitHub Actions workflow: checkout, `docker compose up -d --wait`, run `scripts/validate.sh` (or its constituent `ruff check` / `ruff format --check` / `pytest --cov` commands) inside the `api` container, tear down.
3. **Branch protection on `main`** — configured via `gh api repos/cuauhtemocbe/btc-predictor/branches/main/protection --method PUT` (or an equivalent one-time script), requiring the `ci.yml` status check, blocking force-push and deletion, `enforce_admins: false`.
4. **Documentation** — `CLAUDE.md` updated with a short note on the `enforce_admins: false` exception and a mention that CI now exists (so the "no hosted CI" framing elsewhere in the doc, if any, stays accurate).

### Data Model

Not applicable — no database or schema changes.

### External Dependencies

- GitHub Actions (already available on the repo, no new account/service)
- No new Python/Poetry dependencies

## User Stories

See the originating issues:
- #32 — Align Python Version Consistency
- #33 — CI/CD Pipeline with GitHub Actions (deploy/mutation-testing portions descoped, see above)
- #49 — Enable GitHub branch protection on main

## Testing Strategy

### Unit Tests
No new application code, so no new unit tests in the usual sense. `scripts/tests/test_dev_standards.py` already exists as the pattern for asserting repo-config invariants (e.g. `test_coverage_fail_under_90_configured`); extend it with:
- A check that `pyproject.toml` and `shared/pyproject.toml` both require `^3.13`
- A check that `.github/workflows/ci.yml` exists and references `scripts/validate.sh` (or the lint/format/test commands it wraps)

### Integration Tests
- `docker compose build` succeeds locally after the lock file regeneration
- `docker compose exec api pytest` passes in full after the version bump (regression check — no dependency resolved differently under 3.13 breaks anything)

### E2E / Manual Verification
- Push a throwaway branch and open a PR to confirm the `CI / quality-gate` check appears and reflects pass/fail correctly
- Confirm `gh api repos/cuauhtemocbe/btc-predictor/branches/main/protection` no longer 404s and lists the required check
- Confirm a force-push to `main` from a non-admin context is rejected (or reason from GitHub's documented behavior + the `enforce_admins` setting if a live test isn't safe to run against the real `main`)

## Boundaries & Constraints

### In Scope
- Aligning Python version constraints across all Poetry packages
- One GitHub Actions workflow (`ci.yml`) running the existing local quality gate in a hosted environment
- Branch protection on `main` wired to that workflow's status check

### Out of Scope
- A GitHub Actions deploy workflow (Railway's native integration already handles this — see Scope decision above)
- Scheduled/hosted mutation testing (stays manual, per CLAUDE.md's existing Cosmic Ray section)
- Required PR reviews / required number of approvals (solo-maintainer repo; `enforce_admins: false` already covers the "owner can still push directly" need)
- Deploy previews for PRs

### Technical Constraints
- Must not change the Railway deploy path
- Must reuse `scripts/validate.sh` rather than re-implementing lint/format/test steps directly in the workflow YAML (per CLAUDE.md's "don't duplicate logic" philosophy)
- Container-first: any command CI runs against the app must go through `docker compose exec`, matching local dev and pre-push hooks exactly

## Success Criteria

- [ ] `pyproject.toml` and `shared/pyproject.toml` both pin `python = "^3.13"`; `docker compose build` succeeds
- [ ] `.github/workflows/ci.yml` runs on push/PR and produces a pass/fail status check
- [ ] `gh api repos/cuauhtemocbe/btc-predictor/branches/main/protection` returns 200 (not 404), with force-push and deletion blocked, the CI check required, and `enforce_admins: false`
- [ ] `CLAUDE.md` documents the `enforce_admins: false` exception explicitly
- [ ] Full local test suite (`docker compose exec api pytest`) still passes after all changes

## Implementation Plan

See `specs/repo-hardening-plan.md` (Phase 2).
