---
title: CI/CD Pipeline with GitHub Actions
status: completed
created: 2026-08-08
updated: 2026-10-06
issue: "#33"
---

# CI/CD Pipeline with GitHub Actions

**Objective.** Run the Docker-based quality gate on every pull request and every push to `main`, and report mutation testing on a schedule. Railway deployment stays with its native GitHub integration. Scenarios: issue [#33](https://github.com/cuauhtemocbe/btc-predictor/issues/33).

## Decisions

- `.github/workflows/ci.yml` (the check `Docker quality gate`) builds the Docker Compose services and runs, inside the containers, Ruff lint and format, mypy strict, pytest with the coverage threshold, and uploads the coverage XML as an artifact. Docker resources are stopped even when a check fails.
- `.github/workflows/quality.yml` runs Cosmic Ray weekly and on manual dispatch, with a 60-minute job limit, and uploads the report.
- Deployment is not duplicated in Actions: Railway already deploys `main` through its own integration, and a second path could race it or deploy twice.
- Workflows have read-only repository permissions and expose no secrets to pull requests. All Python checks run inside Docker, using the repository Dockerfile and the Poetry lockfile.
- `scripts/tests/test_ci_workflows.py` pins the triggers, the Docker commands, the quality commands and the mutation schedule.

## Left out on purpose

Branch protection (issue #49, see `repo-hardening.md`), pull-request preview environments, a second Railway deployment mechanism and any change to Railway infrastructure.

## Risks

- Mutation runtime may exceed the job limit as the suite grows. Mitigation: it only runs on a schedule and the job is capped (later reworked in #192 to a 45-minute budget that publishes a partial report).
- Railway's deployment behaviour is configured outside the repository. Mitigation: the native integration is the single deployment owner.

Plan: `ci-cd-pipeline-plan.md`.
