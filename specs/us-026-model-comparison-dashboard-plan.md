# Implementation Plan: US-026 Model Comparison Dashboard

**Spec**: [us-026-model-comparison-dashboard.md](us-026-model-comparison-dashboard.md) (issue #28). **Status**: completed.

Build order: metrics calculation (accuracy, MAPE, total PnL, win rate, Sharpe ratio, max drawdown, cumulative PnL series), then the router with `GET /models` and `GET /api/models/metrics`, then the Jinja2 template with the table, the Chart.js chart and the date filter, then empty-state handling and a link from the main dashboard.

Risks the plan named, with their mitigation: slow metrics over 4 models and 90 days (aggregate in SQL, not one query per model); Sharpe ratio complexity (simple formula on daily returns, checked against a manual calculation in a test); models with no predictions breaking the page (show "N/A"). It assumed the evaluator had filled `actual_price`, `error_pct` and `pnl_simulated`, and that Chart.js was reachable from Railway.

The metrics code now lives in `shared/shared/utils.py` and `shared/shared/returns.py`, not in a `shared/utils/metrics.py` module.
