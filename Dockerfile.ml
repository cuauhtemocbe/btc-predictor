FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91

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

RUN poetry install --no-interaction --no-ansi --with ml --without dev --no-root && \
    chown -R appuser:appgroup /app

USER appuser
CMD ["python", "-m", "daily.main"]
