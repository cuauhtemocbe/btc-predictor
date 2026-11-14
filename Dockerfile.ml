FROM python:3.13.18-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/workers \
    POETRY_VERSION=2.3.3 \
    POETRY_VIRTUALENVS_CREATE=false

RUN pip install --no-cache-dir --upgrade pip==26.2.2 && \
    pip install --no-cache-dir poetry==$POETRY_VERSION && \
    addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app
COPY pyproject.toml poetry.lock* ./
COPY shared/ ./shared/
COPY workers/daily/ ./workers/daily/

RUN poetry install --no-interaction --no-ansi --with ml --without dev --no-root && \
    chown -R appuser:appgroup /app

USER appuser
CMD ["python", "-m", "workers.daily"]
