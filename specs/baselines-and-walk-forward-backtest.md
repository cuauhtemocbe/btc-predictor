---
title: Baseline Comparison and Walk-Forward Backtest
status: completed
created: 2026-09-30
updated: 2026-10-06
issue: "#105, #106"
---

# Baseline Comparison and Walk-Forward Backtest

**Objective.** Make every reported result honest: compare each model with trivial baselines (always-up, persistence, buy-and-hold) with its sample size and a significance measure (#105), and produce the results from a walk-forward backtest that runs the production feature and model code, has no lookahead and computes the headline only on out-of-sample data (#106). Both shipped in PR #136 (2026-10-01) because the backtest report is the first consumer of the baselines. Gherkin scenarios: the issues. User-facing description: `docs/BACKTESTING.md`.

## Decisions

- **Reference values** (spike, BTC daily 2017-2026): always-up direction accuracy 51.1%, persistence 46.5%. A model has to beat them.
- **Direction rule** is the evaluator's: predicted UP iff `predicted_price > price_at_prediction`; actual UP iff `actual_price >= price_at_prediction` (flat counts as UP). PnL is per 1 BTC in USDT.
- **Baselines** (`shared/shared/baselines.py`) are computed on exactly the days the model was evaluated on. Persistence predicts UP iff `price_at_prediction >= previous_close` (close of D-2); a day without it is left out of persistence only. Buy-and-hold is the last `actual_price` minus the first `price_at_prediction`. With no evaluated days every figure is `None`, never `0`.
- **Edge and p-value.** `edge = model accuracy - best baseline accuracy`, with `n_days` and a one-sided binomial p-value (`significant` is `p < 0.05`), computed with the standard library in log space (`math.lgamma`) so `shared` gains no dependency; `scipy.stats.binomtest` is the oracle in tests only. It is an approximation: it treats the best baseline's accuracy as fixed and ignores having picked the best of two baselines, and `docs/BACKTESTING.md` says so.
- **Production parity.** `scripts/backtest_engine.py` calls `shared.features.build_training_set`, `build_prediction_features` and `price_from_return`, and builds models through `workers/daily/models/factory.py::build_model`, which the trainer uses too. The old `scripts/backtest_utils.py` (price-level windows, one query per day, a 30-day default window) was deleted. The window defaults to `settings.training_window_days`.
- **No lookahead.** The daily series is loaded once with the trainer's aggregation and sliced in memory: day D trains on rows dated before D, with an expanding window like production.
- **Reproducibility.** `--seed` (default 42) seeds `random` and `numpy` before every training; the same data, seed and parameters store identical `predicted_price` values. `--retrain-every N` (default 1) retrains every N days and rebuilds the features every day; N is stored in each row's `model_params` and printed in the report.
- **Out-of-sample split.** `--test-start-date` (default: the start of the last 30% of the range) labels each row in the new nullable column `backtest_results.evaluation_slice` (`validation` or `test`, CHECK constraint; legacy rows are `NULL`, reported as "unsplit"). The headline uses only `test` rows; `validation` is a separate labelled section; both show baselines and edge.
- **Safety.** If the start date is earlier than the first loaded day plus `required_training_days(window)`, the run aborts before writing anything and names the earliest allowed start date. A failed precondition writes no rows.
- **Performance budget.** Linear, 365 predicted days, retrain every day: under 60 s in the `api` container (measured 8.1 s on the real data, 366 days).

## Left out on purpose

Dashboard and API exposure of the baselines (#107), the final results page (#109), hyperparameter search, a rolling-window mode, backtests of assets other than `BTCUSDT`, and transaction costs beyond `pnl_realistic`.

## Outcome at delivery (since changed)

The backtest accepted any model by name (`linear`, `xgboost`, `lstm`, `arima`). `xgboost` and `lstm` were strict xfails because they still rejected the return features the production builder gave them (#124); the backtest reproduced that failure instead of working around it, and raises when every day fails to train. LSTM, XGBoost and ARIMA were removed in #184: `--model` now accepts only `linear`.

Tests: `shared/tests/test_baselines.py`, `scripts/tests/test_backtest_engine.py`, `test_backtest_report.py`, `test_backtest_cli.py`. Plan: `baselines-and-walk-forward-backtest-plan.md`.
