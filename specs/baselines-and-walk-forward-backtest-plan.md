# Implementation Plan: Baseline Comparison and Walk-Forward Backtest

**Spec**: [baselines-and-walk-forward-backtest.md](baselines-and-walk-forward-backtest.md) (#105, #106, one PR #136). **Status**: completed.

Build order and files:

1. Baselines library: `shared/shared/baselines.py`, `shared/tests/test_baselines.py`.
2. Model factory shared by the trainer and the backtest: `workers/daily/models/factory.py`.
3. `evaluation_slice` migration: `BacktestResult.evaluation_slice` and an Alembic revision.
4. Walk-forward engine: `scripts/backtest_engine.py` (depends on 2 and 3).
5. Report and CLI: `scripts/backtest_report.py`, `scripts/backtest.py` (depends on 1, 3 and 4).
6. Retire the old path: delete `scripts/backtest_utils.py` and the tests that pinned its price-level behaviour, mapping each old scenario to a new test first; update `docs/BACKTESTING.md` and `CHANGELOG.md`.

Risks the plan named: the old backtest tests pinned the old behaviour (mitigation: map scenarios before deleting); the 60 s budget was an estimate (mitigation: in-memory slicing from the start, measure on dev data); reading the p-value as proof (mitigation: label it an approximation); the non-linear models might reject the return features (left to #124, later removed in #184).
