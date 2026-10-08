# Git Hooks Setup

This project uses [pre-commit](https://pre-commit.com/) framework to manage git hooks.

## Quick Setup

```bash
# Install pre-commit (only once per machine)
pipx install pre-commit

# Install the git hooks (only once per repo clone)
pre-commit install --install-hooks

# Install pre-push hooks (for tests)
pre-commit install --hook-type pre-push
```

The hooks are installed once per clone. The shims that `pre-commit install` generates in `.git/hooks/`
pin the path of the Python interpreter of the pre-commit that installed them. Use `pipx install pre-commit`
as the install method: it keeps pre-commit in its own venv. `pip install pre-commit` also works, but a
pip install into a venv breaks the same way when that venv's Python changes (see
[Troubleshooting: `No module named pre_commit`](#troubleshooting-no-module-named-pre_commit)).

## What Gets Checked?

### Pre-commit (before each commit)
- ✅ **Ruff lint** - Catches code issues, auto-fixes when possible (`shared`, `api-service`, `workers`, `scripts`)
- ✅ **Ruff format** - Ensures consistent code style (same paths)
- ✅ **mypy --strict** - Runs in Docker on `shared`, `workers`, `api` and `scripts`, test code included (`scripts/hooks/run-mypy.sh`, same command as CI)

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

## Manual execution

```bash
pre-commit run --all-files                          # every pre-commit hook
pre-commit run --hook-stage push --all-files        # the pre-push hooks
pre-commit run ruff --all-files                     # one hook
```

## Troubleshooting: `No module named pre_commit`

**Symptom:** `git commit` or `git push` fails with `.../bin/python: No module named pre_commit`,
typically right after a system Python upgrade.

**Cause:** the shims `.git/hooks/pre-commit` and `.git/hooks/pre-push` hard-code `INSTALL_PYTHON=<interpreter
that ran pre-commit install>` (for a pipx install, `~/.local/share/pipx/venvs/pre-commit/bin/python`). The shim
falls back to `pre-commit` on `PATH` only when that file is missing. After a system Python upgrade the
pipx venv's `bin/python` points at the new system Python, which has no `pre_commit` module.

**Fix:**

```bash
# Rebuild the pre-commit venv (or `pipx reinstall-all` if other pipx tools broke too)
pipx reinstall pre-commit

# Check it works, then make a test commit
pre-commit --version
```

Re-run `pre-commit install --install-hooks` and `pre-commit install --hook-type pre-push` only when the
shim path itself changed (a different install method or a different machine).

`git worktree` checkouts share the same `.git/hooks`, so one repair fixes all of them.

⚠️ **Do not use `--no-verify` to get around it:** it also skips the gitleaks secret scan on every commit.

## Troubleshooting: the push fails after the hooks ran

**Symptom:** `git push` fails with `Connection to github.com closed by remote host` after the pre-push hooks
(Trivy, the full test suite, the coverage thresholds) ran for several minutes. The hooks themselves passed.

**Fix:** push again with SSH keep-alive packets, so GitHub does not close the connection while the hooks run:

```bash
GIT_SSH_COMMAND="ssh -o ServerAliveInterval=10 -o ServerAliveCountMax=60" git push
```

The hooks run again in full. Do not use `--no-verify`.

## Bypass hooks

`git commit --no-verify` and `git push --no-verify` skip the hooks (the first also skips the gitleaks scan). Use them only for WIP commits on a feature branch.

Other problems: if the hooks do not run, reinstall them (`pre-commit uninstall`, then the two `pre-commit install` commands of the quick setup); if the pre-push hook cannot reach Docker, run `docker compose up -d` and check `docker compose ps`; to refresh hook versions run `pre-commit autoupdate`, and `pre-commit clean` before reinstalling.

## Configuration

Hooks are configured in `.pre-commit-config.yaml` at the repo root.

Documentation: <https://pre-commit.com/>.
