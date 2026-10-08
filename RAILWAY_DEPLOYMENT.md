# Railway Deployment Guide

How to deploy BTC Predictor to Railway and check it. Each service's Dockerfile, start command and cron schedule are in [RAILWAY_MULTISTAGE_CONFIG.md](RAILWAY_MULTISTAGE_CONFIG.md); they live in the Railway dashboard, not in the `railway.*.toml` files.

## Services

`postgres` (plugin), `api` (web, always on), and three crons: `fetch-price` (`5 0 * * *`), `daily` (`10 0 * * *`) and `monthly-backtest` (`0 0 1 * *`). What each one does: [README](README.md#-arquitectura).

## Deploy step by step

1. **Project.** In [railway.app](https://railway.app) create a project from the GitHub repo `cuauhtemocbe/btc-predictor`, branch `main`.
2. **Database.** Add a PostgreSQL plugin. Railway injects `DATABASE_URL` into the services.
3. **`api`.** New service from the repo, name `api`, root directory `/`, Dockerfile `Dockerfile.api`. Check `DATABASE_URL` and `PORT` are injected, add `TZ=America/Mexico_City`, and generate a public domain under Networking.
4. **Load the history (once).** The crons refuse to run for a symbol with no stored bars:
   ```bash
   railway run -s api python scripts/load_binance_history.py --check   # host reachable from Railway? no DB writes
   railway run -s api python scripts/load_binance_history.py           # BTCUSDT from 2017-08, PAXGUSDT from 2020-08
   ```
5. **`fetch-price`, `daily`, `monthly-backtest`.** For each, create an Empty Service connected to the repo and set the Dockerfile, Start Command, restart policy `Never` and cron schedule from the table in [RAILWAY_MULTISTAGE_CONFIG.md](RAILWAY_MULTISTAGE_CONFIG.md), plus `DATABASE_URL` and `TZ`. `daily` and `monthly-backtest` also take the optional `TRAINING_WINDOW_DAYS` (default 21).

What the crons do:

- **`fetch-price`** ingests the closed daily bar (UTC) of `BTCUSDT` and `PAXGUSDT`, backfills days missed earlier, never stores the open day, skips existing `(symbol, timestamp)` rows and exits non-zero if both sources fail. It reads the `daily/` file of data.binance.vision, which is published around 01:40 UTC, so the 00:05 UTC run uses the REST fallback `data-api.binance.vision` and logs a warning each time. The main REST API (`api.binance.com`) answers HTTP 451 from Railway.
- **`daily`** runs evaluator, trainer and predictor, stopping at the first failure. The predictor exits 1 if the last bar closed more than 2 hours ago (#175), which is why it runs after `fetch-price`. The trainer fails with the required and available row counts if there is too little history.
- **`monthly-backtest`** runs the walk-forward backtest with the production window, the last 365 days and the last 100 as test slice. It exits 1 on too little history instead of shrinking the window ([docs/BACKTESTING.md](docs/BACKTESTING.md)).

## Environment variables

| Variable | Source | Description |
|----------|--------|-------------|
| `DATABASE_URL` | PostgreSQL plugin | Connection string |
| `PORT` | Railway | Port of `api` |
| `TZ` | Manual | Time zone of the logs |
| `TRAINING_WINDOW_DAYS` | Manual, optional | Window in days for the trainer and the backtest, default 21 |

Railway injects everything; no dotenv file and no data-source API key are needed.

## After each push to `main`

Railway builds one image per service and deploys. Check that every service is online with `./scripts/hooks/monitor-railway.sh`. Manual deploy: `railway up`, or Deployments > Deploy in the dashboard.

## Verify

```bash
railway domain
curl https://btc-predictor-production-096e.up.railway.app/health      # {"status": "ok", "database": "reachable"}
railway logs --service <api|fetch-price|daily|monthly-backtest>
railway run --service api python -c "
from sqlalchemy import text
from shared.db.database import SessionLocal
with SessionLocal() as db:
    for row in db.execute(text('SELECT symbol, COUNT(*), MAX(timestamp) FROM prices GROUP BY symbol')):
        print(*row)
"
```

Expected: one row per symbol, with `MAX(timestamp)` equal to yesterday 00:00 UTC after the `fetch-price` run.

## Troubleshooting

- **`DATABASE_URL` not found**: link the PostgreSQL plugin to the service, or copy the variable from the postgres service.
- **A cron does not run**: check the schedule and the Start Command in the dashboard (the `.toml` files are not connected, see RAILWAY_MULTISTAGE_CONFIG.md), read the logs, and make sure the command runs locally (`docker compose exec api python -m workers.daily`).
- **`fetch-price` fails or stores nothing**: run the `--check` command from step 4; the job refuses a symbol with no stored bars, so load the history first.
- **Predictions stay pending (`actual_price` is NULL)**: the evaluator settles a prediction only when the bar that closes it is stored. Check that `fetch-price` succeeded before `daily` and that `prices` has yesterday's bar.
- **`daily` fails with "Insufficient training data"**: the trainer needs `(window + 1) * 5` daily rows (`required_training_days()`). Load more history or lower `TRAINING_WINDOW_DAYS`.

Resources: [Railway docs](https://docs.railway.app/), [Railway CLI](https://docs.railway.app/develop/cli), [Binance public data](https://data.binance.vision).
