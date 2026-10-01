# Implementation Plan: Baseline Comparison and Walk-Forward Backtest

**Spec**: [baselines-and-walk-forward-backtest.md](baselines-and-walk-forward-backtest.md)
**Issues**: #105, #106 (one PR)
**Created**: 2026-09-30
**Status**: completed

## Components

### 1. Baselines library (#105)
- **Purpose**: pure functions that score always-up, persistence and buy-and-hold on a list
  of `EvaluatedDay`, and report edge, `n_days` and a binomial p-value. `None` (not 0) when
  there are no days.
- **Files**: `shared/shared/baselines.py`, `shared/tests/test_baselines.py`
- **Effort**: S

### 2. Model factory (#106 parity)
- **Purpose**: `build_model(name, window_days, n_features)` as the single place that
  instantiates model classes (ARIMA `order=(5,1,0)`, Linear `n_features`, lazy imports for
  xgboost/lstm/arima). `trainer.train_single_model` switches to it, so production and
  backtest cannot diverge.
- **Files**: `workers/daily/models/factory.py`, `workers/daily/trainer.py`,
  `workers/daily/tests/test_model_factory.py`
- **Effort**: S

### 3. `evaluation_slice` migration (#106)
- **Purpose**: nullable `backtest_results.evaluation_slice` with CHECK
  (`validation`/`test`). Legacy rows stay `NULL`.
- **Files**: `shared/shared/db/models.py`, `shared/alembic/versions/<rev>_add_evaluation_slice.py`,
  migration test in `shared/tests/`
- **Effort**: XS

### 4. Walk-forward engine (#106)
- **Purpose**: load the BTCUSDT daily series once (same aggregation as
  `trainer.fetch_training_data`), slice in memory per day, train every N days with
  `build_training_set` + `build_model`, predict with `build_prediction_features` +
  `price_from_return`, seed everything, label slices, compute `pnl_*` with
  `shared.utils`, store rows. Precondition check (earliest allowed start) before any write.
- **Files**: `scripts/backtest_engine.py`, `scripts/tests/test_backtest_engine.py`,
  `scripts/tests/test_backtest_models.py`, `scripts/tests/conftest.py` (synthetic
  deterministic series fixture, module-scoped)
- **Effort**: L

### 5. Report and CLI (#105 + #106)
- **Purpose**: `backtest_report.py` reads rows plus `previous_close` (close of D-2 from
  `prices`), builds `EvaluatedDay`s per slice, calls the baselines and formats: headline =
  test slice, separate labelled validation section, legacy `NULL` rows as "unsplit".
  `scripts/backtest.py` gets `--model --seed --retrain-every --test-start-date` and a
  `--training-window` default from `settings.training_window_days`.
- **Files**: `scripts/backtest_report.py`, `scripts/backtest.py`,
  `scripts/tests/test_backtest_report.py`, `scripts/tests/test_backtest_cli.py`
- **Effort**: M

### 6. Retire the old path, docs, changelog
- **Purpose**: delete `scripts/backtest_utils.py` and rewrite/remove the tests that pinned
  its price-level behaviour (`test_backtest_utils.py`, `test_backtest_gherkin.py`,
  `test_backtest_integration.py`); update `docs/BACKTESTING.md` (flags, slices, retrain
  frequency, baseline definitions, significance caveat) and `CHANGELOG.md`.
- **Files**: `scripts/backtest_utils.py` (delete), the three test files above,
  `docs/BACKTESTING.md`, `CHANGELOG.md`
- **Effort**: S

## Dependencies

### Build Order
1. Baselines library (independent, pure) — can be built first
2. Model factory + trainer refactor (independent of 1)
3. Migration (independent; needed by 4)
4. Engine (depends on 2, 3)
5. Report/CLI (depends on 1, 3, 4)
6. Retire old path + docs (depends on 5)

### External Dependencies
- None at runtime (p-value implemented with `math.lgamma`); scipy 1.18.1 is already in the
  container and is used only as a test oracle.
- Dev database already holds 3,302 BTCUSDT daily rows (2017-08-17 → 2026-08-31), enough
  for a real end-to-end run.

## Risks & Assumptions

### Risks
- **Existing backtest tests pin the old behaviour** (price-level windows, `backtest_utils`
  imports). Mitigation: map each old scenario to the new engine tests before deleting, so
  no coverage is lost; run `pytest scripts/tests` after each step.
- **Performance budget (< 60 s for 365 days, Linear, retrain every day)** is an estimate.
  Mitigation: build the engine with in-memory slicing from the start; measure on the dev
  data in Milestone 3 and adjust the budget in the spec if the number is wrong.
