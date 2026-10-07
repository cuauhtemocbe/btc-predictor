# Walk-Forward Backtesting Guide

## Overview

The BTC Predictor backtesting system allows you to validate the model's effectiveness by simulating historical predictions. It uses **walk-forward testing** (also called rolling-window backtesting) to train models progressively on historical data and test predictions on out-of-sample data, mimicking real-world usage.

## What is Walk-Forward Backtesting?

Walk-forward backtesting trains a model on the data available before a day, predicts that day, compares the prediction with what happened, and repeats for every day of the range:

```
Predict 2024-06-10: train on every daily row dated 2024-06-09 or earlier
Predict 2024-06-11: train on every daily row dated 2024-06-10 or earlier
... one prediction (and one stored row) per day
```

**Key principle: no lookahead.** The price series is loaded once and sliced in memory, so the training data of a day only contains rows dated before it. The window is *expanding* (every earlier row), exactly like the daily worker, which trains on every stored `BTCUSDT` daily row.

**Production parity.** The backtest has no feature or model code of its own (`scripts/backtest_engine.py`). It calls the same code the daily worker runs:

| Step | Code (shared with production) |
|------|-------------------------------|
| Training samples | `shared.features.build_training_set` (log returns, rolling volatility, log volume changes) |
| Prediction features | `shared.features.build_prediction_features` |
| Predicted price | `shared.features.price_from_return` (`last close * exp(predicted return)`) |
| Model construction | `workers.daily.models.factory.build_model` (the daily trainer builds its model with it too) |

If the daily worker changes, the backtest changes with it.

## Prerequisites

Before running backtests, ensure you have:

