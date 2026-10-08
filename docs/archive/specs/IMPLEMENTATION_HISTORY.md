# BTC Predictor: implementation history

Archive of the decisions of User Stories US-001 to US-024 (May 2026, spec-driven development, 10 iterations, GitHub issues #2 to #26). Their original spec files were removed from the repository and live in git history. Each row says what was decided and what replaced it since; for the current design read `CLAUDE.md` and the module-level `CLAUDE.md` files.

## Decisions by user story

| Story | Decision | Today |
|-------|----------|-------|
| US-001 shared package | Poetry workspace with a `shared` package; pydantic-settings for the environment; SQLAlchemy 2.0; `get_db()` as the FastAPI dependency | Same: `shared/shared/config.py`, `shared/shared/db/database.py` (the original docs cite `shared/btc_shared/`, a path that no longer exists) |
| US-002 prices table | `TIMESTAMPTZ`, UNIQUE on `timestamp` for idempotency, index on `timestamp`, Alembic | One daily row per symbol, UNIQUE on `(symbol, timestamp)`; model `Price` in `shared/shared/db/models.py` |
| US-003, US-004 price fetching | The Binance client hit HTTP 451 (geo-block) on Railway, so it moved to CoinGecko with exponential backoff on 429; hourly cron, idempotent through the UNIQUE constraint | CoinGecko was replaced by Binance Vision in #102, because it capped history at 30 days and had no volume. `fetch-price` is a daily cron (`5 0 * * *`): `workers/fetch_price/CLAUDE.md` |
| US-005 `GET /api/prices` | FastAPI async handler, CORS enabled | `api-service/api/routers/prices.py` |
| US-006 `BaseModel` | Abstract interface (`train`, `predict`, `serialize`, `deserialize`) so algorithms can be swapped; pickle for storage | Same interface: `workers/daily/models/base.py` |
| US-007 models table | `BYTEA` artifact, JSON params, `is_active`, training range | At most one active version per (symbol, family, timeframe), enforced by `ix_models_one_active_version_per_name_timeframe` |
| US-008 predictions table | Two-phase lifecycle: insert with NULL evaluation fields, update when evaluated; FK to `models` with CASCADE | Same; unique per `(predicted_for, timeframe, model_id)` |
| US-009 daily predictor | Load the active model, build features from recent prices, store the predicted price | Return features and `last close * exp(predicted return)`; refuses stale data (#174) and an old price anchor (#175) |
| US-010 daily evaluator | Settle the prediction against the actual price; error, percentage error, direction, PnL | Settles against the close of the bar it predicted and leaves it pending if that bar is missing; direction counts a flat day as UP |
| US-011, US-014 history and PnL endpoints | Newest first, with model name and version; PnL as a running sum | `api-service/api/routers/predictions.py`, with `symbol` and `source` filters |
| US-012 dashboard | Server-side Jinja2, no JavaScript framework, responsive CSS | Same, plus asset and `live`/`replay` filters |
| US-013 PnL | Long 1 BTC if predicted UP, otherwise cash; tests direction, not absolute accuracy | `shared/shared/utils.py::calculate_pnl` |
| US-015, US-016 Railway crons | `fetch-price` and `daily` as cron services; `daily` runs evaluator, trainer, predictor in order | Schedules `5 0 * * *` and `10 0 * * *`; start commands live in the Railway dashboard (`RAILWAY_MULTISTAGE_CONFIG.md`) |
| US-017 PnL strategies | Keep `pnl_simulated`; add `pnl_long_short`, `pnl_threshold` (trade only above 1%) and `pnl_realistic` (0.1% fees, 2% stop-loss) | Same four strategies, in `shared/shared/utils.py` |
| US-018 strategy comparison | Total PnL, win rate, drawdown, average win and loss, Sharpe ratio, cumulative chart per strategy | Risk figures come from compounded returns, not dollar PnL (#177) |
| US-019 backfill | Load 90+ days of history in batches, idempotent | Replaced by `scripts/load_binance_history.py` (#101), 9 years of daily bars |
| US-020 walk-forward backtest | Separate `backtest_results` table, `backtest_run_id` UUID per run, production model code reused, all four PnLs per day | Same table; the engine calls `shared.features` and the model factory (#106); `docs/BACKTESTING.md` |
| US-021 backtest dashboard | `GET /backtesting`: cumulative PnL chart, strategy table, date filter | `api-service/api/routers/backtesting.py` |
| US-022 weekly predictions | A `timeframe` column (`1d`, `1w`) with weekly predictions | Removed in #183: only `1d` is allowed |
| US-023 LSTM, XGBoost, ARIMA | Extra models behind `BaseModel` | Removed in #184 (the linear model is the benchmark any new model must beat); they stay in git history |
| US-024 multi-model training | Train every model, activate the best by validation MAPE, CLI scripts to list and activate | Removed in #184: one model, no ranking. `scripts/list_models.py` and `scripts/activate_model.py` remain |

## Cross-cutting decisions

- **Two-phase prediction lifecycle.** The predictor inserts first and the evaluator fills the result later, so a prediction exists the moment it is made.
- **Idempotent jobs.** UNIQUE constraints on prices and predictions make retries safe.
- **Abstract `BaseModel`.** The trainer, predictor and backtest only use the interface, so a model can change without touching them.
- **Container-first.** Development and tests run in Docker (`docker compose exec api ...`) for parity with production.

## Lessons

- Binance REST is geo-blocked from Railway (HTTP 451); only the `data.binance.vision` hosts are used.
- Small, deployable iterations and tests written with each story kept regressions out.
- Railway start commands diverged from the `railway.*.toml` files once (2026-08-09), so the dashboard is the source of truth.

Deployment and backtesting today: `RAILWAY_DEPLOYMENT.md`, `docs/BACKTESTING.md`.