- **Non-linear models may not accept the return features** as-is (they were disabled in
  the reboot, #124). Mitigation: the generic path is tested with Linear; xgboost/lstm/arima
  rows are `non_linear` and may need small, documented adaptations in the engine only
  (never in production code); anything bigger is left to #124 and recorded in the PR.
- **Reproducibility of LSTM/XGBoost** (threading, TF ops). Mitigation: seed `random`,
  `numpy`, TF, and set deterministic ops where available; if exact equality is not
  achievable, document it for that model and keep the exact-equality test for Linear.
- **p-value misread as proof.** Mitigation: label it as an approximation in the report
  and in `docs/BACKTESTING.md`.

### Assumptions
- The stored daily bars are contiguous, so `D-1` and `D-2` closes exist for evaluated days;
  a gap makes that day skipped and counted (the engine already logs skip reasons).
- Calendar-day indexing: "retrain every N days" counts predicted days, not rows.
- Changing the default window from 30 to 21 days is acceptable (it is the production value
  and the point of parity).

## Milestones

- [x] M1: `baselines.py` complete; the 5 #105 scenarios pass; mutation score > 85% on it
- [x] M2: `build_model` shared by trainer and backtest; existing trainer tests unchanged
- [x] M3: engine backtests Linear for 365 days on dev data, reproducible, within the time
  budget (number recorded)
- [x] M4: report shows test-slice headline + baselines + edge; CLI smoke test passes
- [x] M5: old path removed, docs/changelog updated, full `pytest` green, coverage ≥ 90%,
  ruff clean, `pytest --run-non-linear -k backtest` run and its result recorded

## Effort Estimate

**Total Estimated Days**: 4–5 days

| Phase | Effort |
|-------|--------|
| Baselines + factory + migration | 1 day |
| Engine (+ reproducibility, non-linear) | 1.5–2 days |
| Report + CLI | 1 day |
| Retire old path, docs, mutation run, polish | 0.5–1 day |

## Tasks

**Slicing strategy**: Mixed. Baselines, the model factory and the migration are shared
blocking pieces that several scenarios need (the engine needs the factory and the column,
the report needs the baselines), so they are built first as a small horizontal foundation.
Everything downstream is sliced vertically, riskiest first: the end-to-end Linear
walk-forward, which proves production parity, comes before the add-ons.

Every task follows TDD (failing Gherkin-mapped test first) and runs inside
`docker compose exec api`. Issues #105 and #106 already exist, so no new GitHub issues are
created; the PR closes both.

### Foundation (Build First)

- [x] **T1 — Baselines library** (#105)
  - **Acceptance**: all 5 #105 scenarios pass; `None` (not 0) with zero days; persistence
    skips `previous_close=None` and reports its own `n_days`; p-value (stdlib, log space) equals
    `scipy.stats.binomtest(..., alternative="greater")` in tests; no new runtime dependency.
  - **Files**: `shared/shared/baselines.py`, `shared/tests/test_baselines.py`,
  - **Tests**: the 5 scenarios (Outline parametrized `UUDU`/`UDUD`), 200-day coverage,
    100-day edge, empty input, tie rule (`actual >= price_at_prediction` is UP)
  - **Effort**: S

- [x] **T2 — Model factory shared with the trainer** (#106 parity)
  - **Acceptance**: `build_model(name, window_days, n_features)` returns the same
    configured instances `train_single_model` built before (ARIMA `order=(5,1,0)`, Linear
    `n_features`); unknown name raises `ValueError`; xgboost/lstm/arima are imported lazily;
    existing trainer tests pass unchanged.
  - **Files**: `workers/daily/models/factory.py`, `workers/daily/trainer.py`,
    `workers/daily/tests/test_model_factory.py`
  - **Tests**: per-name instance type/params, lazy-import check (Linear-only call does not
    import TensorFlow), regression run of `workers/daily/tests/test_trainer.py`
  - **Effort**: S

- [x] **T3 — `evaluation_slice` column + migration** (#106)
  - **Acceptance**: nullable `evaluation_slice` with CHECK in (`validation`,`test`);
    `alembic upgrade head` and `downgrade -1` both work; legacy rows keep `NULL`;
    invalid value rejected by the DB.
  - **Files**: `shared/shared/db/models.py`, `shared/alembic/versions/<rev>_add_evaluation_slice.py`,
    `shared/tests/test_backtest_slice_migration.py`
  - **Tests**: up/down, CHECK violation, `NULL` allowed
  - **Effort**: XS

### Slice 1 — Linear walk-forward, end to end, production parity (riskiest)

- [x] **T4 — Engine core + minimal CLI path** (#106)
  - **Acceptance**: `python scripts/backtest.py --start-date … --end-date …` (Linear)
    stores one row per day with `model_params` (`model_name`, `window_days`, `target`,
    `train_to`); training data for D has latest observation ≤ D-1 (2024-06-10 → ≤ 2024-06-09);
    spies prove `build_training_set`, `build_prediction_features`, `build_model` are called
    and `scripts/` has no feature/model code of its own; a start earlier than first loaded
    day + `required_training_days(window)` aborts before writing, naming the earliest allowed
    start date, the first loaded day and the window; series loaded with one query.
  - **Files**: `scripts/backtest_engine.py`, `scripts/backtest.py`,
    `scripts/tests/conftest.py` (synthetic deterministic series, module-scoped),
    `scripts/tests/test_backtest_engine.py`
  - **Tests**: #106 scenarios "No future data reaches training", "Production code is used",
    "Insufficient history fails clearly" (asserts zero rows), Linear row of the
    "Every model type" Outline (2024-01-01 → 2024-03-31, one row per day)
  - **Effort**: L

### Slice 2 — Reproducibility and retrain frequency

- [x] **T5 — `--seed` and `--retrain-every`** (#106)
  - **Acceptance**: same seed ⇒ identical stored `predicted_price` across two runs;
    `retrain_every=N` retrains on days 0, N, 2N… and reuses the model in between while
    features are still rebuilt from data ≤ D-1; `seed` and `retrain_every` stored in every
    row's `model_params`; `--training-window` defaults to `settings.training_window_days`.
  - **Files**: `scripts/backtest_engine.py`, `scripts/backtest.py`,
    `scripts/tests/test_backtest_engine.py`
  - **Tests**: "Results are reproducible" scenario, retrain-count spy, params stored,
    default window from settings
  - **Effort**: S

### Slice 3 — Out-of-sample slices and baseline report (#105 meets #106)

- [x] **T6 — Validation/test split and report with baselines**
  - **Acceptance**: `--test-start-date` (default: first day of the last 30% of the range)
    labels rows `validation`/`test`; the report's headline (accuracy, `pnl_simple`, always-up,
    persistence, buy-and-hold, `n_days`, edge, p-value) uses only `test` rows; validation is a
    separate labelled section; legacy `NULL` rows are shown as "unsplit"; `previous_close`
    comes from `prices` (D-2) so persistence covers every evaluated day; an empty slice prints
    "unavailable", not 0; the report is printed at the end of the CLI run.
  - **Files**: `scripts/backtest_report.py`, `scripts/backtest.py`, `scripts/backtest_engine.py`,
    `scripts/tests/test_backtest_report.py`, `scripts/tests/test_backtest_cli.py`
  - **Tests**: "Metrics are computed only on the out-of-sample period", default split,
    unsplit legacy rows, CLI smoke test (exit 0, report contains baseline and edge lines)
  - **Effort**: M

### Slice 4 — Non-linear models through the generic path

- [x] **T7 — xgboost / lstm / arima backtests** (#106)
  - **Acceptance**: the "Every model type" Outline passes for `xgboost`, `lstm`, `arima`
    under `--run-non-linear` (one row per day for 2024-01-01 → 2024-03-31); any adaptation
    lives in the engine, never in production code; whatever cannot be made to work is
    listed in the PR description and left to #124; exact-equality reproducibility is only
    asserted for Linear, and any non-determinism in the others is documented.
  - **Files**: `scripts/tests/test_backtest_models.py`, `scripts/backtest_engine.py` (only if needed)
  - **Tests**: Outline rows marked `non_linear`; `pytest --run-non-linear -k backtest`
  - **Effort**: M
  - **Outcome**: `arima` passes; `xgboost` and `lstm` are strict xfails because the models
    still reject the return features (#124), the same failure the daily trainer has.

### Slice 5 — Retire the old path and close out

- [x] **T8 — Remove `backtest_utils.py`, docs, changelog, quality gates**
  - **Acceptance**: `scripts/backtest_utils.py` deleted and `grep -rn "LinearRegressionModel(" scripts/`
    is empty; old tests (`test_backtest_utils.py`, `test_backtest_gherkin.py`,
    `test_backtest_integration.py`) rewritten or removed with each old scenario mapped to a
    new test in the PR description; `docs/BACKTESTING.md` documents the new flags, slices,
    retrain frequency, baseline definitions and the significance caveat; `CHANGELOG.md` updated;
    timed 365-day Linear run on the dev data recorded (budget < 60 s, spec revised if wrong);
    Cosmic Ray on `baselines.py` > 85%; full `pytest` green, coverage ≥ 90%, ruff clean; spec
    `status: completed` with the PR linked.
  - **Files**: `scripts/backtest_utils.py` (delete), the three old test files,
    `docs/BACKTESTING.md`, `CHANGELOG.md`, `specs/baselines-and-walk-forward-backtest.md`
  - **Tests**: full suite, `ruff check`, mutation run, one `slow`-marked timing test
  - **Effort**: S

### Order and dependencies

```
T1 ─────────────┐
T2 ──┐          ├─▶ T6 ─▶ T7 ─▶ T8
T3 ──┴─▶ T4 ─▶ T5 ┘
```

T1–T3 are independent and can be done in any order. T4 needs T2 and T3, T5 needs T4,
T6 needs T1, T3, T5, T7 needs T4, and T8 comes last. Suggested commit series: one commit
per task, so #105 (T1, T6 report part) and #106 are both traceable in the PR.
