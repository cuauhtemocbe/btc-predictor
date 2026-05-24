# Dockerfile for ML workers (daily, weekly)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/workers \
    POETRY_VERSION=2.3.3 \
    POETRY_VIRTUALENVS_CREATE=false

RUN pip install --no-cache-dir --upgrade pip==26.1 && \
    pip install --no-cache-dir poetry==$POETRY_VERSION && \
    addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

COPY pyproject.toml poetry.lock* ./
COPY shared/ ./shared/
COPY workers/daily/ ./workers/daily/
COPY workers/weekly/ ./workers/weekly/

# Install dependencies (base + ml group)
RUN poetry install --no-interaction --no-ansi --only main --with ml --no-root && \
    chown -R appuser:appgroup /app

USER appuser
# Default to daily (override with start command in Railway for weekly)
CMD ["python", "-m", "daily.main"]
