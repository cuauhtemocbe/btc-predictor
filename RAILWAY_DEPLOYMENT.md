# Railway Deployment Guide

Complete guide to deploy BTC Predictor to Railway.

## 🏗️ Architecture on Railway

Your project will have **4 services**:

1. **postgres** — PostgreSQL database (plugin)
2. **api** — Web service (always running)
3. **fetch-price** — Cron job (runs hourly)
4. **daily** — Cron job (runs daily at 7am Mexico City time)

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

---

### Step 3: Configure API Service

The API service should already be deployed (Railway auto-detects it). If not:

1. Click **"New"** → **"GitHub Repo"** → Select `btc-predictor`
2. Go to service **Settings**:
   - **Name:** `api`
   - **Root Directory:** `/` (leave empty)
   - **Dockerfile Path:** `Dockerfile`
3. Go to **Variables** tab and verify:
   - `DATABASE_URL` — Auto-injected ���
   - `PORT` — Auto-injected ✅
   - `TZ` — Add manually: `America/Mexico_City`
4. Go to **Settings** → **Networking**:
   - Enable **"Generate Domain"** (to get a public URL)

**Deploy Command:**
```bash
uvicorn src.app.main:app --host 0.0.0.0 --port $PORT
```

Railway will automatically use this from the Dockerfile.

---

### Step 4: Configure Fetch-Price Cron Job

1. Click **"New"** → **"Empty Service"**
2. **Settings**:
   - **Name:** `fetch-price`
   - Connect to your GitHub repo
   - **Dockerfile Path:** `Dockerfile`
3. **Variables**:
   - `DATABASE_URL` — Auto-inherited from postgres ✅
   - `TZ` — `America/Mexico_City`
   - `BINANCE_BASE_URL` — (Optional) Default: `https://api.binance.com`
4. **Settings** → **Deploy**:
   - **Start Command:** `python -m workers.fetch_price.main`
5. **Settings** → **Cron Schedule**:
   - **Schedule:** `0 * * * *` (every hour)
   - **Region:** Use same as your database

✅ **Ready to deploy!** US-003 (Binance client) and US-004 (fetch_price job) are complete. This service will:
- Fetch hourly BTC/USDT prices from Binance API
- Store OHLCV data in `btc_prices` table
- Handle idempotency (skips duplicate timestamps)
- Implement rate limiting and error handling

---

### Step 5: Configure Daily Cron Job

1. Click **"New"** → **"Empty Service"**
2. **Settings**:
   - **Name:** `daily`
   - Connect to your GitHub repo
   - **Dockerfile Path:** `Dockerfile`
3. **Variables**:
   - `DATABASE_URL` — Auto-inherited ✅
   - `TZ` — `America/Mexico_City`
4. **Settings** → **Deploy**:
   - **Start Command:** `python -m workers.daily`
5. **Settings** → **Cron Schedule**:
   - **Schedule:** `0 13 * * *` (7am Mexico City = 1pm UTC)
   - **Region:** Use same as your database

✅ **Ready to deploy!** US-006 to US-010 are complete. This service will:
- **Evaluator**: Evaluate yesterday's prediction (update with actual price, errors, PnL)
- **Predictor**: Generate tomorrow's prediction using active ML model
- Run daily orchestration: evaluator → predictor

---

## 🔐 Environment Variables

All services automatically inherit these from Railway:

| Variable | Source | Description |
|----------|--------|-------------|
| `DATABASE_URL` | PostgreSQL plugin | Connection string (auto-injected) |
| `PORT` | Railway | Service port (api only) |
| `TZ` | Manual | Timezone for cron jobs |
| `BINANCE_BASE_URL` | Manual (optional) | Binance API endpoint (default: `https://api.binance.com`) |

**No `.env` file needed** — Railway injects everything!

---

## 🚀 Deployment Workflow

### After Each Git Push to `main`:

