# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Asset selector on the dashboard, models and backtesting pages: a `symbol` query
  parameter (`BTCUSDT` by default, `PAXGUSDT` for gold) scopes every table, chart
  and JSON endpoint (`/api/predictions/*`, `/api/prices`, `/api/backtesting/metrics`,
  `/models/metrics`) to one asset, an unknown symbol is a 422, and gold is labelled
  as a gold-backed token proxy, not XAU spot. An asset with no predictions shows an
  explanatory empty state (#107).
- The models view shows each model's always-up and persistence accuracy, buy-and-hold
  PnL, sample size and edge next to its own metrics, marked "Beats baseline",
  "Not significant" or "Does not beat baseline" with a glyph, not only a color.
  Baselines are daily-only; other timeframes show N/A. `/models/metrics` returns the
  same data under `baseline` (`shared/shared/model_baselines.py`) (#107).
- Baseline comparison (`shared/baselines.py`): every model's direction
  accuracy and simple-strategy PnL is shown next to always-up, persistence and
  buy-and-hold over exactly the days it was evaluated on, with the sample size,
  the edge over the best baseline and a one-sided binomial p-value; no
  evaluated days reports "unavailable", not zero (#105).
- Walk-forward backtest with production parity (`scripts/backtest_engine.py`,
  `scripts/backtest_report.py`): it trains with the same feature builder and
  model factory as the daily worker on an expanding window with no lookahead,
  supports `--model`, `--seed`, `--retrain-every` and `--test-start-date`, labels
  rows `validation` or `test` (new `backtest_results.evaluation_slice` column) and
  headlines only the test slice. A start date without enough history fails before
  storing anything and names the earliest allowed one (#106).

### Changed

- The backtest no longer builds price-level windows by hand: `scripts/backtest_utils.py`
  was removed, `--training-window` defaults to `settings.training_window_days`
  (21, was 30) and results are stored in one transaction (#106).

- The daily and weekly Linear models train on log returns instead of price
  levels. One builder (`shared/features.py`) turns daily closes and volumes
  into lagged log returns, rolling volatility and log volume changes, and the
  stored predicted price is `last close * exp(predicted return)`. Models stored
  before this change are rejected by the predictors until the trainers replace
  them (#104).
- The fetch-price job ingests each closed daily bar from Binance (daily file,
  REST klines fallback, missed days backfilled) instead of CoinGecko; the
  CoinGecko and old Binance clients were removed (#102).

### Fixed

- The daily and weekly evaluators scored nothing since the move to daily bars:
  they looked for a candle at or after 07:00 UTC, and daily bars are stored at
  00:00 UTC. Both now settle each prediction against the close of the bar it
  predicted (the bar opened the day before `predicted_for`) and pick up every
  pending prediction of their timeframe due up to today, so a late bar no
  longer leaves one unevaluated for good (#143).

### Added

- Dev Standards Compliance hardening: container healthcheck, pinned base
  image, self-documented Makefile, `mypy --strict` on `shared/`, enforced
  coverage gate, secret scanning, LICENSE, CHANGELOG, and accessibility
  glyphs for PnL indicators.

## [0.1.0] - 2026-07-18

### Added

- Shared package with database configuration and Alembic migrations.
- BTC price ingestion from CoinGecko with an hourly-to-daily fetch cron.
- `GET /api/prices` endpoint.
- Abstract `BaseModel` ML interface with a Linear Regression baseline,
  and a `models` table for model versioning.
- Two-phase daily prediction lifecycle: predictor job inserts a prediction,
  evaluator job fills in the actual price, errors, and PnL the next day.
- Web dashboard (`GET /`) and `GET /api/predictions/history` endpoint.
- Simulated PnL calculation and `GET /api/predictions/pnl` endpoint.
- Railway cron automation for the fetch-price and daily jobs.
- Multiple PnL trading strategies (simple, long/short, threshold, realistic)
  with a strategy comparison dashboard.
- Historical BTC price backfill and a walk-forward backtesting system with
  a results dashboard.
- Weekly multi-timeframe predictions, advanced ML models (LSTM, XGBoost,
  ARIMA), and a multi-model training/comparison system.
- Dynamic training window strategy that auto-scales from 30 to 145+ days
  of historical data across five progressive phases.

### Changed

- Migrated the price data source from Binance to CoinGecko after Binance
  started returning HTTP 451 (geo-blocking) on Railway.
- Migrated price ingestion from hourly to daily frequency with 4-hour
  candle aggregation.

### Fixed

- Evaluator lookup of 4-hour candles that previously failed to match the
  expected evaluation time.

### Removed

- Temporary admin backfill endpoint that caused service failures in
  production.

[Unreleased]: https://github.com/cuauhtemocbe/btc-predictor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/cuauhtemocbe/btc-predictor/releases/tag/v0.1.0
