# ============================================================================
# Stage 1: Base - Common dependencies for all services
# ============================================================================
FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/workers \
    POETRY_VERSION=2.3.3 \
    POETRY_HOME=/opt/poetry \
    POETRY_VIRTUALENVS_CREATE=false

# Upgrade pip and install Poetry
RUN pip install --no-cache-dir --upgrade pip==26.1 && \
    pip install --no-cache-dir poetry==$POETRY_VERSION

WORKDIR /app

# Copy dependency files and shared package
COPY pyproject.toml poetry.lock* ./
COPY shared/ ./shared/

# Install base dependencies (sqlalchemy, psycopg2, alembic, pydantic-settings, shared)
RUN poetry install --no-interaction --no-ansi --only main --no-root

# ============================================================================
# Stage 2: API Service
# ============================================================================
FROM base AS api

# Install API dependencies (fastapi, uvicorn, jinja2, etc.)
RUN poetry install --no-interaction --no-ansi --only main --with api --no-root

# Copy API service code
COPY api-service/ ./api-service/
COPY scripts/ ./scripts/
COPY entrypoint.sh ./

# Create non-root user and set permissions
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser && \
    chmod +x /app/entrypoint.sh && \
    chown -R appuser:appgroup /app

USER appuser

# Probes GET /health so Railway/Docker can detect a dead uvicorn process.
# Uses python's stdlib instead of curl/wget, neither of which ships with
# the slim base image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('PORT', '8000') + '/health', timeout=3)" || exit 1

CMD ["/app/entrypoint.sh"]

# ============================================================================
# Stage 3: Fetch Price Worker
# ============================================================================
FROM base AS fetch

# Install fetch dependencies (httpx, urllib3, yarl)
RUN poetry install --no-interaction --no-ansi --only main --with fetch --no-root

# Copy fetch_price worker code
COPY workers/fetch_price/ ./workers/fetch_price/

# Create non-root user and set permissions
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser && \
    chown -R appuser:appgroup /app

USER appuser
CMD ["python", "-m", "fetch_price.main"]

# ============================================================================
# Stage 4: ML Workers (Daily & Weekly)
# ============================================================================
FROM base AS ml-worker

# Install ML dependencies (scikit-learn, tensorflow, xgboost, statsmodels, numpy)
RUN poetry install --no-interaction --no-ansi --only main --with ml --no-root

# Copy daily and weekly worker code
COPY workers/daily/ ./workers/daily/
COPY workers/weekly/ ./workers/weekly/

# Create non-root user and set permissions
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser && \
    chown -R appuser:appgroup /app

USER appuser
# Default to daily worker (can be overridden in Railway)
CMD ["python", "-m", "daily.main"]
