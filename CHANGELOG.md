# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Per-module coverage gate: `[tool.coverage_thresholds]` in `pyproject.toml` sets a
  minimum line coverage for each critical module (trainers, predictors, evaluators,
  models, backtest, crud, utils, features, baselines, ingest, API routers), and
  `scripts/check_coverage_thresholds.py` fails naming every module that is below its
  minimum or missing from `coverage.xml`. It runs in the "Docker quality gate" job right
  after the coverage run and in `scripts/validate.sh` (pre-push) (#68).
- CI, `scripts/validate.sh`, the pre-commit hooks and `make lint` run ruff on `shared`,
  `api`, `workers` and `scripts`, and `mypy --strict` on `shared`, `workers`, `api`
  and `scripts` (test code outside `shared/tests` excluded) (#68).
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
- A `source` query parameter (`live`, `replay` or `all`, default `all`) on the
  dashboard, `/models/`, `/models/metrics` and `/api/predictions/history` separates
  the predictions of replayed models (`params["simulated"]`, written by
  `scripts/simulate_history.py`) from live ones. Each history row carries
  `is_replay`; the dashboard shows a "Replay" badge and one headline block per
  source, each with its sample size and baselines, and the "Live + replay" total
  only under `source=all`. A value other than the three is a 422 (#176).

### Changed

- Mutation testing no longer runs weekly: `quality.yml` (now named "Mutation Testing") has only the `workflow_dispatch` trigger, so it runs on demand (#192).
- **Displayed risk numbers change** (#177). Max drawdown, the Sharpe ratio and the
  equity curve are now derived from returns, `pnl / price_at_prediction`, compounded
  from 1.0 and recomputed on read; the stored `pnl_*` columns and the schema do not
  change. Before, "Max Drawdown" was the worst single-day PnL in dollars, and the
  percentage drawdown and the Sharpe ratio were scaled by a fixed 10,000 USDT, so a
  -$5,000 day at BTC = $100,000 read as -50%; it is -5% now. The Sharpe ratio is
  `mean / stdev * sqrt(365)` of the daily returns (sample standard deviation; the
  strategies table used the population one and no annualization).
  - Dashboard strategies table: "Max Drawdown ($)" is replaced by "Worst trade" (the
    worst single-day return) and "Max drawdown" (largest fall of the compounded equity
    curve), both in percent. The backtesting page shows "Max drawdown" in percent.
    The models table shows "Max drawdown" in percent.
  - API: `/api/predictions/strategies` returns `worst_trade_pct` and
    `max_drawdown_pct` instead of `max_drawdown`; `/api/backtesting/metrics` returns
    `max_drawdown_pct` instead of `max_drawdown`; `/models/metrics` no longer returns
    the dollar `max_drawdown` (`max_drawdown_pct` stays, now on the equity curve of
    returns). The `capital` argument and `DEFAULT_CAPITAL` of `shared.utils` are gone.
  - The strategies tables state each strategy's assumptions: shorting is not possible
    on Binance spot and funding is not modeled, the fee is charged every day, and the
    stop-loss acts on closes because no intraday data is stored.
  - A day with no positive `price_at_prediction` has no return and is left out of the
    risk figures; with fewer than 2 returns, or returns that do not vary, the Sharpe
    ratio is undefined (N/A in the models table, 0.00 in the strategies tables).
- The models page and `/models/metrics` show one row per model family, not one per
  model row (#178). The trainer saves a new `linear_v<N>` row every day and each made
  one prediction, so per-row accuracy was 0% or 100%, the Sharpe ratio needed 2 points
  and the page ran 11 queries per row (about 4,400 queries and 3.7 s at 365 rows; now
  6 queries, whatever the number of rows). A row is now one (symbol, family,
  timeframe), family being the name without `_v<N>` (`model_family`): counts,
  accuracy, MAPE, PnL, win rate, Sharpe, drawdown and baselines cover the predictions
  of all its versions in `predicted_for` order. Every model row stays in the database
  with its version and `train_to`; nothing is deleted and there is no migration.
  - `/models/metrics` `models[]`: `name` is the family (`linear`, not `linear_v1`);
    `id` and `version` are those of the active version, else the newest;
    `is_active` is true when any version is active; `trained_at` is the latest
    training; `is_replay` is true only when every version of the row is simulated.
    New fields: `versions_count`, `first_train_to`, `last_train_to`. `daily_pnl` is
    keyed by family name and runs over all its versions.
  - `source=live|replay|all` filters the versions and the predictions that make up
    each row, so a replay version counts in the row only under `replay` or `all`.
  - The page shows the number of versions and their `train_to` range under the name.
- The predictor now runs right after the daily close (#175): `fetch-price` at 00:05 UTC
  (`5 0 * * *`) and `daily` at 00:10 UTC (`10 0 * * *`) instead of 06:00 and 07:00. The
  prediction used to be saved 7 hours after the close it is anchored to, so the recorded
  PnL assumed a price nobody could trade at. The predictor exits 1 and saves nothing when
  the last closed bar is older than `max_bar_age_hours` (new setting, default 2).
  **Deploy note:** change both cron schedules in the Railway dashboard before merging,
  because a 07:00 run now exits 1.
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
- The daily and weekly predictors, evaluators and trainers and the backtest cron
  took "today" from the container's time zone (`America/Mexico_City`, UTC-6) while
  bars are dated in UTC, so a run between 00:00 and 06:00 UTC stored its prediction
  one day early. Every job now uses `shared.utils.utc_today()` (#173).
- The daily and weekly predictors and trainers now refuse a series whose last bar
  is not dated yesterday (UTC) or that skips a day: they exit 1, name the missing
  dates and save no prediction and no model. Before, a missed `fetch-price` run
  produced a 2-day move scored as a 1-day prediction (#174).

### Added

- Dev Standards Compliance hardening: container healthcheck, pinned base
  image, self-documented Makefile, `mypy --strict` on `shared/`, enforced
  coverage gate, secret scanning, LICENSE, CHANGELOG, and accessibility
  glyphs for PnL indicators.

### Removed

- The LSTM, ARIMA and XGBoost models and the `tensorflow-cpu`, `xgboost` and
  `statsmodels` dependencies (#184, step 1). `LinearRegressionModel` is the only model:
  it is the benchmark any later model has to beat after fees. `--model` of
  `scripts/backtest.py` accepts only `linear` (anything else exits 2), and
  `deserialize_model` raises `RuntimeError` for a stored model that is not linear. All
  production models were `linear_v1`, so no data migration is needed. The code stays in
  git history.
- With one model, the machinery that chose among several (#184, step 2; supersedes
  #159): `train_all_models`, `scripts/train_all_models.py`, `split_train_validation`,
  `calculate_mape`, `model_registry`, `train_single_model`, the multi-model prediction
  mode (`--multi-model`, `get_active_models`, `_predict_multi_model`) and its US-025
  tests. The predictor loads the one active `1d` model (`get_active_model`) and no
  longer parses command-line arguments, so a leftover `--multi-model` in a start
  command is ignored. `build_model` stays in `workers/daily/models/factory.py` because
  the backtest CLI takes its `--model` choices from it. The database schema is
  unchanged, so it still allows several model families.

- The weekly worker (`workers/weekly/`, `railway.weekly.toml`), the `weekly-predictor`
  Railway service, the Weekly dashboard tab and the `1w` timeframe (#183). At 52
  predictions a year a 55% hit rate cannot be told from 50% for about 12 years, and
  production had 0 evaluated weekly predictions. `timeframe` accepts only `1d` in the
  API (`1w` and `1h` answer 422) and in the database: migration `e2b8f4a6c1d7` deletes
  the `1w` models and predictions (and any `1h` rows) and narrows the CHECK constraints
  `valid_timeframe_values` and `valid_model_timeframe_values` to `('1d')`; its
  downgrade restores the constraints, not the rows. `required_training_days` and
  `fetch_training_data` lost their `horizon_days` argument. `weekly-predictor` must be
  deleted or paused in Railway before this migration is deployed. Older entries keep
  describing the weekly worker as it was.

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
