# US-022 Railway Deployment Guide

## Overview

This guide explains how to deploy the weekly predictor service to Railway for US-022 (Weekly BTC Price Predictions).

## Prerequisites

- Railway CLI installed and authenticated (`railway login`)
- GitHub repository pushed with latest code
- Existing Railway services: `Postgres`, `btc-predictor` (API), `daily`, `fetch-price`

## Deployment Steps

### 1. Verify Migration Applied

The migration for the `timeframe` column should apply automatically when the `btc-predictor` service deploys.

Verify by checking logs:
```bash
railway logs --service btc-predictor | grep "alembic"
```

You should see:
```
INFO  [alembic.runtime.migration] Running upgrade 05299070b357 -> fda7ff646d39, add timeframe column to predictions
```

### 2. Create Weekly Predictor Service

**Option A: Via Railway Dashboard (Recommended)**

1. Go to your Railway project: https://railway.app/project/[your-project-id]
2. Click **"+ New"** → **"Empty Service"**
3. Name it: `weekly-predictor`
4. Click on the service → **Settings** tab
5. Under **Source**, select your GitHub repo: `cuauhtemocbe/btc-predictor`
6. Set **Root Directory**: leave empty (monorepo root)
7. Set **Start Command**:
   ```bash
   python -m workers.weekly
   ```

8. Under **Cron Schedule**, set:
   ```
   0 7 * * 1
   ```
   (Every Monday at 7am UTC)

9. Under **Variables**, add all environment variables (copy from `btc-predictor` service):
   - `DATABASE_URL` (link to Postgres service)
   - Any other shared environment variables

10. Click **Deploy**

**Option B: Via Railway CLI**

```bash
# Create new service
railway service create weekly-predictor

# Link to your project
railway link

# Set environment variables (copy from other services)
railway variables --service weekly-predictor set DATABASE_URL=$DATABASE_URL

# Set start command
railway up --service weekly-predictor --start-command "python -m workers.weekly"

# Set cron schedule (must be done via dashboard for now)
```

**Important**: Railway cron schedules can only be configured via the dashboard currently.

### 3. Configure Service

Set the following in the **weekly-predictor** service settings:

- **Instance Type**: Shared (cron jobs don't need dedicated resources)
- **Restart Policy**: Never (cron jobs should not restart)
- **Health Check**: Disabled (not needed for cron)

### 4. Verify Deployment

1. Wait for the service to build and deploy
2. Check logs:
   ```bash
   railway logs --service weekly-predictor
   ```

3. Manually trigger the job to test (in Railway dashboard):
   - Go to service → Deployments → Latest → **Restart**
   - Check logs for success

Expected output:
```
Starting weekly job orchestration
Step 1: Running weekly evaluator
Weekly evaluator job completed successfully
Step 2: Running weekly predictor
Model predicted price (7 days ahead): $67500.00
Saved weekly prediction #X: for=2026-05-26, timeframe=1w
Weekly predictor job completed successfully
Weekly job completed successfully
```

### 5. Verify Database

Connect to production database and verify:

```sql
-- Check timeframe column exists
\d predictions

-- Check weekly predictions are being created
SELECT * FROM predictions WHERE timeframe = '1w' ORDER BY predicted_at DESC LIMIT 5;
```

### 6. Verify API

Test the API endpoints:

```bash
# Get weekly predictions
curl https://btc-predictor-production-096e.up.railway.app/api/predictions/history?timeframe=1w

# Get daily predictions (should still work)
curl https://btc-predictor-production-096e.up.railway.app/api/predictions/history?timeframe=1d

# Get all predictions (no filter)
curl https://btc-predictor-production-096e.up.railway.app/api/predictions/history
```

## Cron Schedule Breakdown

```
0 7 * * 1
│ │ │ │ └─ Day of week (1 = Monday)
│ │ │ └─── Month (any)
│ │ └───── Day of month (any)
│ └─────── Hour (7 = 7am UTC)
└───────── Minute (0)
```

**Runs**: Every Monday at 7:00 AM UTC

## Monitoring

### Check Logs

```bash
# View real-time logs
railway logs --service weekly-predictor

# View logs from all services
railway logs
```

### Check Cron Execution

1. Go to Railway dashboard → **weekly-predictor** service
2. Click **Deployments** tab
3. See execution history and logs for each cron run

### Database Monitoring

```sql
-- Count weekly predictions
SELECT COUNT(*) FROM predictions WHERE timeframe = '1w';

-- Check latest weekly prediction
SELECT 
    predicted_for, 
    predicted_at, 
    timeframe,
    predicted_price,
    actual_price,
    direction_correct
FROM predictions 
WHERE timeframe = '1w' 
ORDER BY predicted_at DESC 
LIMIT 1;

-- Compare daily vs weekly accuracy
SELECT 
    timeframe,
    COUNT(*) as total,
    AVG(error_pct) as avg_error,
    SUM(CASE WHEN direction_correct THEN 1 ELSE 0 END)::float / COUNT(*) as accuracy
FROM predictions
WHERE actual_price IS NOT NULL
GROUP BY timeframe;
```

## Troubleshooting

### Issue: Weekly predictor not running

**Check**:
1. Cron schedule is correct: `0 7 * * 1`
2. Service has `DATABASE_URL` variable set
3. Service has correct start command: `python -m workers.weekly`

**Solution**: Check Railway logs for errors

### Issue: Migration not applied

**Check**:
```bash
railway logs --service btc-predictor | grep "fda7ff646d39"
```

**Solution**: Manually trigger redeploy of `btc-predictor` service

### Issue: Insufficient data error

**Check**: 
```sql
SELECT COUNT(*) FROM btc_prices;
```

**Solution**: Need at least 30 days of price data. Run backfill script or wait for `fetch-price` cron to accumulate data.

## Rollback

If something goes wrong:

1. **Pause weekly service**: Railway dashboard → weekly-predictor → Settings → Pause
2. **Rollback API**: Railway dashboard → btc-predictor → Deployments → Revert to previous
3. **Rollback migration** (if needed):
   ```bash
   # Connect to production
   railway run sh -c "cd shared && alembic downgrade -1"
   ```

## Next Steps

After successful deployment:

1. ✅ Wait for Monday 7am UTC to see first automated weekly prediction
2. ✅ Monitor logs and database for the next 2 weeks
3. ✅ Implement dashboard UI tabs (deferred from US-022 implementation)
4. ✅ Add comprehensive tests for weekly workers
5. ✅ Consider adding hourly predictions (1h timeframe) in future iteration

## Related

- Spec: `specs/us-022-weekly-predictions.md`
- Plan: `specs/us-022-weekly-predictions-plan.md`
- GitHub Issue: #24
- Migration: `shared/alembic/versions/fda7ff646d39_add_timeframe_column_to_predictions.py`
