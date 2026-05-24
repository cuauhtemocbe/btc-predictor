# Railway Multi-Stage Docker Configuration

## Overview

Este proyecto usa un **Dockerfile multi-stage con targets** para optimizar el tamaño de las imágenes por servicio.

**Dockerfile único** con 4 targets:
- `base` → Dependencias comunes (SQLAlchemy, PostgreSQL, Alembic)
- `api` → API service (base + FastAPI + Uvicorn + Jinja2)
- `fetch` → Fetch price worker (base + httpx + urllib3)
- `ml-worker` → Daily/Weekly workers (base + scikit-learn + TensorFlow + XGBoost)

---

## Configuración en Railway

### Servicio: `api`

**Settings → Build:**
```
Build Method: Dockerfile
Dockerfile Path: Dockerfile
Docker Build Target: api
```

**Settings → Deploy:**
```
Start Command: /app/entrypoint.sh
```

---

### Servicio: `fetch-price`

**Settings → Build:**
```
Build Method: Dockerfile
Dockerfile Path: Dockerfile
Docker Build Target: fetch
```

**Settings → Deploy:**
```
Start Command: python -m fetch_price.main
```

**Cron Settings:**
```
Cron Schedule: 0 6 * * *
```

---

### Servicio: `daily`

**Settings → Build:**
```
Build Method: Dockerfile
Dockerfile Path: Dockerfile
Docker Build Target: ml-worker
```

**Settings → Deploy:**
```
Start Command: python -m daily.main
```

**Cron Settings:**
```
Cron Schedule: 0 7 * * *
```

---

### Servicio: `weekly`

**Settings → Build:**
```
Build Method: Dockerfile
Dockerfile Path: Dockerfile
Docker Build Target: ml-worker
```

**Settings → Deploy:**
```
Start Command: python -m weekly.main
```

**Cron Settings:**
```
Cron Schedule: 0 7 * * 1
```

---

## Tamaños de Imagen Esperados

| Servicio | Target | Tamaño Estimado | Reducción vs Monolítico |
|----------|--------|----------------|-------------------------|
| API | `api` | ~200MB | -50% |
| Fetch Price | `fetch` | ~80MB | -80% |
| Daily Worker | `ml-worker` | ~180MB | -55% |
| Weekly Worker | `ml-worker` | ~180MB | -55% |

**Nota:** Daily y Weekly comparten el mismo target (`ml-worker`) pero con diferente `CMD`.

---

## Alternativa: railway.toml (por servicio)

Si prefieres configuración como código, puedes crear archivos `railway.toml` por servicio:

### `railway.api.toml`
```toml
[build]
builder = "dockerfile"
dockerfilePath = "Dockerfile"
target = "api"

[deploy]
startCommand = "/app/entrypoint.sh"
```

### `railway.fetch.toml`
```toml
[build]
builder = "dockerfile"
dockerfilePath = "Dockerfile"
target = "fetch"

[deploy]
startCommand = "python -m fetch_price.main"
```

### `railway.daily.toml`
```toml
[build]
builder = "dockerfile"
dockerfilePath = "Dockerfile"
target = "ml-worker"

[deploy]
startCommand = "python -m daily.main"
```

### `railway.weekly.toml`
```toml
[build]
builder = "dockerfile"
dockerfilePath = "Dockerfile"
target = "ml-worker"

[deploy]
startCommand = "python -m weekly.main"
```

**Uso:** Especifica el archivo de configuración en Railway UI:
```
Settings → Build → Railway Config File: railway.api.toml
```

---

## Verificación Local

### Construir cada target:

```bash
# API
docker build --target api -t btc-predictor-api:latest .

# Fetch Price
docker build --target fetch -t btc-predictor-fetch:latest .

# ML Workers (Daily/Weekly)
docker build --target ml-worker -t btc-predictor-ml:latest .
```

### Verificar tamaños:

```bash
docker images | grep btc-predictor
```

### Probar cada servicio:

```bash
# API
docker run -p 8000:8000 --env-file .env btc-predictor-api:latest

# Fetch (one-shot)
docker run --env-file .env btc-predictor-fetch:latest

# Daily (one-shot)
docker run --env-file .env btc-predictor-ml:latest python -m daily.main

# Weekly (one-shot)
docker run --env-file .env btc-predictor-ml:latest python -m weekly.main
```

---

## Grupos de Dependencias (pyproject.toml)

Las dependencias están organizadas en grupos opcionales:

```toml
[tool.poetry.dependencies]
# Base (todos los servicios)
sqlalchemy, psycopg2-binary, alembic, pydantic-settings, shared

[tool.poetry.group.api.dependencies]
# Solo API
fastapi, uvicorn, starlette, jinja2, httpx

[tool.poetry.group.fetch.dependencies]
# Solo fetch_price
httpx, urllib3, yarl

[tool.poetry.group.ml.dependencies]
# Solo daily/weekly
scikit-learn, numpy, tensorflow-cpu, xgboost, statsmodels
```

**Instalación en cada stage:**
```bash
# Base
poetry install --only main

# API
poetry install --only main --with api

# Fetch
poetry install --only main --with fetch

# ML Workers
poetry install --only main --with ml
```

---

## Rollback a Monolítico

Si necesitas volver al Dockerfile monolítico:

1. Revertir `pyproject.toml` (mover dependencias de grupos a `[tool.poetry.dependencies]`)
2. Usar Dockerfile simple:
   ```dockerfile
   FROM python:3.13-slim
   # ... (copiar todo y poetry install --only main)
   ```
3. Remover `Docker Build Target` en Railway

---

## Próximos Pasos

1. ✅ Actualizar `poetry.lock` con nuevos grupos
2. ⏸️  Construir imágenes localmente para verificar
3. ⏸️  Configurar targets en Railway UI
4. ⏸️  Deploy y verificar tamaños en Railway dashboard
