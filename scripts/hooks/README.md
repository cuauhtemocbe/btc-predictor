# Git Hooks Setup

This project uses [pre-commit](https://pre-commit.com/) framework to manage git hooks.

## Quick Setup

```bash
# Install pre-commit (only once per machine)
pip install pre-commit

# Install the git hooks (only once per repo clone)
pre-commit install --install-hooks

# Install pre-push hooks (for tests)
pre-commit install --hook-type pre-push
```

## What Gets Checked?

### Pre-commit (before each commit)
- ✅ **Ruff lint** - Catches code issues, auto-fixes when possible (`shared`, `api-service`, `workers`, `scripts`)
- ✅ **Ruff format** - Ensures consistent code style (same paths)
- ✅ **mypy --strict** - Runs in Docker on `shared`, `workers`, `api` and `scripts` (`scripts/hooks/run-mypy.sh`, same command as CI)

### Pre-push (before pushing to remote)
- ✅ **Trivy CVE gate** - Fails closed on CRITICAL, fixable vulnerabilities (runs before tests, fast-fail)
- ✅ **Pytest** - Runs all tests with 90% coverage requirement
- ✅ **Per-module coverage thresholds** - After the tests, `scripts/check_coverage_thresholds.py` checks the same `coverage.xml` against `[tool.coverage_thresholds]` in `pyproject.toml` (see below)
- ✅ **Docker aware** - Automatically starts Docker Compose if needed
- ⏭️ **Pytest skips docs/config-only pushes** - It runs only when the push touches code (`shared/`, `api-service/`, `workers/`, `scripts/`), `conftest.py`, `pyproject.toml`, `poetry.lock`, `docker-compose.yml` or a `Dockerfile*`. The Trivy gate always runs (it takes under a second)

## Per-module coverage thresholds

The global 90% gate can stay green while a trainer, a model or the backtest code is barely covered, so
each critical module has its own minimum line coverage in `[tool.coverage_thresholds]` of `pyproject.toml`
(repo-relative path = percent). The pre-push hook (through `scripts/validate.sh`) and the CI job
"Docker quality gate" run the check on the `coverage.xml` of the full pytest run, without running the suite again.

```bash
docker compose exec api pytest --cov --cov-report=xml:/tmp/coverage.xml
docker compose exec api python scripts/check_coverage_thresholds.py /tmp/coverage.xml
```

When it fails, the output ends with the verdict and one line per offending module:

```text
Coverage threshold check FAILED: 1 of 42 critical modules.
  workers/daily/trainer.py: 62.0% covered, minimum 90%
```

- `N% covered, minimum M%`: add tests for the lines `pytest --cov --cov-report=term-missing` lists as missing.
  Do not lower the minimum to get past it.
- `not in the coverage report`: no test imports the module, or it was renamed/moved. Add a test that
  exercises it, or fix the key in `pyproject.toml`.
- New critical module: add its path with a minimum (largest multiple of 5 at least 2 points below the measured value).

## Manual Execution

```bash
# Run all pre-commit hooks manually
pre-commit run --all-files

# Run only pre-push hooks
pre-commit run --hook-stage push --all-files

# Run specific hook
pre-commit run ruff --all-files
pre-commit run pytest-docker --hook-stage push

# Update hook versions
pre-commit autoupdate
```

## Bypass Hooks (use sparingly!)

```bash
# Skip pre-commit hooks
git commit --no-verify

# Skip pre-push hooks
git push --no-verify
```

⚠️ **Warning:** Only bypass hooks when absolutely necessary (e.g., WIP commits on feature branch).

## Troubleshooting

### Hooks not running?
```bash
# Reinstall hooks
pre-commit uninstall
pre-commit install --install-hooks
pre-commit install --hook-type pre-push
```

### Docker not starting?
```bash
# Manually start services
docker compose up -d

# Check services are healthy
docker compose ps
```

### Update hook dependencies
```bash
# Update to latest versions
pre-commit autoupdate

# Clean cache and reinstall
pre-commit clean
pre-commit install --install-hooks
```

## Configuration

Hooks are configured in `.pre-commit-config.yaml` at the repo root.

See: https://pre-commit.com/ for full documentation.
