FROM python:3.13.18-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/workers \
    POETRY_VERSION=2.3.3 \
    POETRY_VIRTUALENVS_CREATE=false

# Patch zlib until the pinned base digest ships it: the base has zlib1g
# 1:1.3.dfsg+really1.3.1-1+b1 (CVE-2026-76844, CVE-2026-85091, fixed in
# +deb13u1). Remove this step after bumping the digest to an image that already
# includes the fix.
RUN apt-get update && \
    apt-get install -y --no-install-recommends --only-upgrade zlib1g && \
    rm -rf /var/lib/apt/lists/*

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
