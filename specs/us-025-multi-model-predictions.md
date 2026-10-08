---
title: US-025 Multi-Model Predictions (Parallel)
status: removed
created: 2026-05-19
updated: 2026-10-06
issue: "#27, removed in #184"
---

# US-025: Multi-Model Predictions (Parallel)

**Decision (2026-05):** the predictor accepted a `--multi-model` flag and generated one prediction per active model, so models could be compared side by side in production. A failing model was logged and skipped; `UNIQUE (predicted_for, model_id)` kept re-runs idempotent; the evaluator already scored every prediction of a day.

**Removed in #184**, together with LSTM, XGBoost and ARIMA: the linear model is the only model, the predictor uses the one active `1d` model, and there is no multi-model mode or best-of-several selection (`CLAUDE.md`, Design Decision 3). The code lives in git history.

What remains of it: the unique constraint on `(predicted_for, timeframe, model_id)` and the evaluator scoring every pending prediction. The implementation plan was deleted because every step in it described the removed flag.
