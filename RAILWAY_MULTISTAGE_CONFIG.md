# Railway: configuración por servicio

Fuente única de qué construye y arranca cada servicio. Los pasos para crear el proyecto, las variables y la verificación están en [RAILWAY_DEPLOYMENT.md](RAILWAY_DEPLOYMENT.md).

| Servicio | Dockerfile | Start Command | Cron (UTC) | Grupo de dependencias |
|----------|-----------|---------------|------------|-----------------------|
| `api` | `Dockerfile.api` | `/app/entrypoint.sh` (migraciones y Uvicorn) | no aplica, siempre activo | `api` (FastAPI, Uvicorn, Jinja2) |
| `fetch-price` | `Dockerfile.fetch` | `python -m fetch_price.main` | `5 0 * * *` | `fetch` (httpx, urllib3, yarl) |
| `daily` | `Dockerfile.ml` | `python -m workers.daily` | `10 0 * * *` | `ml` (scikit-learn, numpy) |
| `monthly-backtest` | `Dockerfile.backtest` | `python -m workers.backtest.main` | `0 0 1 * *` | `ml` |

Cada servicio tiene su propio Dockerfile; todos instalan el paquete `shared/` con `poetry install --with <grupo> --without dev --no-root`. Los cron jobs usan política de reinicio `never`.

## Los comandos y horarios viven en Railway, no en `railway.*.toml`

`railway.api.toml`, `railway.fetch.toml` y `railway.daily.toml` (en la raíz) **no están conectados** a los servicios: cada servicio guarda su `Build` y `Deploy` en el dashboard (o vía CLI/MCP), independiente de esos archivos. No existe un `.toml` para `monthly-backtest`.

El 2026-08-09 se corrigió el `startCommand` en `railway.daily.toml` y se hizo push a `main`, pero el servicio `daily` siguió con el comando viejo y roto hasta que se actualizó en Railway. Si cambias un `startCommand`, `buildCommand`, `dockerfilePath` o `cronSchedule`, aplícalo también en el servicio. Verifica con:

```bash
railway environment config --json | grep -A3 '"daily"'
```

`workers/daily/` solo tiene `__main__.py` y usa imports absolutos, así que el Start Command de `daily` es `python -m workers.daily`; `python -m daily.main` no existe.

## Construir y probar en local

```bash
docker build -f Dockerfile.api -t btc-predictor-api:latest .      # igual con .fetch, .ml y .backtest
docker compose exec api python -m workers.daily                   # los jobs se prueban contra docker compose
docker compose exec api python -m workers.fetch_price.main
```

Las imágenes de producción no traen base de datos: para probarlas solas necesitan `--env-file` con un Postgres accesible (variables en `docker-compose.yml`).

## Historial

- 2026-08-09: de un Dockerfile con targets a un Dockerfile por servicio (`4c74069`); se corrigió el Start Command de `daily` (`c2e986c`).
