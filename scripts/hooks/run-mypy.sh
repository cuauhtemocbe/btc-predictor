#!/bin/bash
set -e

echo "🔍 Running mypy --strict on shared/ in Docker..."

if ! docker compose ps | grep -q "api.*running"; then
    echo "📦 Starting Docker Compose services..."
    docker compose up -d

    timeout=30
    elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if docker compose exec -T api echo "ready" &>/dev/null; then
            break
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    if [ $elapsed -eq $timeout ]; then
        echo "❌ Timeout waiting for services to start"
        exit 1
    fi
fi

if ! docker compose exec -T api sh -c "cd /app && python -m mypy shared/shared shared/btc_shared shared/tests"; then
    echo "❌ mypy found type errors in shared/. Fix them before committing."
    exit 1
fi

echo "✅ mypy --strict passed on shared/"
exit 0
