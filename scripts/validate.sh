#!/bin/bash
# Single source of truth for the local quality gate: lockfile validation,
# ruff lint, ruff format check, mypy, pytest with coverage and the per-module
# coverage thresholds (scripts/check_coverage_thresholds.py). Reused by
# `make validate` and by the
# pre-commit/pre-push git hooks so the checks never drift out of sync.
set -e

echo "🔎 Running full local quality gate..."

if ! docker compose ps | grep -q "api.*running"; then
    echo "📦 Starting Docker Compose services..."
    docker compose up -d --wait
fi

echo "🔒 Poetry lockfile check..."
if ! docker compose exec -T api poetry check --lock; then
    echo "❌ Lockfile out of sync: run poetry lock and commit the updated poetry.lock" >&2
    exit 1
fi

echo "🧹 Ruff lint..."
docker compose exec -T api ruff check shared api workers scripts

echo "🎨 Ruff format check..."
docker compose exec -T api ruff format --check shared api workers scripts

echo "🔍 mypy --strict..."
docker compose exec -T api python -m mypy \
    shared/shared shared/btc_shared shared/tests workers api scripts

echo "🧪 Pytest with coverage..."
docker compose exec -T api pytest --cov --cov-report=term-missing \
    --cov-report=xml:/tmp/coverage.xml

echo "📏 Per-module coverage thresholds..."
docker compose exec -T api python scripts/check_coverage_thresholds.py /tmp/coverage.xml

echo "✅ Validation passed: lint, format, and tests (with coverage) are all green"
