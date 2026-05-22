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
- ✅ **Ruff lint** - Catches code issues, auto-fixes when possible
- ✅ **Ruff format** - Ensures consistent code style

### Pre-push (before pushing to remote)
- ✅ **Pytest** - Runs all tests with 90% coverage requirement
- ✅ **Docker aware** - Automatically starts Docker Compose if needed

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
