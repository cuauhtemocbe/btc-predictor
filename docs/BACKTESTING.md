# Walk-Forward Backtesting Guide

## Overview

The BTC Predictor backtesting system allows you to validate the model's effectiveness by simulating historical predictions. It uses **walk-forward testing** (also called rolling-window backtesting) to train models progressively on historical data and test predictions on out-of-sample data, mimicking real-world usage.

## What is Walk-Forward Backtesting?

Walk-forward backtesting trains a model on a rolling window of past data, generates a prediction for the next day, evaluates it against actual prices, and repeats this process for each historical day:

```
Day 0-29: Train model on first 30 days
Day 30: Predict price for day 31
Day 31: Evaluate prediction against actual price

Day 1-30: Re-train model (rolling window)
Day 31: Predict price for day 32
Day 32: Evaluate prediction

... repeat for all historical days
```

**Key Principle: No Lookahead Bias**  
The model never sees future data during training. For each prediction, it only uses data available up to that point in time, ensuring realistic simulation.

## Prerequisites

Before running backtests, ensure you have:

1. ✅ **Historical BTC prices**: Run the backfill script (US-019) to load 90+ days of data
2. ✅ **Database migration**: The `backtest_results` table must exist (automatic via Alembic)
3. ✅ **Docker containers running**: `docker compose up -d`

Check data availability:
```bash
docker compose exec postgres psql -U btcpredictor -d btcpredictor \
  -c "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM btc_prices;"
```

## Running a Backtest

### Basic Usage

```bash
docker compose exec api python scripts/backtest.py \
  --start-date=2024-05-01 \
  --end-date=2024-05-30
```

This will:
1. Generate a unique backtest run ID (UUID)
2. For each day from May 1-30:
   - Train a LinearRegressionModel on the previous 30 days
   - Predict the next day's BTC price
   - Calculate all 4 PnL strategies
   - Save results to `backtest_results` table
3. Log progress every 10 days
4. Display summary statistics

### CLI Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--start-date` | Yes | - | Start date for backtest (YYYY-MM-DD) |
| `--end-date` | Yes | - | End date for backtest (YYYY-MM-DD) |
| `--training-window` | No | 30 | Training window in days |

### Examples

**Backtest May 2024 (30 days):**
```bash
docker compose exec api python scripts/backtest.py \
  --start-date=2024-05-01 \
  --end-date=2024-05-31
```

**Backtest with 60-day training window:**
```bash
docker compose exec api python scripts/backtest.py \
  --start-date=2024-05-01 \
  --end-date=2024-05-31 \
  --training-window=60
```

**Backtest last 90 days:**
```bash
docker compose exec api python scripts/backtest.py \
  --start-date=2024-02-01 \
  --end-date=2024-04-30
```

## Understanding Backtest Results

### Database Schema

Results are stored in the `backtest_results` table:

```sql
SELECT 
    backtest_run_id,
    predicted_for,
    predicted_price,
    actual_price,
    pnl_simple,
    pnl_long_short,
    pnl_threshold,
    pnl_realistic
FROM backtest_results
WHERE backtest_run_id = '<UUID>'
ORDER BY predicted_for;
```

### PnL Strategies

The backtest calculates 4 PnL strategies for each prediction:

1. **Simple** (`pnl_simple`): Buy if predicted UP, stay in cash otherwise
2. **Long/Short** (`pnl_long_short`): Long if predicted UP, short if predicted DOWN
3. **Threshold** (`pnl_threshold`): Only trade if predicted change > 1%
4. **Realistic** (`pnl_realistic`): With trading fees (0.1%) and stop-loss (2%)

### Example Queries

**Get backtest summary:**
```sql
SELECT 
    backtest_run_id,
    COUNT(*) AS predictions,
    SUM(pnl_simple) AS total_simple,
    SUM(pnl_long_short) AS total_long_short,
    SUM(pnl_threshold) AS total_threshold,
    SUM(pnl_realistic) AS total_realistic,
    AVG(ABS(actual_price - predicted_price)) AS avg_error,
    MIN(predicted_for) AS start_date,
    MAX(predicted_for) AS end_date
FROM backtest_results
WHERE backtest_run_id = '<UUID>'
GROUP BY backtest_run_id;
```

**Find best/worst predictions:**
```sql
-- Best prediction (smallest error)
SELECT 
    predicted_for,
    predicted_price,
    actual_price,
    ABS(actual_price - predicted_price) AS error,
    pnl_realistic
FROM backtest_results
WHERE backtest_run_id = '<UUID>'
ORDER BY error ASC
LIMIT 5;

-- Worst prediction (largest error)
SELECT 
    predicted_for,
    predicted_price,
    actual_price,
    ABS(actual_price - predicted_price) AS error,
    pnl_realistic
FROM backtest_results
WHERE backtest_run_id = '<UUID>'
ORDER BY error DESC
LIMIT 5;
```

**Compare multiple backtest runs:**
```sql
SELECT 
    backtest_run_id,
    COUNT(*) AS predictions,
    SUM(pnl_realistic) AS total_pnl,
    AVG(pnl_realistic) AS avg_pnl_per_day,
    STDDEV(pnl_realistic) AS pnl_volatility
FROM backtest_results
GROUP BY backtest_run_id
ORDER BY total_pnl DESC;
```

**Cumulative PnL over time:**
```sql
SELECT 
    predicted_for,
    predicted_price,
    actual_price,
    pnl_realistic,
    SUM(pnl_realistic) OVER (
        PARTITION BY backtest_run_id 
        ORDER BY predicted_for
    ) AS cumulative_pnl
FROM backtest_results
WHERE backtest_run_id = '<UUID>'
ORDER BY predicted_for;
```

