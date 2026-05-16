FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    POETRY_VERSION=1.8.4 \
    POETRY_HOME=/opt/poetry \
    POETRY_VIRTUALENVS_CREATE=false

RUN pip install --no-cache-dir poetry==$POETRY_VERSION && \
    addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Copy root dependencies
COPY pyproject.toml poetry.lock* ./

# Copy shared package first (needed by main app)
COPY shared/pyproject.toml shared/poetry.lock* ./shared/
COPY shared/btc_shared/ ./shared/btc_shared/

# Install dependencies (includes shared package)
RUN poetry install --no-interaction --no-ansi --only main --no-root

# Copy application code
COPY src/ ./src/

# Change ownership and switch to non-root user
RUN chown -R appuser:appgroup /app
USER appuser

CMD uvicorn src.app.main:app --host 0.0.0.0 --port ${PORT:-8000}
