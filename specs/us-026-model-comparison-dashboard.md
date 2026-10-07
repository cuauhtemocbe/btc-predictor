---
title: US-026 - Model Comparison Dashboard
status: completed
created: 2026-05-19
updated: 2026-10-06
issue: "#28"
---

# US-026: Model Comparison Dashboard

**Decision (2026-05):** a page `GET /models` and a JSON endpoint `GET /api/models/metrics` compare models by evaluated predictions: accuracy (direction correct), MAPE, total PnL, win rate, Sharpe ratio (annualized, `sqrt(365)`) and max drawdown, plus a cumulative PnL line chart (Chart.js) with one line per model, a date range filter (`start`, `end`) and a highlight on the model with the highest total PnL. No schema change: the page reads `models` and `predictions`. Server-side Jinja2, no JavaScript framework, aggregation in SQL instead of one query per model.

Left out on purpose: activating a model from the page (done by `scripts/activate_model.py`), table sorting, CSV export, real-time updates.

**What changed since:**

- A "model" is a family (`linear` for `linear_v1`, `linear_v2`, ...): one row per (symbol, family, timeframe) over the predictions of every version (#178), computed in `shared/shared/utils.py::get_all_models_metrics`.
- Sharpe ratio and max drawdown come from compounded returns, not from the dollar PnL (#177).
- Every metric sits next to the baselines (`shared/shared/baselines.py`), and the page filters by `symbol` and by `source=live|replay|all` (#176).
- LSTM, XGBoost and ARIMA are gone (#184), so the page compares the families that exist.

Tests: `api-service/tests/test_models_api.py`. Code: `api-service/api/routers/models.py`, `api-service/api/templates/models.html`. Plan: `us-026-model-comparison-dashboard-plan.md`.
