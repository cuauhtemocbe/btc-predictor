# US-024: Multi-Model Training System - Railway Deployment Guide

## Overview

This guide explains how to deploy and run the US-024 multi-model training scripts on Railway.

**Scripts included:**
- `scripts/train_all_models.py` — Train all 4 ML models and auto-activate best
- `scripts/activate_model.py` — Manually activate a specific model by ID
- `scripts/list_models.py` — List all models with metrics

## Prerequisites

✅ Railway CLI installed and authenticated  
✅ BTC Predictor project deployed to Railway  
✅ At least 90 days of historical BTC prices in database  
✅ All services running (postgres, api)

## Deployment Steps

### 1. Verify Railway CLI is Configured

```bash
# Check authentication
railway whoami

# Link to your project (if not already linked)
railway link

# List services
railway status
```

### 2. Ensure Database is Populated

The multi-model training requires **at least 90 days** of historical BTC prices.

```bash
# Check how many days of data you have
railway run --service api psql $DATABASE_URL -c \
  "SELECT COUNT(DISTINCT DATE(timestamp)) as days FROM btc_prices;"

# If less than 90 days, backfill more data
railway run --service api python scripts/backfill_prices.py --days=120
```

## Running Scripts on Railway

### Train All Models

Train all 4 ML models (Linear, LSTM, XGBoost, ARIMA) with validation split:

```bash
railway run --service api python scripts/train_all_models.py
```

**Expected output:**
```
==================================================================
BTC Predictor - Multi-Model Training
==================================================================
Training linearModel...
✓ linearModel completed in 2.3s, validation error: 2.5%
Training lstmModel...
✓ lstmModel completed in 180s, validation error: 1.8%
Training xgboostModel...
✓ xgboostModel completed in 45s, validation error: 2.1%
Training arimaModel...
✓ arimaModel completed in 120s, validation error: 3.2%
Best model: lstm_v1 with 1.8% validation error
✓ Activated lstm_v1
==================================================================
✓ SUCCESS: Trained and saved 4 models
==================================================================
```

**What happens:**
1. Fetches last 90 days of BTC prices
2. Splits into train (70%), validation (20%), buffer (10%)
3. Trains all 4 models sequentially
4. Calculates MAPE validation error on holdout data
5. Saves all models to database with `is_active=false`
6. Activates model with lowest validation error

**Time estimate:** 5-10 minutes (LSTM training is slowest)

### List All Models

View all trained models with their metrics:

```bash
railway run --service api python scripts/list_models.py
```

**Expected output:**
```
==============================================================================================================
ID    Name                 Version    Active   Val Error    Trained At               
==============================================================================================================
5     lstm_v1              v1         ✓ Yes    1.80%        2026-05-19 10:05:23      
4     xgboost_v1           v1         No       2.10%        2026-05-19 10:03:15      
3     linear_v1            v1         No       2.50%        2026-05-19 10:00:02      
6     arima_v1             v1         No       3.20%        2026-05-19 10:10:45      
==============================================================================================================
Total: 4 model(s)
==============================================================================================================

Currently active model:
  • lstm_v1 (ID: 5)
  • Validation Error: 1.80%
  • Trained: 2026-05-19 10:05:23
```

### Activate Specific Model

Manually activate a model by ID:

```bash
# First, list models to get the ID
railway run --service api python scripts/list_models.py

# Activate model with ID 4 (xgboost_v1 in example above)
railway run --service api python scripts/activate_model.py --model-id=4
```

**Expected output:**
```
======================================================================
BTC Predictor - Activate Model #4
======================================================================
======================================================================
✓ SUCCESS
  Model ID:  4
  Name:      xgboost_v1
  Version:   v1
  Trained:   2026-05-19 10:03:15
  Val Error: 2.10%
======================================================================
All other models have been deactivated.
This model will now be used for predictions.
======================================================================
```

**Use case:** Override auto-selection if you want to test a different model in production.

## Automated Scheduled Training (Optional)

To retrain models weekly, create a new Railway service with a cron schedule:

### Option A: Using Railway Cron

1. **Create new service:**
   ```bash
   railway service create --name train-models-weekly
   ```

