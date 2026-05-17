#!/bin/sh
set -e

echo "Running database migrations..."
cd /app/shared
python -m alembic upgrade head

echo "Starting API server..."
cd /app/api-service
exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
