# US-025: Multi-Model Predictions - Railway Deployment Guide

This guide covers deploying the multi-model predictions feature to Railway.

## Prerequisites

- Railway CLI installed and authenticated (`railway login`)
- Railway project already exists for btc-predictor
- Current working directory: project root

## Changes Overview

US-025 introduces multi-model prediction support:

### Code Changes
- **predictor.py**: Now supports `--multi-model` flag to generate predictions from all active models
- **evaluator.py**: Evaluates predictions from all models (no code changes needed, already compatible)
- **models.py**: Updated UNIQUE constraint to allow multiple predictions per date (one per model)

### Database Changes
- Migration `c0a41e870a5e`: Updates UNIQUE constraint from `(predicted_for, timeframe)` to `(predicted_for, timeframe, model_id)`

## Deployment Steps

### 1. Run Database Migration

```bash
# Connect to Railway project
railway link

# Run migrations via Railway CLI
railway run --service api sh -c "cd shared && alembic upgrade head"
```

Expected output:
```
INFO  [alembic.runtime.migration] Running upgrade fda7ff646d39 -> c0a41e870a5e, add model_id to unique constraint for multi-model predictions
```

### 2. Deploy Updated Code

```bash
# Commit changes
git add .
git commit -m "feat(models): implement multi-model predictions system (US-025)"

# Push to main (triggers automatic Railway deployment)
git push origin main
```

### 3. Update Daily Cron Service

The `daily` cron service needs to be updated to use the `--multi-model` flag.

#### Option A: Update via Railway Dashboard

1. Go to Railway dashboard → `daily` service
2. Click "Variables" tab
3. Update `START_COMMAND` variable:
   ```
   python -m daily.main --multi-model
   ```
4. Redeploy the service

#### Option B: Update via Railway CLI

```bash
# Set environment variable for daily service
railway variables --service daily set START_COMMAND="python -m daily.main --multi-model"

# Trigger redeployment
railway up --service daily
```

### 4. Verify Deployment

#### Check Migration Status

```bash
railway run --service api sh -c "cd shared && alembic current"
```

Expected output: `c0a41e870a5e (head)`

#### Check Daily Service Logs

```bash
railway logs --service daily
```

Look for:
```
Starting daily predictor job in multi-model mode
Loaded 4 active model(s) in multi-model mode
Predictions for 2024-05-21:
  ✓ linear_v1:  $67,000 (model #1)
  ✓ lstm_v1:    $67,200 (model #2)
  ✓ xgboost_v1: $66,800 (model #3)
  ✓ arima_v1:   $67,100 (model #4)
Multi-model predictions saved successfully
```

#### Verify Database

```bash
railway run --service postgres psql -U btcpredictor -d btcpredictor -c "
SELECT m.name, COUNT(p.id) as predictions_count
FROM predictions p
JOIN models m ON p.model_id = m.id
WHERE p.predicted_for >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY m.name
ORDER BY m.name;
"
```

Expected output (after a few days of running):
```
     name      | predictions_count
---------------+-------------------
 arima_v1      |                 7
 linear_v1     |                 7
 lstm_v1       |                 7
 xgboost_v1    |                 7
```

## Rollback Plan

If issues arise, rollback with these steps:

### 1. Disable Multi-Model Mode

```bash
# Revert daily service to single-model mode
railway variables --service daily set START_COMMAND="python -m daily.main"

# Redeploy
railway up --service daily
```

### 2. Rollback Database Migration (if needed)

```bash
# Downgrade to previous migration
railway run --service api sh -c "cd shared && alembic downgrade -1"
```

**Warning**: This will remove the new UNIQUE constraint. If you have predictions from multiple models for the same date, the downgrade will fail. You'll need to manually clean up data first.

### 3. Rollback Code

```bash
# Revert to previous commit
git revert HEAD
git push origin main
```

## Testing in Production

### 1. Verify Multi-Model Predictions

After the next daily cron run:

```bash
# Check that predictions from all models were created
railway run --service postgres psql -U btcpredictor -d btcpredictor -c "
SELECT m.name, p.predicted_price, p.predicted_for
FROM predictions p
JOIN models m ON p.model_id = m.id
WHERE p.predicted_for = (SELECT MAX(predicted_for) FROM predictions)
ORDER BY m.name;
"
```

### 2. Verify Evaluations

After the evaluator runs:

```bash
# Check that all predictions were evaluated
railway run --service postgres psql -U btcpredictor -d btcpredictor -c "
SELECT m.name, p.predicted_price, p.actual_price, p.error_pct
FROM predictions p
JOIN models m ON p.model_id = m.id
WHERE p.predicted_for = CURRENT_DATE
  AND p.actual_price IS NOT NULL
ORDER BY m.name;
"
```

## Monitoring

### Key Metrics to Watch

1. **Prediction Count**: Should be 4x higher (one per model)
2. **Daily Cron Duration**: May increase slightly (4 models to load/predict)
3. **Database Size**: Will grow ~4x faster for predictions table

### Alerting

Set up alerts for:

- Daily cron failures
- Database disk space (predictions table growth)
- Prediction count anomalies (e.g., fewer than expected models predicting)

## Troubleshooting

### Issue: "No active models found"

**Cause**: No models are marked as `is_active=true`

**Solution**:
```bash
# Activate all trained models
railway run --service postgres psql -U btcpredictor -d btcpredictor -c "
UPDATE models SET is_active = true WHERE trained_at IS NOT NULL;
"
```

### Issue: "Multiple predictions per date" Error

**Cause**: Migration didn't run or failed

**Solution**:
```bash
# Check current migration
railway run --service api sh -c "cd shared && alembic current"

# If not at head, upgrade
railway run --service api sh -c "cd shared && alembic upgrade head"
```

### Issue: One Model Fails, Others Don't Predict

**Cause**: In single-model mode, one failure stops the job

**Solution**: Ensure `--multi-model` flag is set (see step 3 above)

## Post-Deployment Tasks

1. **Monitor for 3 days** to ensure stable operation
2. **Update documentation** if any issues arise
3. **Create US-026** (Model Comparison Dashboard) to visualize multi-model predictions
4. **Archive old predictions** (optional) to manage database growth

## References

- **Spec**: `specs/us-025-multi-model-predictions.md`
- **Implementation Plan**: `specs/us-025-multi-model-predictions-plan.md`
- **GitHub Issue**: #27
- **Migration**: `shared/alembic/versions/c0a41e870a5e_add_model_id_to_unique_constraint_for_.py`