2. **Configure cron schedule:**
   ```bash
   railway variables set \
     --service train-models-weekly \
     RAILWAY_CRON_SCHEDULE="0 2 * * 0"  # Every Sunday at 2 AM UTC
   ```

3. **Set start command:**
   ```bash
   railway variables set \
     --service train-models-weekly \
     RAILWAY_RUN_UID=python \
     scripts/train_all_models.py
   ```

4. **Deploy:**
   ```bash
   railway up --service train-models-weekly
   ```

### Option B: Manual Scheduled Runs

Use your local cron or a service like GitHub Actions:

```yaml
# .github/workflows/train-models.yml
name: Weekly Model Training

on:
  schedule:
    - cron: '0 2 * * 0'  # Every Sunday at 2 AM UTC
  workflow_dispatch:  # Allow manual trigger

jobs:
  train:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Install Railway CLI
        run: npm install -g @railway/cli
      
      - name: Train Models
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
        run: railway run --service api python scripts/train_all_models.py
```

## Monitoring and Logs

### View Training Logs

```bash
# Stream logs from api service during training
railway logs --service api --follow
```

### Check Model Performance

After training, verify predictions use the new model:

```bash
# Trigger a prediction manually
railway run --service api python -m daily.predictor

# Check prediction used correct model
railway run --service api psql $DATABASE_URL -c \
  "SELECT p.predicted_for, m.name, m.version 
   FROM predictions p 
   JOIN models m ON p.model_id = m.id 
   ORDER BY p.predicted_at DESC 
   LIMIT 5;"
```

## Troubleshooting

### Error: "Insufficient training data"

**Cause:** Less than 90 days of BTC prices in database.

**Solution:**
```bash
# Backfill more historical data
railway run --service api python scripts/backfill_prices.py --days=120

# Verify data
railway run --service api psql $DATABASE_URL -c \
  "SELECT COUNT(*) FROM btc_prices;"
```

### Error: "Model training failed"

**Cause:** Specific model (e.g., LSTM, ARIMA) encountered training error.

**Solution:**
```bash
# Check full logs for error details
railway logs --service api --tail=200

# Common issues:
# - LSTM: Out of memory (need more RAM on Railway plan)
# - ARIMA: Non-stationary data (increase 'd' parameter in trainer.py)
# - XGBoost: Missing dependency (check requirements.txt)
```

### No Active Model After Training

**Cause:** All models failed validation or had errors.

**Solution:**
```bash
# Check which models were saved
railway run --service api python scripts/list_models.py

# If models exist but none active, manually activate one
railway run --service api python scripts/activate_model.py --model-id=<ID>
```

## Best Practices

### 1. Retrain Regularly

Models trained on old data become stale as market conditions change.

**Recommendation:** Retrain weekly or bi-weekly with fresh data.

### 2. Monitor Validation Error Trends

Track validation error over time to detect when model quality degrades:

```bash
# Query validation error history
railway run --service api psql $DATABASE_URL -c \
  "SELECT name, version, trained_at, params->>'validation_error_pct' as val_error 
   FROM models 
   WHERE name LIKE 'lstm%' 
   ORDER BY trained_at DESC 
   LIMIT 10;"
```

### 3. A/B Test Models

Before fully switching to a new model, run both in parallel:

1. Train new models (save as v2, v3, etc.)
2. Keep old model active for production
3. Manually compare predictions
4. Activate new model when confident

### 4. Resource Planning

**RAM requirements:**
- Linear Regression: ~500MB
- XGBoost: ~1GB
- LSTM: ~2GB (TensorFlow overhead)
- ARIMA: ~800MB

**Recommendation:** Use Railway plan with at least 4GB RAM for smooth multi-model training.

## Next Steps

After deploying US-024:

1. ✅ Run `train_all_models.py` to create initial models
2. ✅ Verify active model with `list_models.py`
3. ✅ Update predictor job to use active model
4. ✅ Set up weekly retraining (optional)
5. ✅ Monitor validation error trends
6. 📈 Proceed to US-025 (Multi-Model Predictions) for parallel predictions

## Support

**Issues:** https://github.com/cuauhtemocbe/btc-predictor/issues  
**Docs:** `/docs/railway/`  
**Contact:** cuauhtemocbe@gmail.com
