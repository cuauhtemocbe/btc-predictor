---
title: Trivy Fail-Closed CVE Gate (Pre-Push)
status: completed
created: 2026-09-14
updated: 2026-10-06
issue: "meta-projects#41"
---

# Trivy Fail-Closed CVE Gate (Pre-Push)

**Objective.** A CRITICAL, fixable CVE in a dependency blocks `git push` locally, before it can reach `main` and Railway's auto-deploy. This repository's part of a rollout across projects (meta-projects#41).

## Decisions

- **Hook, not a hand-written file.** Git hooks come from the pre-commit framework (`.pre-commit-config.yaml`, `pre-commit install --hook-type pre-push`), which regenerates `.git/hooks/pre-push`; no `.githooks/`, no `core.hooksPath`.
- **`scripts/hooks/trivy-scan.sh`** runs `trivy fs . --scanners vuln --severity CRITICAL --exit-code 1 --ignore-unfixed --quiet`. It fails closed: if `trivy` is not on `PATH` it exits non-zero and points to `.claude/skills/trivy-scan/setup.md` instead of skipping or installing Trivy.
- **`trivy-cve-gate`** is a local hook (`stages: [pre-push]`, `always_run: true`) registered before `pytest-docker`, so the seconds-long scan fails fast ahead of the full test suite.
- **Scope:** vulnerabilities only, CRITICAL only, as in the rollout spec. Secrets and misconfiguration scans and a hosted-CI Trivy scan were left out of this hook (container scanning later arrived as `.github/workflows/container-security.yml`).
- The scan started from a clean baseline: 0 findings in `poetry.lock` and `shared/poetry.lock`.

Docs: `scripts/hooks/README.md` and `scripts/setup-hooks.sh` list the step. Verified with `pre-commit run --hook-stage push trivy-cve-gate --all-files`.
