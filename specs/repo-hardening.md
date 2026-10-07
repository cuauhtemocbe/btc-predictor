---
title: Repo Hardening — Python Version Alignment, Hosted CI, Branch Protection
status: completed
created: 2026-08-07
updated: 2026-10-06
issues: "#32, #33, #49"
---

# Repo Hardening: Python Version Alignment, Hosted CI, Branch Protection

**Objective.** Close three gaps between the repository and its documented standards: Poetry packages that pinned different Python versions (#32), no hosted CI (#33) and no protection on `main`, the branch Railway deploys from (#49). They were bundled so branch protection could require the CI check from day one, and the CI workflow would build against a consistent Python version.

## Decisions

- **Python `^3.13` everywhere** (root and `shared/` were `^3.12` while `api-service/` and `workers/fetch_price/` were `^3.13`; the Docker image and mypy already targeted 3.13). `poetry.lock` was regenerated with `poetry lock --no-update`.
- **One CI workflow, no hand-maintained copy of the commands.** The workflow brings up the Docker Compose stack and runs the same checks as `scripts/validate.sh` inside the `api` container (now `ci.yml`, see `ci-cd-pipeline.md`).
- **No Actions deploy workflow.** Issue #33 proposed `deploy.yml` with a Railway token; Railway already deploys `main` through its native integration, and a second path would duplicate or race it. The spec also left scheduled mutation testing out; `quality.yml` added it later (#33, #192).
- **Branch protection on `main`:** force-pushes and deletion blocked, required status checks, `enforce_admins: false` so the owner can push directly. The exception is documented in `CLAUDE.md` (Main Branch Protection), which also lists the required checks. Required pull-request reviews were left out because the repository has one maintainer.

Verification the spec asked for: a pull request shows the CI check, `gh api repos/cuauhtemocbe/btc-predictor/branches/main/protection` answers 200 instead of 404, and the full local suite still passes.