1. ✅ **Historical BTC prices**: Run `scripts/load_binance_history.py` (#101) to load years of daily data
2. ✅ **Database migration**: The `backtest_results` table must exist (automatic via Alembic)
3. ✅ **Docker containers running**: `docker compose up -d`

Check data availability:
```bash
docker compose exec postgres psql -U btcpredictor -d btcpredictor \
  -c "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM prices;"
```

## Running a Backtest

### Basic Usage

```bash
docker compose exec api python scripts/backtest.py \
  --start-date=2024-05-01 \
  --end-date=2024-05-30
```

This will:
1. Check there is enough history before the start date (see "Troubleshooting")
2. Generate a unique backtest run ID (UUID)
3. For each day, train the model on the rows before it and predict the day's close
4. Store one `backtest_results` row per day, in a single transaction (nothing is stored if the run fails)
5. Log progress every 10 days, then print the PnL summary and the **report** (see "Reading the report")

### CLI Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--start-date` | Yes | - | First day predicted (YYYY-MM-DD) |
| `--end-date` | Yes | - | Last day predicted (YYYY-MM-DD, inclusive) |
| `--model` | No | `linear` | `linear` (the only model since #184) |
| `--training-window` | No | `settings.training_window_days` (21) | Window in days; same default as production |
| `--seed` | No | 42 | Seeds `random`, `numpy` and TensorFlow before every training |
| `--retrain-every` | No | 1 | Retrain every N days and reuse the model in between |
| `--test-start-date` | No | start of the last 30% of the range | First day of the test slice |

### Examples

**Backtest 2024 with the production window:**
```bash
docker compose exec api python scripts/backtest.py \
  --start-date=2024-01-01 --end-date=2024-12-31
```

**Explicit validation/test split:**
```bash
docker compose exec api python scripts/backtest.py \
  --start-date=2023-01-01 --end-date=2025-12-31 \
  --test-start-date=2025-01-01
```

**Retrained monthly:**
```bash
docker compose exec api python scripts/backtest.py \
  --start-date=2024-01-01 --end-date=2024-12-31 \
  --retrain-every=30
```

**Print the report of a stored run again:**
```bash
docker compose exec api python scripts/backtest_report.py --run-id=<UUID>
```

### Validation and test slices

The range is split in two: the `validation` slice (before `--test-start-date`) is the only data allowed to inform choices such as the window or a model's hyperparameters; the `test` slice is the out-of-sample result and is never used to choose anything. Every row stores its slice in `evaluation_slice`. Rows stored before the split existed have `NULL` there and are reported as `unsplit`.

If you tune something, tune it by looking only at validation metrics, then run once more and read the test slice. Looking at the test slice and changing the setup afterwards turns it into a second validation set.

### Reproducibility

The same data, parameters and `--seed` store identical predictions (verified for Linear). `--seed` is applied before every training. Stored in each row's `model_params`: `model_name`, `symbol`, `window_days`, `seed`, `retrain_every`, `test_start_date`, `train_from`, `train_to` (the last day the model in use was trained on) and `training_samples`.

### Retrain frequency

Training every day is expensive for the heavy models. `--retrain-every N` retrains on the 1st, (N+1)th, (2N+1)th... day and reuses the model in between, while the prediction features are always rebuilt from data before each day. The frequency is stored in every row and printed in the report: compare runs only when they use the same frequency.

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
    pnl_realistic,
    evaluation_slice   -- 'validation', 'test' or NULL (stored before the split)
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

## Reading the report

Every run ends with a report; `scripts/backtest_report.py --run-id=<UUID>` prints it again. Real output (Linear, window 21, seed 42, retrain every day, `BTCUSDT` daily data up to 2026-08-31):

```
Model: linear  window: 21d  seed: 42  retrain every: 1 day(s)
Range: 2019-01-01 to 2026-08-31
Test slice starts: 2024-01-01

== Headline: test slice (out-of-sample), 974 evaluated days ==
  Model accuracy:          51.23%
  Always-up accuracy:      50.72%
  Persistence accuracy:    49.08% (974 days)
  Best baseline:           always_up
  Edge over best baseline: +0.51 pp (p = 0.3866, not significant at 0.05)
  Model PnL (simple):      $38,486.31
  Always-up PnL:           $36,297.71
  Persistence PnL:         $23,099.84
  Buy-and-hold PnL:        $36,297.71

-- Validation slice (tuning only, never a result), 1826 evaluated days --
  Model accuracy:          48.69%
  Always-up accuracy:      51.20%
  Persistence accuracy:    45.29% (1826 days)
  Best baseline:           always_up
  Edge over best baseline: -2.52 pp (p = 0.9852, not significant at 0.05)
  Model PnL (simple):      -$8,659.53
  Always-up PnL:           $38,580.68
  Persistence PnL:         -$9,998.53
  Buy-and-hold PnL:        $38,580.68
```

This run, and the one with the monthly-cron configuration (last 365 days, last 100 as test), are summarised in the "Resultados" section of the [README](../README.md#-resultados). Neither shows a statistically significant edge over the baselines.

- **Headline = test slice only.** Validation numbers are a separate, labelled section.
- **Baselines are computed on exactly the days the model was evaluated on**, so the comparison is like for like.
- **Sample size** is always shown. With a few hundred days a difference of one or two points is noise.
- **No data, no number**: a slice with no evaluated days prints `unavailable`, never `0`.

### Baselines

Direction rules follow the evaluator: the day is UP when `actual_price >= price_at_prediction` (a flat day counts as UP); a model predicts UP when `predicted_price > price_at_prediction`.

| Baseline | Definition |
|----------|------------|
| **Always-up** | Predicts UP every day. Its simple-strategy PnL (long 1 BTC every day) equals the buy-and-hold PnL of the period. |
| **Persistence** | Predicts tomorrow's direction is today's: UP when `price_at_prediction >= close of the day before`. That close comes from `prices`, so every evaluated day is covered. A day without it is left out of persistence only (its day count is shown). |
| **Buy-and-hold** | Last `actual_price` minus first `price_at_prediction` of the slice (1 BTC, USDT). |

Reference values from the spike (BTC daily 2017-2026): always-up direction accuracy 51.1%, persistence 46.5%. A model that does not beat these adds nothing.

### Edge and significance

`edge = model accuracy - best baseline accuracy`, with the number of evaluated days and a one-sided binomial-test p-value: how likely a coin that is right as often as the best baseline would be to get at least as many days right as the model did. `significant` means `p < 0.05`.

It is an **approximation**: the baseline's accuracy is treated as a fixed probability, and picking the best of two baselines is not corrected for. Read a small p-value as "worth a closer look", not as proof, and a large one as "indistinguishable from the baseline".

### What to look for

✅ **Good signs:**
- Test-slice accuracy above the best baseline with a small p-value, over a sample of hundreds of days
- A model PnL that beats always-up and persistence on the test slice, not only on validation
- Similar behaviour across different test periods

⚠️ **Red flags:**
- Great validation numbers and a test slice that collapses (overfitting to the validation choices)
- A positive PnL in a rising market that always-up matches or beats
- A tiny sample, or a retrain frequency different from the run you compare against

## Performance Tips

For faster backtests:

1. **Use smaller date ranges**: Test 7-30 days first, then scale up
2. **Optimize training window**: Smaller windows train faster (but may reduce accuracy)
3. **Run in background**: Use `nohup` or `screen` for long backtests
4. **Monitor database size**: Backtest results accumulate; clean old runs periodically

## Troubleshooting

### Error: "Start date ... has only N daily rows before it"

```
Start date 2023-01-10 has only 9 daily rows before it but BTCUSDT needs 30 (window=5d):
the earliest allowed start date is 2023-01-31 (first loaded day 2023-01-01)
```

**Cause**: production needs `(window + 1) * 5` daily rows to train, and fewer precede the start date. Nothing was stored.

**Solution**: use the start date the message gives, or load more history:
```bash
docker compose exec api python scripts/load_binance_history.py
```

### Error: "No actual price data"

```
WARNING: Skipping 2024-05-15: no actual price
```

**Cause**: A day is missing from the stored daily series (a gap in the history load or in the daily ingest)

**Solution**: The script automatically skips days with missing data. Look for gaps in the daily series:
```sql
SELECT DATE(timestamp) AS day,
       LEAD(DATE(timestamp)) OVER (ORDER BY timestamp) AS next_day
FROM prices
WHERE symbol = 'BTCUSDT'
ORDER BY timestamp;
-- a gap is any row where next_day - day > 1; fill it with scripts/load_binance_history.py
```

### Error: "Model training failed"

```
WARNING: Skipping 2024-05-20: training failed - X contains NaN values
```

**Cause**: Data quality issue (NaN, infinite values) in the stored daily rows

**Solution**: Investigate the stored rows and reload them with `scripts/load_binance_history.py`. Check for outliers:
```sql
SELECT * FROM prices
WHERE symbol = 'BTCUSDT'
  AND (close IS NULL OR close = 0 OR close > 1000000)
ORDER BY timestamp;
```

### Error: "Every one of the N days failed to train"

```
ValueError: Every one of the 91 days failed to train the linear model, nothing was stored;
first error: X must have 5 features (window_days), got 11
```

**Cause**: the model rejects what the production code gives it. Every model is built with the feature count of the production builder (`2 * window_days + 1`, #104) through `workers.daily.models.factory`; this error means a model class was built with another width. The backtest reproduces the daily trainer's behaviour on purpose instead of working around it.

### Performance: Slow backtests

A year of Linear predictions (retrain every day) takes about 10 s. If a run takes much longer:

1. Check database indexes: `\d backtest_results`
2. Profile the script: `python -m cProfile scripts/backtest.py ...`
3. Consider parallel processing (future enhancement)

## Limitations

### Current Limitations

- **One model**: the linear model is the only one (#184). `--model` accepts only `linear`; XGBoost, LSTM and ARIMA were removed and live in git history.
- **Expanding window only**: like production; there is no rolling-window mode.
- **No hyperparameter search**: the validation/test split and its labelling make it possible to tune without leaking, but no tuner is built in.
- **Sequential processing**: No parallelization
- **One asset in the CLI**: the script backtests `BTCUSDT` only; `PAXGUSDT` (the gold proxy) is ingested and shown on the dashboard but has no backtest or production model

### Future Enhancements (US-021+)

- [ ] Web dashboard for backtest visualization (US-021)
- [ ] Multi-timeframe predictions (monthly)
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

### Monthly cron (`workers/backtest/`)

The monthly Railway cron (`Dockerfile.backtest`) runs `scripts/backtest.py` with the production configuration, so its stored results describe what the live system does:

- **Window**: `settings.training_window_days` (21, `TRAINING_WINDOW_DAYS`), passed as `--training-window`. It never picks its own window.
- **Range**: ends on the newest loaded day and covers the last 365 days. It starts no earlier than the earliest allowed start date for the window (`required_training_days(window)` rows must precede it), so a short history shortens the range instead of failing.
- **Split**: the last 100 days are the test slice (`--test-start-date`); everything before is validation.
- **Seed and retrain**: `--seed=42` and `--retrain-every=1`, logged at start and shown in the printed report.
- **Too little history**: exits 1 and logs the engine's message (the earliest allowed start date, or that no start date has enough history). It also exits 1 when the earliest allowed start date leaves fewer than 100 test days plus one validation day. It never shrinks the window to fit.

## Related Documentation

- [Baselines and walk-forward backtest spec](../specs/baselines-and-walk-forward-backtest.md) (#105, #106)
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
A: Run one backtest per `--model` with the same range, window, seed, `--retrain-every` and `--test-start-date`, and compare their test-slice reports: each is already shown next to the same baselines.

**Q: What's a good PnL result?**  
A: One that beats the baselines on the test slice with a sample large enough to tell it from chance. A positive PnL alone says little: in a rising market, buy-and-hold is positive too.

---

**Last Updated**: 2026-10-02  
**Issues**: US-020 Walk-Forward Backtesting System; #105 baselines; #106 production-parity walk-forward  
**Status**: ✅ Implemented
