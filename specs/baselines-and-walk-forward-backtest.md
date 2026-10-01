---
title: Baseline Comparison and Walk-Forward Backtest
status: completed
created: 2026-09-30
updated: 2026-09-30
issue: "#105, #106"
---

# Baseline Comparison and Walk-Forward Backtest

## Objective

Make every reported result honest: compare each model against trivial baselines
(always-up, persistence, buy-and-hold) with its sample size and a significance
measure (#105), and produce those results from a walk-forward backtest that runs
the exact production feature and model code with no lookahead and with headline
metrics computed only on out-of-sample data (#106). Both ship in one PR because
the backtest report is the first consumer of the baselines.

## Context

- The reboot (#99–#109) rebuilds the evidence that the predictor adds value. Spike
  reference values for BTC daily 2017-2026: **always-up direction accuracy 51.1%**,
  **direction persistence 46.5%**. A model has to beat these to mean anything.
- #104 (merged) made the Linear model train on log returns through the single
  feature builder `shared/shared/features.py` (`build_training_set`,
  `build_prediction_features`, `price_from_return`).
- `scripts/backtest_utils.py` has drifted from production: it hard-codes
  `LinearRegressionModel`, builds **price-level** windows by hand
  (`generate_prediction`), runs one SQL query per day (`fetch_training_data`) and
  defaults to a 30-day window while production uses `settings.training_window_days`
  (21). Its numbers do not describe what `workers/daily/` would do.
- Baselines exist only as prose in `docs/BACKTESTING.md`.
- Existing conventions this spec reuses:
  - Direction rule (`workers/daily/evaluator.py::calculate_direction_correct`):
    predicted UP iff `predicted_price > price_at_prediction`; actual UP iff
    `actual_price >= price_at_prediction` (flat counts as UP).
  - PnL is per 1 BTC in USDT (`shared/shared/utils.py::calculate_pnl*`).
  - Production trains on **every stored BTCUSDT daily row** (expanding window) and
    needs `required_training_days(window)` rows (`workers/daily/trainer.py`).
- Scope decisions agreed with the user (2026-09-30):
  - The backtest is **model-generic** (any `BaseModel` by name) with Linear fully
    tested. The xgboost/lstm/arima scenarios are marked `non_linear` and run with
    `--run-non-linear` until #124 re-enables those models.
  - Baselines are surfaced in the **library and the backtest report** only.
    Dashboard/API exposure is left to #107.

## Requirements

### Functional Requirements

**Baselines (#105)**

- [x] `shared/shared/baselines.py` computes, from a list of evaluated days, the
  direction accuracy of **always-up** and **persistence**, and the PnL of
  always-up (== buy-and-hold) and persistence under the simple strategy.
- [x] Baselines are computed on exactly the days the model was evaluated on (same
  list in, same count out). The result carries `n_days`.
- [x] Persistence predicts UP for day D iff `price_at_prediction >= previous_close`
  (close of D-2). Days with `previous_close = None` are excluded from persistence
  only, and `persistence.n_days` reports the count actually scored.
- [x] Buy-and-hold PnL for the period = last `actual_price` − first
  `price_at_prediction` (1 BTC, USDT).
- [x] Edge reporting: `edge = model_accuracy − max(always_up, persistence)`, the
  sample size `n_days`, and a one-sided binomial-test `p_value` (stdlib implementation, checked against scipy in tests)
  (H0: model hit rate ≤ best baseline accuracy) plus `significant`
  (`p_value < 0.05`).
- [x] With zero evaluated days, baselines, edge and p-value are `None` ("unavailable"),
  never `0`.

**Walk-forward backtest (#106)**

- [x] `scripts/backtest.py` predicts each date D with data **dated ≤ D-1 only**
  (expanding window, like production), for any model name in
  `{linear, xgboost, lstm, arima}`.
- [x] The backtest imports and calls the production code: `build_training_set` /
  `build_prediction_features` / `price_from_return` from `shared.features`, and the
  model classes through a new shared factory `workers/daily/models/factory.py`
  (`build_model(name, window_days, n_features)`), which `trainer.train_single_model`
  also uses (single source of model construction, including ARIMA's `order`).
- [x] The series is loaded once (one query, same aggregation as
  `trainer.fetch_training_data`) and sliced in memory per day.
- [x] One `backtest_results` row per predicted day, with `model_params` holding
  `model_name`, `symbol`, `window_days`, `seed`, `retrain_every`, `test_start_date`,
  `target`, `train_from`, `train_to`, `training_samples`.
- [x] `--retrain-every N` (default 1): the model is retrained every N days and
  reused in between; features are always rebuilt from data ≤ D-1. N is stored in
  every row and printed in the report.
- [x] `--seed` (default 42) seeds `random`, `numpy` and TensorFlow; two runs with the
  same seed store identical `predicted_price` values.
- [x] Validation/test split: `--test-start-date` (default: first day of the last 30%
  of the range). Rows get `evaluation_slice` = `validation` or `test` (new column,
  Alembic migration; legacy rows stay `NULL` = unsplit).
- [x] The report's **headline metrics use only `test` rows**; `validation` metrics are
  printed in a separate, labelled section. Both sections include the baselines and
  edge from #105.
- [x] `--training-window` defaults to `settings.training_window_days`.
- [x] If `start_date` < first loaded day + `required_training_days(window)`, the run
  aborts **before** writing anything with a message naming the earliest allowed
  start date, the first loaded day and the window.
- [x] `docs/BACKTESTING.md` and `CHANGELOG.md` updated.

### Non-Functional Requirements

- [x] Performance: a Linear backtest over 365 predicted days with `--retrain-every 1`
  completes in < 60 s inside the `api` container (measured: 366 days on the real dev data took 8.1 s;
  the 365-day synthetic-series test is `slow`-marked).
- [x] Reproducibility: same data + same seed + same parameters ⇒ identical stored
  predictions (exact equality on the stored `NUMERIC(15,2)` values).
- [x] Quality gates: ruff + type-check green, total coverage ≥ 90%, new modules ≥ 95%.
- [x] Idempotency/safety: a failed precondition (insufficient history, bad
  arguments) writes no rows.

## Architecture

### Components

```
shared/shared/baselines.py          NEW   pure functions: baselines, edge, p-value
workers/daily/models/factory.py     NEW   build_model(name, window_days, n_features)
workers/daily/trainer.py            EDIT  train_single_model uses build_model
scripts/backtest_engine.py          NEW   walk-forward loop (replaces backtest_utils)
scripts/backtest_report.py          NEW   loads rows + prices, calls baselines, formats report
scripts/backtest.py                 EDIT  CLI: --model --seed --retrain-every --test-start-date
scripts/backtest_utils.py           DEL   fetch_training_data/generate_prediction replaced
shared/shared/db/models.py          EDIT  BacktestResult.evaluation_slice
shared/alembic/versions/*           NEW   add evaluation_slice (nullable, CHECK in 'validation','test')
docs/BACKTESTING.md, CHANGELOG.md   EDIT
```

Data flow of one run:

```
prices (BTCUSDT daily) ──load once──▶ DailySeries
for D in [start..end]:
    history = series[dates ≤ D-1]                       # no lookahead, by slicing
    if (D - first_test_or_start) % retrain_every == 0:
        fs = build_training_set(history…, window, horizon=1)   # production builder
        model = build_model(name, window, feature_count(window)); model.train(fs.X, fs.y)
    x = build_prediction_features(history…, window)             # production builder
    predicted = price_from_return(history.closes[-1], model.predict(x))
    store BacktestResult(slice = validation|test, pnl_* via shared.utils)
report(run_id): rows → EvaluatedDay[] → baselines.evaluate(...) per slice
```

### Data Model

```python
@dataclass(frozen=True)
class EvaluatedDay:
    predicted_for: date
    previous_close: Decimal | None   # close of D-2 (None if not available)
    price_at_prediction: Decimal     # close of D-1
    actual_price: Decimal            # close of D
    predicted_price: Decimal | None  # None when scoring baselines only

@dataclass(frozen=True)
class BaselineReport:
    n_days: int
    always_up_accuracy: float | None
    persistence_accuracy: float | None
    persistence_n_days: int
    always_up_pnl: Decimal | None      # equals buy_and_hold_pnl
    persistence_pnl: Decimal | None
    buy_and_hold_pnl: Decimal | None
    best_baseline: str | None          # "always_up" | "persistence"
    model_accuracy: float | None
    edge: float | None
    p_value: float | None
    significant: bool | None
```

`backtest_results.evaluation_slice VARCHAR(10) NULL CHECK (evaluation_slice IN ('validation','test'))`.

### External Dependencies

- None at runtime: the one-sided binomial p-value is computed in log space with the
  standard library (`math.lgamma`), so `shared` gains no dependency (scipy would bloat
  the api/fetch images). `scipy.stats.binomtest` is used only in tests as the oracle.
- No new services. Runs inside the `api` container.

## User Stories

Authoritative text and Gherkin live in the issues:

- #105 — *Compare every model against trivial baselines* (5 scenarios)
- #106 — *Walk-forward backtest with production-code parity and out-of-sample metrics* (6 scenarios)

Every scenario maps to at least one automated test (see Testing Strategy).

## Testing Strategy

All commands run inside the container: `docker compose exec api pytest …`.

### Gherkin → test mapping

| Issue | Scenario | Test (file) |
|-------|----------|-------------|
| #105 | Baselines over the same evaluated days | `shared/tests/test_baselines.py::test_baselines_cover_exactly_the_evaluated_days` (200 days) |
| #105 | Baseline accuracy matches hand-checked series (Outline: `UUDU`/always_up → 0.75, `UDUD`/persistence → 0.0) | `shared/tests/test_baselines.py::test_baseline_accuracy_hand_checked` (parametrized) |
| #105 | Buy-and-hold PnL for the same period | `shared/tests/test_baselines.py::test_buy_and_hold_pnl_between_two_dates` |
| #105 | Edge reported with sample size and significance | `shared/tests/test_baselines.py::test_edge_reports_sample_size_and_p_value` (100 days, p-value checked against `scipy.stats.binomtest`) |
| #105 | Zero evaluated days → unavailable | `shared/tests/test_baselines.py::test_no_evaluated_days_is_unavailable_not_zero` |
| #106 | No future data reaches training | `scripts/tests/test_backtest_engine.py::test_training_set_ends_before_predicted_day` (2024-06-10 → latest 2024-06-09) |
| #106 | Production feature and prediction code is used | `scripts/tests/test_backtest_engine.py::test_backtest_calls_production_builders_and_factory` (spies on `build_training_set`, `build_prediction_features`, `build_model`; identity check on imports) |
| #106 | Every model type can be backtested (Outline) | `scripts/tests/test_backtest_models.py::test_backtest_stores_one_result_per_day[linear]`; `[xgboost]`, `[lstm]`, `[arima]` marked `non_linear` |
| #106 | Results are reproducible | `scripts/tests/test_backtest_engine.py::test_same_seed_same_predictions` |
| #106 | Metrics only on out-of-sample period | `scripts/tests/test_backtest_report.py::test_headline_metrics_use_only_test_slice` |
| #106 | Insufficient history fails clearly | `scripts/tests/test_backtest_engine.py::test_start_before_enough_history_names_earliest_date` (also asserts zero rows written) |

Extra tests that pin behaviour this spec adds: `retrain_every` reuse and storage,
`build_model` factory parity with `trainer.train_single_model`, migration up/down,
persistence skipping `previous_close=None`, legacy `NULL` slice rows reported as
"unsplit".

### Unit Tests

`shared/baselines.py` (pure, table-driven), `build_model`, report formatting.

### Integration Tests

Engine against the test Postgres with a synthetic deterministic price series
(module-scoped fixture, like the existing cached price datasets), covering the
loop, slices, retrain frequency and the precondition failure.

### E2E Tests

CLI smoke test: `python scripts/backtest.py …` on the seeded fixture exits 0 and the
report contains the baseline and edge lines.

### Performance Tests

One timed run of the 365-day Linear backtest (marked `slow`), asserting the budget.

### Mutation Testing

Run Cosmic Ray on `shared/shared/baselines.py` (target > 85%, as in the project goal).

## Boundaries & Constraints

### In Scope

- Baselines library, significance test, backtest engine/CLI/report, model factory,
  `evaluation_slice` migration, docs and changelog.
- Linear fully covered; xgboost/lstm/arima supported by the generic path and tested
  under `--run-non-linear`.

### Out of Scope

- Dashboard/API exposure of baselines (#107) and the final results page (#109).
- Re-adapting LSTM/XGBoost/ARIMA to the reboot data (#124).
- Automated hyperparameter search (the split and labelling make leakage structurally
  impossible to report; no tuner is built here).
- Rolling-window mode (production is expanding-window; parity first).
- Multi-asset backtests (`BTCUSDT` only, via `DEFAULT_SYMBOL`).
- Transaction-cost modelling beyond the existing `pnl_realistic`.

### Technical Constraints

- Python 3.13, SQLAlchemy 2.0, Alembic for every schema change; run everything in
  containers (`docker compose exec api …`).
- Model code stays lazily imported (TensorFlow/XGBoost/statsmodels must not load for
  Linear-only runs).
- The significance test is an approximation: it treats the best baseline's accuracy
  as a fixed null probability and does not account for choosing the best of two
  baselines. It is documented as such in `docs/BACKTESTING.md`.
- Persistence for fixture series: in `UDUD` the first day has no preceding
  direction, so persistence is scored on 3 days (accuracy 0.0 = 0/3); always-up
  `UUDU` is scored on 4 (3/4). In real runs `previous_close` always comes from
  `prices`, so persistence covers every evaluated day.

## Success Criteria

- [x] All 11 Gherkin scenarios (5 from #105, 6 from #106) have passing automated
  tests. Of the 3 non-linear Outline rows, `arima` passes with `--run-non-linear`;
  `xgboost` and `lstm` are strict xfails: those models still reject the return
  features the production builder gives them (`X must have N features`), which
  #124 fixes. The backtest reproduces that production failure instead of working
  around it, and now raises when every day fails to train.
- [x] `docker compose exec api pytest` green with total coverage ≥ 90%; ruff clean.
- [x] A real run, e.g. `scripts/backtest.py --start-date=2024-01-01 --end-date=2024-12-31`
  against loaded Binance history, prints test-slice accuracy, always-up and
  persistence accuracy, buy-and-hold PnL, `n_days`, edge and p-value, and the same
  command twice yields identical stored predictions.
- [x] `scripts/backtest_utils.py` no longer contains its own feature or model code;
  grep for `LinearRegressionModel(` under `scripts/` returns nothing.
- [x] `docs/BACKTESTING.md` documents the new flags, the slices, the retrain
  frequency and the baseline definitions.

## Implementation Plan

See `specs/baselines-and-walk-forward-backtest-plan.md`. Delivered in PR #136 (merged 2026-10-01).
Delivered in the order baselines → model factory → migration → engine → seed/retrain →
split + report → non-linear models → docs, one commit per task.

## Changelog

<!-- Empty until this spec reaches `completed` and is modified again. -->
