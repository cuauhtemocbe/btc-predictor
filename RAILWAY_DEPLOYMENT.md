# Railway Deployment Guide

Complete guide to deploy BTC Predictor to Railway.

For the per-service Dockerfiles, start commands and dependency groups see
[`RAILWAY_MULTISTAGE_CONFIG.md`](RAILWAY_MULTISTAGE_CONFIG.md). Start commands and
cron schedules live in the Railway dashboard, not in the `railway.*.toml` files.

## 🏗️ Architecture on Railway

The project has **6 services**:

| Service | Type | Schedule (UTC) | What it does |
|---------|------|----------------|--------------|
| **postgres** | Plugin | — | PostgreSQL database |
| **api** | Web, always on | — | FastAPI + dashboard |
| **fetch-price** | Cron | `5 0 * * *` (daily 00:05 UTC) | Ingests the closed daily Binance bar of each symbol |
| **daily** | Cron | `10 0 * * *` (daily 00:10 UTC) | evaluator → trainer → predictor (1-day horizon) |
| **monthly-backtest** | Cron | `0 0 1 * *` (1st of the month, 00:00) | Walk-forward backtest with the production configuration |

---

## 📋 Step-by-Step Deployment

### Step 1: Create Railway Project

1. Go to [railway.app](https://railway.app)
2. Sign in with GitHub
3. Click **"New Project"**
4. Select **"Deploy from GitHub repo"**
5. Choose: `cuauhtemocbe/btc-predictor`
6. Select branch: `main`

### Step 2: Add PostgreSQL Database

1. In your Railway project, click **"New"**
2. Select **"Database"**
3. Choose **"PostgreSQL"**
4. Railway automatically:
   - Creates the database
   - Injects `DATABASE_URL` environment variable
   - All services will have access to this variable

✅ **Done!** Your database is ready.

### Step 3: Configure API Service

1. Click **"New"** → **"GitHub Repo"** → Select `btc-predictor`
2. Go to service **Settings**:
   - **Name:** `api`
   - **Root Directory:** `/` (leave empty)
   - **Dockerfile Path:** `Dockerfile.api`
3. Go to **Variables** tab and verify:
   - `DATABASE_URL` — Auto-injected ✅
   - `PORT` — Auto-injected ✅
   - `TZ` — Add manually: `America/Mexico_City`
4. Go to **Settings** → **Networking**:
   - Enable **"Generate Domain"** (to get a public URL)

The container starts through `entrypoint.sh` (migrations, then Uvicorn).

### Step 4: Load the Price History (once)

The cron jobs refuse to run for a symbol that has no stored bars, so load the history first:

```bash
railway run -s api python scripts/load_binance_history.py --check   # host reachable from Railway? (no DB writes)
railway run -s api python scripts/load_binance_history.py           # BTCUSDT from 2017-08, PAXGUSDT from 2020-08
```

The loader verifies the SHA256 checksum of every monthly zip, is idempotent, and reports missing days at the end.

### Step 5: Configure Fetch-Price Cron Job

1. Click **"New"** → **"Empty Service"**
2. **Settings**:
   - **Name:** `fetch-price`
   - Connect to your GitHub repo
   - **Dockerfile Path:** `Dockerfile.fetch`
3. **Variables**:
   - `DATABASE_URL` — Auto-inherited from postgres ✅
   - `TZ` — `America/Mexico_City`
4. **Settings** → **Deploy**:
   - **Start Command:** `python -m fetch_price.main`
   - **Restart Policy:** Never
5. **Settings** → **Cron Schedule**:
   - **Schedule:** `5 0 * * *` (daily at 00:05 UTC)
   - **Region:** Use same as your database

✅ **Ready to deploy!** This service will:
- Ingest the closed daily bar (UTC) of each supported symbol (`BTCUSDT`, `PAXGUSDT`) from Binance, with volume
- Read the `daily/` file of data.binance.vision, falling back to the REST klines endpoint (`data-api.binance.vision`) if the file is not published yet
- Backfill days missed by earlier runs, never store the still-open day
- Be idempotent (existing `(symbol, timestamp)` rows are skipped) and exit non-zero if both sources fail

**Note:** the `daily/` file is published ~01:40 UTC, so the 00:05 UTC cron does not find it yet and uses the REST fallback (it logs a warning on each run). Binance's main REST API (`api.binance.com`) is geo-blocked from Railway (HTTP 451), which is why only `data.binance.vision` and `data-api.binance.vision` are used.

### Step 6: Configure Daily Cron Job

1. Click **"New"** → **"Empty Service"**
2. **Settings**:
   - **Name:** `daily`
   - Connect to your GitHub repo
   - **Dockerfile Path:** `Dockerfile.ml`
3. **Variables**:
   - `DATABASE_URL` — Auto-inherited ✅
   - `TZ` — `America/Mexico_City`
   - `TRAINING_WINDOW_DAYS` — (optional) default `21`
4. **Settings** → **Deploy**:
   - **Start Command:** `python -m workers.daily`
   - **Restart Policy:** Never
5. **Settings** → **Cron Schedule**:
   - **Schedule:** `10 0 * * *` (daily at 00:10 UTC, after `fetch-price`; the predictor exits 1 if the last bar closed more than 2 hours ago, #175)
   - **Region:** Use same as your database

✅ **Ready to deploy!** This service runs, in order, stopping at the first failure:
- **Evaluator**: settles every pending 1-day prediction whose settling bar is stored (a missing bar leaves it pending)
- **Trainer**: trains the Linear model on every stored `BTCUSDT` daily row (log-return features, window `TRAINING_WINDOW_DAYS`) and fails with the required and available row counts if there is too little history
- **Predictor**: predicts the next day with the active model

### Step 7: Configure the Monthly Cron Job

Same image and variables as `daily`, different start command and schedule:

| Service | Dockerfile | Start Command | Cron Schedule |
|---------|-----------|---------------|---------------|
| `monthly-backtest` | `Dockerfile.backtest` | `python -m workers.backtest.main` | `0 0 1 * *` |

`monthly-backtest` runs the walk-forward backtest with the production window, the last 365 days and the last 100 days as the out-of-sample test slice, and stores the rows in `backtest_results`. It exits 1 when there is too little history instead of shrinking the window. See [`docs/BACKTESTING.md`](docs/BACKTESTING.md).

---

## 🔐 Environment Variables

All services automatically inherit these from Railway:

| Variable | Source | Description |
|----------|--------|-------------|
| `DATABASE_URL` | PostgreSQL plugin | Connection string (auto-injected) |
| `PORT` | Railway | Service port (api only) |
| `TZ` | Manual | Timezone for logs |
| `TRAINING_WINDOW_DAYS` | Manual (optional) | Sliding-window size in days used by the trainers and the backtest (default `21`) |

**No `.env` file needed** — Railway injects everything. No data-source API key is needed either: the Binance public data is free.

---

## 🚀 Deployment Workflow

### After Each Git Push to `main`:

1. Railway detects changes
2. Builds a new Docker image per service
3. Deploys to production
4. Run `./scripts/hooks/monitor-railway.sh` to check that every service is online

### Manual Deploy:

```bash
# Via CLI
railway up

# Or via dashboard
# Go to service → Deployments → "Deploy"
```

---

## ✅ Verify Deployment

### Check API Service:

```bash
# Get your Railway URL
railway domain

# Test health endpoint
curl https://btc-predictor-production.up.railway.app/health
```

Expected response:
```json
{
  "status": "ok",
  "database": "connected"
}
```

### Check Logs:

```bash
railway logs --service api
railway logs --service fetch-price
railway logs --service daily
railway logs --service monthly-backtest
```

### Check the data:

```bash
railway run --service api python -c "
from sqlalchemy import text
from shared.db.database import SessionLocal
with SessionLocal() as db:
    rows = db.execute(text('SELECT symbol, COUNT(*), MAX(timestamp) FROM prices GROUP BY symbol'))
    for symbol, count, last in rows:
        print(symbol, count, last)
"
```

Expected: one row per symbol, with `MAX(timestamp)` equal to yesterday 00:00 UTC after the 00:05 UTC `fetch-price` run.

---

## 🐛 Troubleshooting

### Issue: `DATABASE_URL` not found

**Solution:** Make sure the PostgreSQL plugin is added and linked to your services.

1. Go to postgres service
2. Click **"Variables"** tab
3. Copy `DATABASE_URL`
4. Go to each service → **"Variables"** → Add `DATABASE_URL` manually if not auto-injected

### Issue: Cron jobs not running

**Solution:**
1. Verify the cron schedule syntax in the service settings (see the table above)
2. Check service logs for errors
3. Check the **Start Command** in the dashboard: it must match the table above (the `railway.*.toml` files are not connected to the services)
4. Ensure `python -m workers.daily` can run locally first (`docker compose exec api python -m workers.daily`)

### Issue: `fetch-price` fails or stores nothing

**Solution:**
1. Check that the host is reachable from Railway: `railway run -s api python scripts/load_binance_history.py --check`
2. The job refuses to run for a symbol with no stored bars: load the history first (Step 4)
3. Check that `https://data.binance.vision` and `https://data-api.binance.vision/api/v3/ping` answer from your network

### Issue: Predictions stay pending (`actual_price` is NULL)

**Solution:** The evaluator settles a prediction only when the bar that closes it is stored. Check that `fetch-price` ran successfully before `daily` and that `prices` has yesterday's bar (see "Check the data").

### Issue: `daily` fails with "Insufficient training data"

**Solution:** The trainer needs `(window + 1) * 5` daily rows (`required_training_days()`). Load more history with `scripts/load_binance_history.py` or lower `TRAINING_WINDOW_DAYS`.

---

## 📚 Resources

- [Railway Docs](https://docs.railway.app/)
- [Railway CLI](https://docs.railway.app/develop/cli)
- [Cron Schedule Syntax](https://crontab.guru/)
- [Binance public data](https://data.binance.vision)
- Project Repository: https://github.com/cuauhtemocbe/btc-predictor
