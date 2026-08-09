# Railway Docker Configuration

## Overview

Cada servicio tiene su **propio Dockerfile dedicado** (no un único Dockerfile
multi-stage con targets, como en versiones anteriores de este documento):

| Servicio | Dockerfile | Grupo de dependencias |
|----------|-----------|------------------------|
| `api` | `Dockerfile.api` | `api` (FastAPI, Uvicorn, Jinja2) |
| `fetch-price` | `Dockerfile.fetch` | `fetch` (httpx, urllib3, yarl) |
| `daily` | `Dockerfile.ml` | `ml` (scikit-learn, TensorFlow, XGBoost, statsmodels) |
| `weekly-predictor` | `Dockerfile.ml` | `ml` (mismo Dockerfile que `daily`, distinto Start Command) |
| `monthly-backtest` | `Dockerfile.backtest` | `ml` |

Todos comparten el mismo `shared/` (base) instalado via
`poetry install --with <grupo> --without dev --no-root`.

---

## ⚠️ Los Start Commands viven en Railway, no en `railway.*.toml`

Este repo tiene archivos `railway.api.toml`, `railway.fetch.toml`,
`railway.daily.toml` y `railway.weekly.toml` en la raíz. **No están conectados
como config-as-code a los servicios** — cada servicio en Railway tiene su
`Build`/`Deploy` configurado directamente en el dashboard (o via
`mcp__railway__update_service` / `railway environment edit
--service-config`), independiente de esos archivos.

Esto causó un incidente real (2026-08-09): se corrigió el `startCommand` en
`railway.daily.toml` y se hizo push a `main`, pero el servicio `daily` en
Railway siguió usando el comando viejo y roto hasta que se actualizó
explícitamente con `mcp__railway__update_service` / `railway environment
edit --service-config`.

**Regla práctica:** si cambias un `startCommand`, `buildCommand`,
`dockerfilePath` o `cronSchedule`, aplícalo también en el servicio de Railway
directamente (dashboard o CLI/MCP) — no asumas que el `.toml` del repo lo
propaga solo. Verifica con:

```bash
railway environment config --json | grep -A3 '"daily"'
# o
# mcp__railway__get_service_config (service_id: daily)
```

---

## Configuración en Railway

### Servicio: `api`

**Settings → Build:**
```
Build Method: Dockerfile
Dockerfile Path: Dockerfile.api
```

**Settings → Deploy:**
```
Start Command: /app/entrypoint.sh
Restart Policy: ON_FAILURE
```

---

### Servicio: `fetch-price`

**Settings → Build:**
```
Build Method: Dockerfile
Dockerfile Path: Dockerfile.fetch
```

**Settings → Deploy:**
```
Start Command: python -m fetch_price.main
Restart Policy: NEVER
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
Dockerfile Path: Dockerfile.ml
```

**Settings → Deploy:**
```
Start Command: python -m workers.daily
Restart Policy: NEVER
```

**Cron Settings:**
```
Cron Schedule: 0 7 * * *
```

> `workers/daily/` solo expone `__main__.py` (no `main.py`) y usa imports
> absolutos (`from workers.daily import evaluator, predictor, trainer`).
> El Start Command **debe** ser `python -m workers.daily`, nunca
> `python -m daily.main` (ese módulo no existe).

---

### Servicio: `weekly-predictor`

**Settings → Build:**
```
Build Method: Dockerfile
Dockerfile Path: Dockerfile.ml
```

**Settings → Deploy:**
```
Start Command: python -m workers.weekly
Restart Policy: NEVER
```

**Cron Settings:**
```
Cron Schedule: 0 7 * * 1
```

Mismo Dockerfile que `daily` (ambos workers ML se copian en la misma
imagen), pero con `Start Command` distinto. Aplica la misma regla que
`daily`: `python -m workers.weekly`, no `python -m weekly.main`.

---

### Servicio: `monthly-backtest`

**Settings → Build:**
```
Build Method: Dockerfile
Dockerfile Path: Dockerfile.backtest
```

**Settings → Deploy:**
```
Start Command: python -m workers.backtest.main
Restart Policy: NEVER
```

**Cron Settings:**
```
Cron Schedule: 0 0 1 * *
```

---

## Grupos de Dependencias (pyproject.toml)

```toml
[tool.poetry.dependencies]
# Base (todos los servicios): sqlalchemy, psycopg2-binary, alembic, pydantic-settings

[tool.poetry.group.api.dependencies]
fastapi, uvicorn, starlette, jinja2, httpx

[tool.poetry.group.fetch.dependencies]
httpx, urllib3, yarl

[tool.poetry.group.ml.dependencies]
scikit-learn, numpy, tensorflow-cpu, xgboost, statsmodels
```

**Instalación real en cada Dockerfile** (usa `--with`, no `--only main`):
```bash
# api (Dockerfile.api)
poetry install --with api --without dev --no-root

# fetch-price (Dockerfile.fetch)
poetry install --with fetch --without dev --no-root

# daily / weekly-predictor / monthly-backtest (Dockerfile.ml / Dockerfile.backtest)
poetry install --with ml --without dev --no-root
```

---

## Verificación Local

### Construir cada imagen:

```bash
docker build -f Dockerfile.api -t btc-predictor-api:latest .
docker build -f Dockerfile.fetch -t btc-predictor-fetch:latest .
docker build -f Dockerfile.ml -t btc-predictor-ml:latest .
docker build -f Dockerfile.backtest -t btc-predictor-backtest:latest .
```

### Probar cada servicio (contra `docker compose`, no imágenes standalone):

```bash
# Manejo diario/semanal — usar el compose de desarrollo, no las imágenes de prod
docker compose exec api python -m workers.daily
docker compose exec api python -m workers.weekly
docker compose exec api python -m workers.fetch_price.main
```

Estas imágenes de producción (`Dockerfile.ml`, `Dockerfile.fetch`) no tienen
un DB local por defecto — para probarlas standalone necesitan `--env-file`
apuntando a un Postgres accesible, ver `docker-compose.yml` para las
variables requeridas.

---

## Historial

- **2026-05-24:** migración de Dockerfile monolítico con `Docker Build
  Target` a la primera versión de este documento.
- **2026-08-09:** migración de targets a Dockerfiles dedicados por servicio
  (`4c74069`); se detectó y corrigió el bug de Start Command incorrecto en
  `daily`/`weekly-predictor` descrito arriba (`c2e986c`).