1. Railway detects changes
2. Builds new Docker image
3. Runs tests (if configured)
4. Deploys to production
5. Zero-downtime restart

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
# Via CLI
railway logs --service api

# Or via dashboard
# Go to service → View Logs
```

---

## 🐛 Troubleshooting

### Issue: `DATABASE_URL` not found

**Solution:** Make sure PostgreSQL plugin is added and linked to your services.

1. Go to postgres service
2. Click **"Variables"** tab
3. Copy `DATABASE_URL`
4. Go to each service → **"Variables"** → Add `DATABASE_URL` manually if not auto-injected

### Issue: Shared package import fails

**Solution:** Make sure Dockerfile includes shared package:

```dockerfile
COPY shared/btc_shared/ ./shared/btc_shared/
```

### Issue: Cron jobs not running

**Solution:**
1. Verify cron schedule syntax: `0 * * * *` (cron format)
2. Check service logs for errors
3. Ensure `python -m workers.fetch_price.main` can run locally first

### Issue: Binance API errors

**Solution:**
1. Check if Binance API is accessible: `curl https://api.binance.com/api/v3/ping`
2. Verify `BINANCE_BASE_URL` environment variable is correct
3. Check logs for rate limiting errors (429 status code)
4. Binance public API has rate limits: 1200 requests/minute, 20 orders/second

---

## 🎯 Fetch-Price Service Details

### What it does:
- Runs every hour (`0 * * * *`)
- Fetches latest BTC/USDT price from Binance API
- Stores OHLCV data (Open, High, Low, Close, Volume) in `btc_prices` table
- Implements idempotency: skips if data for that hour already exists

### API endpoint used:
```bash
GET https://api.binance.com/api/v3/klines
  ?symbol=BTCUSDT
  &interval=1h
  &limit=1
```

### Expected behavior:
- **First run:** Inserts 1 row into `btc_prices`
- **Subsequent runs (same hour):** Skips insertion (UNIQUE constraint on timestamp)
- **Next hour:** Inserts new row

### How to verify it's working:

```bash
# Check logs
railway logs --service fetch-price

# Expected output (success):
INFO: Fetched price for 2026-05-16 15:00:00: $67234.56
INFO: Successfully saved price to database

# Expected output (duplicate):
INFO: Fetched price for 2026-05-16 15:00:00: $67234.56
INFO: Price already exists, skipping (idempotent)
```

### Query the database:

```bash
# Via Railway CLI
railway run --service api python -c "
from shared.db.database import get_engine
from sqlalchemy import text
engine = get_engine()
with engine.connect() as conn:
    result = conn.execute(text('SELECT COUNT(*) FROM btc_prices'))
    print(f'Total prices: {result.scalar()}')
"
```

---

## 📊 Current Status

After implementing US-001 to US-004:

| Service | Status | Ready to Deploy? |
|---------|--------|------------------|
| **postgres** | ✅ Ready | Yes |
| **api** | ✅ Ready | Yes (health endpoint, foundation for US-005) |
| **fetch-price** | ✅ Ready | Yes (US-003, US-004 complete) |
| **daily** | ⏳ Waiting | No (needs US-006 to US-010) |

---

## 🎯 Next Steps

1. ✅ Deploy **postgres** + **api** (working)
2. ✅ Implement **US-002** (database models + migrations)
3. ✅ Implement **US-003, US-004** (Binance client + fetch_price job)
4. 🚀 **Deploy fetch-price cron** (ready to deploy!)
5. ⏳ Implement **US-005** (API endpoint to query prices)
6. ⏳ Implement **US-006 to US-010** (ML models, predictions)
7. ⏳ Deploy **daily** cron after US-010

---

## 📚 Resources

- [Railway Docs](https://docs.railway.app/)
- [Railway CLI](https://docs.railway.app/develop/cli)
- [Cron Schedule Syntax](https://crontab.guru/)
- Project Repository: https://github.com/cuauhtemocbe/btc-predictor
