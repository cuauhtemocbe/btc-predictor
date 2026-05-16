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

# Copy API application code
COPY btc-api/ ./api/

# Install API dependencies
WORKDIR /app/api
RUN poetry install --no-interaction --no-ansi --only main --no-root

# Change ownership and switch to non-root user
WORKDIR /app
RUN chown -R appuser:appgroup /app
USER appuser

CMD uvicorn btc_api.main:app --host 0.0.0.0 --port ${PORT:-8000}
