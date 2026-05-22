#!/bin/bash
set -e

echo "🧪 Running tests in Docker..."

# Check if Docker Compose services are running
if ! docker compose ps | grep -q "api.*running"; then
    echo "📦 Starting Docker Compose services..."
    docker compose up -d

    # Wait for services to be ready
    echo "⏳ Waiting for services to be ready..."
    sleep 5

    # Wait for API container to be healthy
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

    # Wait for Postgres to be ready
    echo "⏳ Waiting for Postgres to be ready..."
    timeout=30
    elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if docker compose exec -T postgres pg_isready -U btcpredictor &>/dev/null; then
            break
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    if [ $elapsed -eq $timeout ]; then
        echo "❌ Timeout waiting for Postgres to start"
        exit 1
    fi

    echo "✅ Services are ready"
else
    echo "✅ Docker Compose services already running"
fi

# Run tests with coverage
echo "🧪 Running pytest with coverage..."
if ! docker compose exec -T api pytest --cov --cov-report=term-missing --cov-fail-under=90; then
    echo "❌ Tests failed or coverage below 90%. Fix tests before pushing."
    exit 1
fi

echo "✅ All tests passed!"
exit 0
