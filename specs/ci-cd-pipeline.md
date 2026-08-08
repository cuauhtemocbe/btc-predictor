---
title: CI/CD Pipeline with GitHub Actions
status: completed
created: 2026-08-08
updated: 2026-08-08
issue: #33
---

# CI/CD Pipeline with GitHub Actions

## Objective

Run the repository's Docker-based quality gate automatically for every push and
pull request, report scheduled mutation-testing results, and deploy all
Railway services after changes land on `main`.

## Context

The repository currently relies on local Docker hooks for Ruff, mypy, pytest,
and coverage. Without hosted CI, a pull request can be merged without proving
that the clean container environment still passes. Railway deploys production
from `main`, so deployment must remain restricted to trusted branch updates.

## Requirements

### Functional Requirements

- [x] Run Ruff linting and formatting checks in Docker on pushes and pull requests.
- [x] Run mypy strict checks for the shared package in Docker.
- [x] Run pytest with the repository's coverage threshold in Docker.
- [x] Publish the coverage XML as a CI artifact.
- [x] Run Cosmic Ray mutation testing weekly and on manual dispatch.
- [x] Deploy the API, fetch-price, daily, and weekly Railway services after successful CI on `main`.
- [x] Keep Railway credentials available only to the deployment workflow.

### Non-Functional Requirements

- [x] Reproducibility: CI uses the repository Dockerfile and Poetry lockfile.
- [x] Security: workflows use least-privilege read permissions and do not expose secrets to PRs.
- [x] Feedback: failed quality commands must fail the GitHub check.
- [x] Cleanup: Docker resources are stopped even when a check fails.

## Architecture

### Components

- `.github/workflows/ci.yml`: blocking PR and push checks.
- `.github/workflows/quality.yml`: scheduled mutation-testing report.
- `.github/workflows/deploy.yml`: production Railway deployment.
- `scripts/tests/test_ci_workflows.py`: regression tests for workflow coverage.

### External Dependencies

- GitHub Actions checkout and artifact actions.
- Docker Compose and the repository's `Dockerfile.dev`.
- Railway CLI and a project-scoped `RAILWAY_TOKEN`.

## User Stories

See GitHub issue [#33](https://github.com/cuauhtemocbe/btc-predictor/issues/33).

## Testing Strategy

### Unit Tests

Test workflow definitions as repository configuration: required triggers,
Docker commands, quality commands, mutation schedule, and Railway secrets.

### Integration Tests

The CI workflow itself builds and runs the Docker Compose services, then runs
the complete Ruff, mypy, and pytest quality gate.

### E2E Tests

The deployment workflow is verified by GitHub Actions and Railway deployment
status after a merge to `main`.

## Boundaries & Constraints

### In Scope

- Hosted CI quality checks.
- Scheduled mutation testing.
- Railway deployment trigger for the four application services.
- Documentation for required repository secrets.

### Out of Scope

- Configuring GitHub branch protection rules; tracked separately by issue #49.
- Preview environments for pull requests.
- Provisioning or changing Railway infrastructure.

### Technical Constraints

- All Python checks must run inside Docker.
- Deployments must run only from `main`.
- The Railway project token must be configured as the `RAILWAY_TOKEN` secret.

## Success Criteria

- [x] A PR receives a failing GitHub check when Ruff, mypy, or pytest fails.
- [x] A successful CI run produces a downloadable coverage artifact.
- [x] A weekly workflow produces a Cosmic Ray report artifact.
- [x] A successful CI run for `main` deploys the four configured Railway services.
- [x] No CI workflow grants write permissions to repository contents.

## Implementation Plan

Implemented in this repository by `.github/workflows/ci.yml`,
`.github/workflows/quality.yml`, and `.github/workflows/deploy.yml`.
