# Deploy Daily Cron Job to Railway

Quick guide to deploy the daily evaluator+predictor cron job to Railway.

## 🚀 Step-by-Step Deployment

### Step 1: Create Service via Railway Dashboard

1. Go to https://railway.app
2. Open your **btc-predictor** project
3. Switch to **production** environment
4. Click **"+ New"** → **"Empty Service"**

### Step 2: Link to GitHub Repo

1. Click on the new service
2. Go to **Settings** → **Source**
3. Click **"Connect Repo"**
4. Select: `cuauhtemocbe/btc-predictor`
5. Branch: `main`
6. **Root Directory**: Leave empty (uses `/`)

### Step 3: Configure Service

**Settings → General:**
- **Service Name**: `daily`
- **Build Method**: Dockerfile

**Settings → Deploy:**
- **Start Command**: `python -m workers.daily`
- **Dockerfile Path**: `Dockerfile`

### Step 4: Set Environment Variables

Go to **Variables** tab and add:

| Variable | Value | Source |
|----------|-------|--------|
| `DATABASE_URL` | (auto-inherited from Postgres) | Auto |
| `TZ` | `America/Mexico_City` | Manual |

### Step 5: Configure Cron Schedule

**Settings → Cron:**
- **Enable Cron**: ✅ Yes
- **Schedule**: `0 13 * * *`
  - This runs at **13:00 UTC** = **7:00 AM Mexico City time**
- **Region**: US East (same as your database)

### Step 6: Deploy

1. Click **"Deploy"** button
2. Wait for build to complete (~2-3 minutes)
3. Check logs to verify success

## ✅ Verify Deployment

### Check Logs

```bash
# Via CLI
railway logs --service daily

# Or via dashboard
# Go to service → Deployments → View Logs
```

### Expected Log Output

```
Starting daily job orchestration
Step 1: Running evaluator
Starting daily evaluator job
Evaluating prediction for date: 2026-05-17
No unevaluated predictions for 2026-05-17
No predictions to evaluate, exiting successfully
Step 2: Running predictor
Starting daily predictor job
...
Daily job completed successfully
```

### Verify Cron Schedule

```bash
railway service status
```

Should show:
```
Cron jobs
  - daily: ● Online · 0/1 running · 0 13 * * * · next run in X hours
```

## 🔧 Troubleshooting

### Build Fails

- Check **Build Logs** in Railway dashboard
- Verify `Dockerfile` is correct
- Ensure all dependencies in `pyproject.toml`

### Deployment Fails

- Check **Deploy Logs** for Python errors
- Verify `DATABASE_URL` is set
- Check database connection

### Cron Not Running

- Verify cron schedule syntax: `0 13 * * *`
- Check service status: should show "Online"
- Verify timezone matches (`TZ=America/Mexico_City`)

### No Predictions to Evaluate

This is normal if:
- No prediction was made yesterday (first run)
- Prediction already evaluated today (idempotent)
- Model hasn't been trained yet (US-007 trainer needed)

## 📅 Cron Schedule Reference

| Time (Mexico City) | UTC | Cron Expression |
|-------------------|-----|-----------------|
| 7:00 AM | 1:00 PM | `0 13 * * *` |
| 6:00 AM | 12:00 PM | `0 12 * * *` |
| 8:00 AM | 2:00 PM | `0 14 * * *` |

**Note**: Mexico City is UTC-6, so add 6 hours to local time for UTC cron schedule.

## 🎯 What This Service Does

The daily cron job runs two tasks in sequence:

### 1. Evaluator (US-010)
- Finds predictions for today with `actual_price=NULL`
- Fetches today's 7am BTC close price
- Calculates error metrics:
  - `error_abs`: |actual - predicted|
  - `error_pct`: (error_abs / actual) × 100
  - `direction_correct`: Did predicted direction match actual?
  - `pnl_simulated`: Profit/loss from prediction strategy
- Updates prediction record

### 2. Predictor (US-009)
- Loads active ML model from database
- Fetches recent historical prices
- Predicts tomorrow's BTC price
- Saves prediction to database (evaluation fields = NULL)

## 🔄 Full Workflow Example

**Day 1 (Today):**
- 7:00 AM: Daily cron runs
  - Evaluator: "No predictions to evaluate" (first run)
  - Predictor: Predicts Day 2 price ($67,000)
  - Database: prediction for Day 2 created

**Day 2:**
- 7:00 AM: Daily cron runs
  - Evaluator: Evaluates Day 2 prediction (actual=$67,500)
    - Updates: error_abs=500, error_pct=0.74, direction_correct=True
  - Predictor: Predicts Day 3 price ($67,800)
  - Database: Day 2 evaluated, Day 3 prediction created

**Day 3, 4, 5... (continues):**
- Each day: evaluate yesterday → predict tomorrow

## 📊 Monitor in Production

### Database Queries

```sql
-- View recent predictions
SELECT 
    id, predicted_for, predicted_price, actual_price,
    error_abs, error_pct, direction_correct, pnl_simulated
FROM predictions
ORDER BY predicted_for DESC
LIMIT 10;

-- Check evaluation coverage
SELECT 
    COUNT(*) FILTER (WHERE actual_price IS NULL) as unevaluated,
    COUNT(*) FILTER (WHERE actual_price IS NOT NULL) as evaluated
FROM predictions;
```

### Health Checks

1. **Service Status**: Should be "Online" in Railway dashboard
2. **Recent Deployments**: Check for successful deploys
3. **Logs**: No error messages in daily logs
4. **Database**: New predictions created daily, old ones evaluated

---

**Deployed Date**: 2026-05-17  
**US Completed**: US-010 (Daily Evaluator)  
**Status**: ✅ Ready for production
