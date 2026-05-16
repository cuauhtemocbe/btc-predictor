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
4. **Settings** → **Deploy**:
   - **Start Command:** `python -m jobs.fetch_price.main`
5. **Settings** → **Cron Schedule**:
   - **Schedule:** `0 * * * *` (every hour)
   - **Region:** Use same as your database

⚠️ **Note:** This service won't work until you implement US-003 (Binance client) and US-004 (fetch_price job).

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
   - **Start Command:** `python -m jobs.daily.main`
5. **Settings** → **Cron Schedule**:
   - **Schedule:** `0 13 * * *` (7am Mexico City = 1pm UTC)
   - **Region:** Use same as your database

⚠️ **Note:** This service won't work until you implement US-006 to US-010 (ML models, predictions, evaluation).

---

## 🔐 Environment Variables

All services automatically inherit these from Railway:

| Variable | Source | Description |
|----------|--------|-------------|
| `DATABASE_URL` | PostgreSQL plugin | Connection string (auto-injected) |
| `PORT` | Railway | Service port (api only) |
| `TZ` | Manual | Timezone for cron jobs |

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
3. Ensure `python -m jobs.fetch_price.main` can run locally first

---

## 📊 Current Status

After deploying with shared package (US-001):

| Service | Status | Ready to Deploy? |
|---------|--------|------------------|
| **postgres** | ✅ Ready | Yes |
| **api** | ✅ Ready | Yes (hello world) |
| **fetch-price** | ⏳ Waiting | No (needs US-003, US-004) |
| **daily** | ⏳ Waiting | No (needs US-006 to US-010) |

---

## 🎯 Next Steps

1. ✅ Deploy **postgres** + **api** now (they work)
2. ⏳ Implement **US-002** (database models + migrations)
3. ⏳ Implement **US-003, US-004** (Binance client + fetch_price job)
4. ⏳ Deploy **fetch-price** cron after US-004
5. ⏳ Implement **US-006 to US-010** (ML models, predictions)
6. ⏳ Deploy **daily** cron after US-010

---

## 📚 Resources

- [Railway Docs](https://docs.railway.app/)
- [Railway CLI](https://docs.railway.app/develop/cli)
- [Cron Schedule Syntax](https://crontab.guru/)
- Project Repository: https://github.com/cuauhtemocbe/btc-predictor
