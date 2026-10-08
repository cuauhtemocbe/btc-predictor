# Walk-Forward Backtesting Guide

`scripts/backtest.py` replays the daily job over past days to check the model against the baselines. For every day of a range it trains on the daily rows dated before that day, predicts the day's close, compares it with what happened, and stores one `backtest_results` row.

```
Predict 2024-06-10: train on every daily row dated 2024-06-09 or earlier
Predict 2024-06-11: train on every daily row dated 2024-06-10 or earlier
```

**No lookahead.** The price series is loaded once and sliced in memory, so the training data of a day only has rows dated before it. The window is *expanding*, like the daily worker, which trains on every stored `BTCUSDT` daily row.

**Production parity.** `scripts/backtest_engine.py` has no feature or model code of its own; it calls the code the daily worker runs (#106):

| Step | Code |
|------|------|
| Training samples | `shared.features.build_training_set` |
| Prediction features | `shared.features.build_prediction_features` |
| Predicted price | `shared.features.price_from_return` (`last close * exp(predicted return)`) |
| Model construction | `workers.daily.models.factory.build_model` |

## Running a backtest

Needs the daily history loaded (`scripts/load_binance_history.py`, #101) and the containers up. Check the data with `SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM prices;`.

```bash
docker compose exec api python scripts/backtest.py --start-date=2024-05-01 --end-date=2024-05-30
```

The run checks there is enough history before the start date, creates a `backtest_run_id` (UUID), stores one row per day in a single transaction (nothing is stored if the run fails), logs progress every 10 days and prints the PnL summary and the report (see "Reading the report").

| Argument | Default | Description |
|----------|---------|-------------|
| `--start-date` | required | First day predicted (YYYY-MM-DD) |
| `--end-date` | required | Last day predicted, inclusive |
| `--model` | `linear` | The only model since #184 |
| `--training-window` | `settings.training_window_days` (21) | Window in days, the production default |
| `--seed` | 42 | Seeds `random` and `numpy` before every training |
| `--retrain-every` | 1 | Retrain every N days and reuse the model in between |
| `--test-start-date` | start of the last 30% of the range | First day of the test slice |

Print the report of a stored run again: `python scripts/backtest_report.py --run-id=<UUID>`.

### Validation and test slices

The `validation` slice (before `--test-start-date`) is the only data allowed to inform choices such as the window; the `test` slice is the out-of-sample result and never decides anything. Tune by looking only at validation, then run once more and read the test slice: choosing a setup by looking at the test slice turns it into a second validation set. Each row stores its slice in `evaluation_slice`; rows stored before the split have `NULL` and are reported as `unsplit`.

### Reproducibility and retrain frequency

The same data, parameters and `--seed` store identical predictions. Each row's `model_params` holds `model_name`, `symbol`, `window_days`, `seed`, `retrain_every`, `test_start_date`, `train_from`, `train_to` (the last day the model in use was trained on) and `training_samples`. `--retrain-every N` retrains on the 1st, (N+1)th, (2N+1)th day and so on, while the prediction features are rebuilt every day. Compare runs only when they use the same frequency.

## Results

`backtest_results` holds `backtest_run_id`, `predicted_for`, `predicted_price`, `actual_price`, `evaluation_slice` and four PnL columns, per 1 BTC in USDT:

1. `pnl_simple`: long if predicted UP, cash otherwise.
2. `pnl_long_short`: long if predicted UP, short if DOWN.
3. `pnl_threshold`: trades only if the predicted change is above 1%.
4. `pnl_realistic`: long/short with 0.1% fees and a 2% stop-loss.

```sql
-- Summary of one run
SELECT COUNT(*) AS predictions, SUM(pnl_simple) AS total_simple,
       SUM(pnl_realistic) AS total_realistic,
       AVG(ABS(actual_price - predicted_price)) AS avg_error,
       MIN(predicted_for) AS start_date, MAX(predicted_for) AS end_date
FROM backtest_results WHERE backtest_run_id = '<UUID>';

-- Cumulative PnL over time
SELECT predicted_for, pnl_realistic,
       SUM(pnl_realistic) OVER (ORDER BY predicted_for) AS cumulative_pnl
FROM backtest_results WHERE backtest_run_id = '<UUID>' ORDER BY predicted_for;
```

## Reading the report

Real output (Linear, window 21, seed 42, retrain every day, `BTCUSDT` up to 2026-08-31):

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
  (same lines; accuracy 48.69%, edge -2.52 pp, p = 0.9852)
```

This run and the monthly-cron configuration are summarised in the [README](../README.md#-resultados); neither shows a significant edge.

- The headline is the test slice only; validation is a separate, labelled section.
- Baselines are computed on exactly the days the model was evaluated on.
- The sample size is always shown; with a few hundred days a difference of one or two points is noise.
- A slice with no evaluated days prints `unavailable`, never `0`.

### Baselines

Direction rules follow the evaluator: a day is UP when `actual_price >= price_at_prediction` (flat counts as UP); a model predicts UP when `predicted_price > price_at_prediction`.

| Baseline | Definition |
|----------|------------|
| **Always-up** | Predicts UP every day; its simple PnL equals buy-and-hold. |
| **Persistence** | Predicts today's direction again: UP when `price_at_prediction >= close of the day before`, read from `prices`. A day without that close is left out of persistence only. |
| **Buy-and-hold** | Last `actual_price` minus first `price_at_prediction` of the slice. |

Reference values (BTC daily 2017-2026, spike): always-up 51.1%, persistence 46.5%.

### Edge and significance

`edge = model accuracy - best baseline accuracy`, with the number of days and a one-sided binomial p-value: how likely a coin as accurate as the best baseline is to get at least as many days right as the model. `significant` means `p < 0.05`. It is an approximation: the baseline's accuracy is a fixed probability and picking the best of two baselines is not corrected for, so a small p-value means "worth a closer look" and a large one "indistinguishable from the baseline".

Good signs: a test-slice accuracy above the best baseline with a small p-value over hundreds of days, and a PnL that beats always-up and persistence on test, not only on validation. Red flags: strong validation and a collapsing test slice (overfitting to validation choices); a positive PnL in a rising market that always-up matches; a tiny sample or a different retrain frequency.

## Troubleshooting

- **"Start date ... has only N daily rows before it"**: production needs `(window + 1) * 5` daily rows to train and fewer precede the start date. Nothing is stored. Use the start date the message gives, or load more history with `scripts/load_binance_history.py`.
- **"Skipping <day>: no actual price"**: a day is missing in the stored daily series. The script skips it. Find gaps with `SELECT DATE(timestamp) AS day, LEAD(DATE(timestamp)) OVER (ORDER BY timestamp) AS next_day FROM prices WHERE symbol = 'BTCUSDT'` (a gap is `next_day - day > 1`) and fill them with `scripts/load_binance_history.py`.
- **"Skipping <day>: training failed - X contains NaN values"**: bad rows in `prices` (NULL, 0 or outliers). Inspect and reload them.
- **"Every one of the N days failed to train"**: the model rejects what the production builder gives it, for example a width other than `2 * window_days + 1` (#104). The backtest reproduces the daily trainer on purpose instead of working around it.
- **Slow runs**: a year of Linear predictions with a daily retrain takes about 10 s; a much longer run is worth profiling.

## Limitations

- One model: `--model` accepts only `linear`; XGBoost, LSTM and ARIMA were removed in #184 and live in git history.
- Expanding window only, like production; no rolling-window mode, no hyperparameter search, no parallelism.
- `BTCUSDT` only: `PAXGUSDT` is ingested and shown on the dashboard but has no backtest or production model.

## Monthly cron (`workers/backtest/`)

The `monthly-backtest` service (`Dockerfile.backtest`, `python -m workers.backtest.main`) runs `scripts/backtest.py` with the production configuration:

- **Window**: `settings.training_window_days` (21), passed as `--training-window`; it never picks its own.
- **Range**: the last 365 days up to the newest loaded day, starting no earlier than the earliest allowed start date for the window, so a short history shortens the range instead of failing.
- **Split**: the last 100 days are the test slice; everything before is validation.
- **Seed and retrain**: `--seed=42` and `--retrain-every=1`, shown in the printed report.
- **Too little history**: exits 1 and logs the engine's message, also when the earliest allowed start leaves fewer than 100 test days plus one validation day. It never shrinks the window to fit.

To run a backtest on Railway: `railway run python scripts/backtest.py --start-date=2024-05-01 --end-date=2024-05-30`.

## Related

- [Baselines and walk-forward backtest spec](../specs/baselines-and-walk-forward-backtest.md) (#105, #106)
- [Implementation history](archive/specs/IMPLEMENTATION_HISTORY.md)