## Interpreting Results

### Success Metrics

- **Total PnL**: Sum of all PnL values (higher is better)
- **Average Error**: Mean absolute difference between predicted and actual prices
- **Prediction Accuracy**: Percentage of predictions in correct direction
- **Sharpe Ratio**: Risk-adjusted returns (PnL / volatility)

### What to Look For

✅ **Good Signs:**
- Positive cumulative PnL (especially for `pnl_realistic`)
- Consistent performance across different time periods
- Low average error relative to price volatility
- Realistic strategy outperforms simple strategy (shows robustness)

⚠️ **Red Flags:**
- Large negative PnL
- High volatility in daily PnL
- Model performs worse than random guessing (50% direction accuracy)
- Overfitting: excellent training performance but poor backtest results

### Example Interpretation

```
Backtest Run: 30 days (May 2024)
Total PnL (Realistic): +$2,450
Average PnL per day: +$81.67
Average Error: $350 (0.5% of price)
Direction Accuracy: 58%
```

**Interpretation**: The model shows modest predictive power with 58% directional accuracy (better than random 50%). Positive PnL suggests the model can be profitable after fees, but relatively small edge means position sizing and risk management are critical.

## Performance Tips

For faster backtests:

1. **Use smaller date ranges**: Test 7-30 days first, then scale up
2. **Optimize training window**: Smaller windows train faster (but may reduce accuracy)
3. **Run in background**: Use `nohup` or `screen` for long backtests
4. **Monitor database size**: Backtest results accumulate; clean old runs periodically

## Troubleshooting

### Error: "Insufficient data"

```
ValueError: Insufficient data: need at least 30 days of data before 2024-05-01
```

**Solution**: Run the backfill script to load more historical data:
```bash
docker compose exec api python scripts/backfill_daily_prices.py --days=90
```

### Error: "No actual price data"

```
WARNING: Skipping 2024-05-15: no actual price data
```

**Cause**: Gap in historical data (exchange downtime, API failure)

**Solution**: The script automatically skips days with missing data. Check data quality:
```sql
SELECT DATE(timestamp), COUNT(*) AS hourly_records
FROM btc_prices
GROUP BY DATE(timestamp)
HAVING COUNT(*) < 24
ORDER BY DATE(timestamp);
```

### Error: "Model training failed"

```
WARNING: Skipping 2024-05-20: training failed - X contains NaN values
```

**Cause**: Data quality issue (NaN, infinite values)

**Solution**: Investigate data source and re-run backfill. Check for outliers:
```sql
SELECT * FROM btc_prices
WHERE close IS NULL 
   OR close = 0 
   OR close > 1000000
ORDER BY timestamp;
```

### Performance: Slow backtests

If 90-day backtest takes > 5 minutes:

1. Check database indexes: `\d backtest_results`
2. Profile the script: `python -m cProfile scripts/backtest.py ...`
3. Consider parallel processing (future enhancement)

## Limitations

### Current Limitations

- **Single model**: Only LinearRegressionModel supported (no LSTM, XGBoost yet)
- **Fixed training window**: 30 days (configurable via CLI, but not per-day adaptive)
- **Sequential processing**: No parallelization
- **No parameter optimization**: Manual hyperparameter tuning required

### Future Enhancements (US-021+)

- [ ] Web dashboard for backtest visualization (US-021)
- [ ] Multi-model comparison (US-023-026)
- [ ] Multi-timeframe predictions (weekly, monthly)
- [ ] Parameter optimization (grid search, Bayesian optimization)
- [ ] Walk-forward optimization (optimize hyperparameters during backtest)

## Deployment on Railway

The backtest script is accessible in the Railway `api` service:

```bash
# Via Railway CLI
railway run python scripts/backtest.py --start-date=2024-05-01 --end-date=2024-05-30

# Or SSH into service and run directly
railway shell
cd /app
python scripts/backtest.py --start-date=2024-05-01 --end-date=2024-05-30
```

**Note**: Long-running backtests (>30 days) may timeout on Railway's free tier. For large backtests, run locally and sync results to production database.

## Related Documentation

- [US-020 Specification](../specs/us-020-walk-forward-backtesting.md)
- [US-020 Implementation Plan](../specs/us-020-walk-forward-backtesting-plan.md)
- [Implementation History](../docs/archive/specs/IMPLEMENTATION_HISTORY.md)
- [US-021: Backtesting Dashboard](https://github.com/cuauhtemocbe/btc-predictor/issues/23) (future)

## FAQs

**Q: How is backtesting different from real-time predictions?**  
A: Backtesting simulates historical predictions to validate model effectiveness before risking real capital. Real-time predictions use the latest data to predict tomorrow's price.

**Q: Why use walk-forward instead of train-test split?**  
A: Walk-forward mimics real-world usage where you retrain daily with new data. Traditional train-test split trains once on old data, which doesn't reflect model performance with fresh data.

**Q: Can I backtest on custom date ranges?**  
A: Yes! Use `--start-date` and `--end-date` to specify any range where you have historical data.

**Q: How do I compare different models?**  
A: Run multiple backtests with different `backtest_run_id` UUIDs and compare results in the database. Future releases (US-023+) will support multi-model backtesting.

**Q: What's a good PnL result?**  
A: It depends on your risk tolerance and market conditions. Positive PnL with `pnl_realistic` (after fees) is good. Compare against buy-and-hold strategy for baseline.

---

**Last Updated**: 2026-05-19  
**User Story**: US-020 Walk-Forward Backtesting System  
**Status**: ✅ Implemented
