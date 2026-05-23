FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/workers \
    POETRY_VERSION=2.3.3 \
    POETRY_HOME=/opt/poetry \
    POETRY_VIRTUALENVS_CREATE=false

# Upgrade pip and install Poetry with security fixes
RUN pip install --no-cache-dir --upgrade pip==26.1 && \
    pip install --no-cache-dir poetry==$POETRY_VERSION && \
    addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Copy all source code and dependencies
COPY pyproject.toml poetry.lock* ./
COPY shared/ ./shared/
COPY api-service/ ./api-service/
COPY workers/ ./workers/
COPY scripts/ ./scripts/
COPY entrypoint.sh ./

# Install all dependencies from root (ensures consistent versions via poetry.lock)
RUN poetry install --no-interaction --no-ansi --only main --no-root

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Change ownership and switch to non-root user
WORKDIR /app
RUN chown -R appuser:appgroup /app
USER appuser

# Run entrypoint script (migrations + uvicorn)
CMD ["/app/entrypoint.sh"]
