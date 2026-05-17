FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    POETRY_VERSION=2.3.3 \
    POETRY_HOME=/opt/poetry \
    POETRY_VIRTUALENVS_CREATE=false

# Upgrade pip and install Poetry with security fixes
RUN pip install --no-cache-dir --upgrade pip==26.1 && \
    pip install --no-cache-dir poetry==$POETRY_VERSION && \
    addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Copy root dependencies
COPY pyproject.toml poetry.lock* ./

# Copy shared package first (needed by api)
COPY shared/ ./shared/

# Install root dependencies
RUN poetry install --no-interaction --no-ansi --only main --no-root

# Copy API service (includes api package + pyproject.toml)
COPY api-service/ ./api-service/

# Install API dependencies
WORKDIR /app/api-service
RUN poetry install --no-interaction --no-ansi --only main --no-root

# Change ownership and switch to non-root user
WORKDIR /app
RUN chown -R appuser:appgroup /app
USER appuser

# Set working directory to api-service for uvicorn
WORKDIR /app/api-service

# Run uvicorn (using JSON array format for proper signal handling)
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
