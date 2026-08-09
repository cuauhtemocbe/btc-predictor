# Implementation Plan: CI/CD Pipeline with GitHub Actions

**Spec**: [ci-cd-pipeline.md](ci-cd-pipeline.md)
**Created**: 2026-08-08
**Status**: completed

## Components

### 1. Docker CI quality gate

- **Purpose**: Run Ruff, mypy, pytest, and coverage on every push and pull request.
- **Files**: `.github/workflows/ci.yml`, `docker-compose.yml`
- **Effort**: M

### 2. Scheduled mutation testing

- **Purpose**: Run Cosmic Ray weekly and retain the report as an artifact.
- **Files**: `.github/workflows/quality.yml`
- **Effort**: S

### 3. Railway deployment integration

- **Purpose**: Preserve Railway's existing native GitHub deployment without duplicating it in Actions.
- **Files**: Railway project configuration, no new workflow file
- **Effort**: XS

### 4. Documentation and regression tests

- **Purpose**: Document workflow ownership and protect contracts from accidental removal.
- **Files**: `README.md`, `specs/ci-cd-pipeline.md`, `scripts/tests/test_ci_workflows.py`
- **Effort**: S

## Dependencies

### Build Order

1. Docker CI quality gate
2. Workflow contract tests
3. Scheduled mutation testing
4. Railway integration compatibility
5. Documentation and verification

### External Dependencies

- GitHub-hosted Ubuntu runners with Docker Compose.
- Existing Railway native GitHub integration.

## Risks & Assumptions

### Risks

- **Mutation runtime**: Cosmic Ray may exceed the weekly job timeout as the test suite grows. Mitigation: keep it scheduled and cap execution at 60 minutes.
- **Railway integration drift**: Deployment behavior is configured outside the repository. Mitigation: keep the native integration as the single deployment owner.

### Assumptions

- Railway service build configuration remains managed by the linked Railway services.
- Railway is already configured to deploy from GitHub after changes to `main`.

## Milestones

- [x] Docker quality gate passes in a clean container.
- [x] Workflow definitions pass actionlint.
- [x] Workflow contract tests pass.
- [x] The repository has no duplicate Railway deployment workflow.

## Tasks

### Foundation

- [x] **Task 1**: Add the pull request and push CI workflow.
  - **Acceptance**: Ruff, mypy, and pytest run in Docker and failures fail the job.
  - **Files**: `.github/workflows/ci.yml`
  - **Tests**: Full Docker quality gate.
  - **Effort**: M

### Integration

- [x] **Task 2**: Add scheduled mutation testing and artifact upload.
  - **Acceptance**: Weekly and manual triggers run Cosmic Ray and retain a report.
  - **Files**: `.github/workflows/quality.yml`
  - **Tests**: actionlint and workflow contract tests.
  - **Effort**: S

- [x] **Task 3**: Keep Railway deployment owned by the native GitHub integration.
  - **Acceptance**: No GitHub Actions workflow requires Railway credentials or duplicates deployment.
  - **Files**: `.github/workflows/`
  - **Tests**: workflow contract tests and GitHub checks.
  - **Effort**: XS

### Polish

- [x] **Task 4**: Document setup and add regression tests.
  - **Acceptance**: Workflow responsibilities and Railway ownership are documented.
  - **Files**: `README.md`, `scripts/tests/test_ci_workflows.py`, `specs/`
  - **Tests**: Four passing workflow contract tests.
  - **Effort**: S

## Effort Estimate

**Total Estimated Days**: 1-2 days

| Phase | Effort |
|-------|--------|
| Foundation | 0.5 day |
| Features | 0.5 day |
| Integration | 0.5 day |
| Testing & Polish | 0.5 day |
