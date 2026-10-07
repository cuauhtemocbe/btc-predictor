# BTC Predictor — Project Context for Claude

## Project Overview

**BTC Predictor** is a data science web application that predicts Bitcoin's price for the next day using machine learning models. It tracks predictions, calculates historical errors, and simulates profit/loss (PnL) based on predicted direction.

---

## Tech Stack

- **ML:** Linear Regression is the only model. XGBoost, LSTM and ARIMA were removed (#184); they stay in git history, and any model added later has to beat the linear model and the rule strategy after fees.
- **Data:** Binance only, free, no API key (Design Decision 5). Assets: `BTCUSDT` and `PAXGUSDT` (gold proxy, Design Decision 6b).

---

## Architecture

**For complete architecture details and implementation history, see:**
- `docs/archive/specs/IMPLEMENTATION_HISTORY.md` — Full implementation journey, decisions, and lessons learned

**Railway Services:**
- `postgres` — Shared database
- `api` — Web service (FastAPI + dashboard)
- `fetch-price` — Cron job daily at 00:05 UTC (`5 0 * * *`)
- `daily` — Cron job daily at 00:10 UTC (`10 0 * * *`)
- `monthly-backtest` — Cron job on the 1st of each month at 00:00 UTC (`0 0 1 * *`)

The start commands and schedules live in the Railway dashboard, not in `railway.*.toml` (see `RAILWAY_MULTISTAGE_CONFIG.md`).

---

## Key Design Decisions

### 1. Monorepo with Shared Package
- `shared/` is a Poetry package that `api-service/` and `workers/` depend on
- Avoids code duplication for DB config, models, utilities

### 2. Idempotent Jobs
- UNIQUE constraints prevent duplicates on retries
- Safe to re-run jobs without data corruption

### 3. Abstract BaseModel as the Model Interface
- All ML models inherit from `BaseModel`; the trainer, the predictor and the backtest only use that interface
- `LinearRegressionModel` is the only model and the benchmark any new model must beat. The daily job trains one model and the predictor uses the one active `1d` model; there is no multi-model mode, best-of-several selection or validation-MAPE ranking (removed in #184)
- Models are built through `workers.daily.models.factory.build_model`, the same call the daily trainer and the backtest make

### 4. Two-Phase Prediction Lifecycle
- **Phase 1:** Predictor inserts prediction with `actual_price=NULL`
- **Phase 2:** Evaluator updates with actual price + errors + PnL next day

### 5. Binance Vision as the Only Data Source

- **Why:** the free `data.binance.vision` files give 9 years of daily bars with volume, free and without an API key. The previous data source capped history at 30 days and had no volume, so it was replaced (#102). The Binance REST API is geo-blocked from Railway (HTTP 451), so the REST fallback uses `data-api.binance.vision`.
- **Stored data, history load and daily ingest:** see `workers/fetch_price/CLAUDE.md`.
- **No intraday data is stored.** The spike on 1h data (#109, `docs/spikes/109-intraday-prediction.md`) found a ~1 pp direction edge worth ~2 bps per trade against 20 bps of fees, so intraday was dropped.

### 6. Daily Bars and Return-Based Features

- **Frequency:** the whole pipeline works on daily bars. There is no intraday aggregation.
- **Features** (`shared/shared/features.py`): `W` lagged log returns, their standard deviation as volatility, and `W` log volume changes (`2W + 1` features). **Target:** next-day log return. The predicted price is `last close * exp(predicted return)`.
- **Same code in production and backtest:** the daily trainer, the predictor and the walk-forward backtest all call `shared.features` and `workers.daily.models.factory`.
- **Evaluator:** the predictor runs at 00:10 UTC on day D, ten minutes after the close of the bar opened on D-1, uses that close and predicts the bar opened on D, which closes at 00:00 UTC on D+1 (`predicted_for`). The evaluator settles it against that close once `fetch-price` has ingested it, and leaves it pending if the bar is missing (`fetch_actual_price` in `workers/daily/evaluator.py`).
- **Stale or gapped data:** the predictors and trainers refuse a series whose last bar is not dated yesterday (UTC) or that skips a day, exit 1 and save nothing (`require_fresh_series`, #174).
- **Price anchor is fresh:** the predictor exits 1 and saves nothing if the last closed bar is older than `max_bar_age_hours` (2, `shared/shared/config.py`), so a late run cannot record a price nobody could trade at (`require_recent_close`, #175). The evaluator and the trainer have no such guard.
- **Days are UTC:** every job takes today from `shared.utils.utc_today()`, never from `date.today()`. `docker-compose.yml` sets `TZ=America/Mexico_City`, so the local date is a day behind UTC from 00:00 to 06:00 UTC (#173). Details and the test fixture: `workers/daily/CLAUDE.md`.
- **Live and replay predictions:** `scripts/simulate_history.py` marks the models it trains with `params["simulated"] = true`. The API and the dashboard separate them with `source=live|replay|all` (`source_filter` in `shared/shared/db/crud.py`; default `all`), and the combined total is always labeled "live + replay" (#176).
- **Baselines:** every reported accuracy or PnL sits next to *always-up*, *persistence* and *buy-and-hold*, with the sample size, the edge and a binomial p-value (`shared/shared/baselines.py`).

### 6b. PAXG as a Proxy for Gold

- Binance has no XAU spot pair. Gold is shown through `PAXGUSDT`, the PAX Gold token (1 token = 1 troy ounce of London Good Delivery gold), which trades 24/7.
- It is a proxy, not XAU spot: it can trade at a small premium or discount to gold and follows crypto-exchange liquidity and hours, not the LBMA fixing. Weekend moves have no gold-market counterpart.
- The dashboard states this next to the data (`shared/shared/assets.py`, `Asset.note`). History starts in 2020-08, so there are fewer days than for BTC. The daily worker trains and predicts `BTCUSDT` only (`DEFAULT_SYMBOL`); PAXG is ingested and shown on the dashboard.

### 7. Fixed Training Window

- See `workers/daily/CLAUDE.md` (`training_window_days` in `shared/shared/config.py`, default 21).

### 8. Docker Image Hardening

- The production `Dockerfile` pins the base image by `sha256` digest so builds are reproducible. `Dockerfile.dev` keeps the floating `python:3.13-slim` tag on purpose: dev images should track patch releases.
- The `api` stage has a `HEALTHCHECK` on `GET /health` using stdlib `urllib` (the slim image ships neither `curl` nor `wget`). The `fetch` and `ml-worker` stages have none on purpose: they are one-shot cron jobs.

---

## Testing Requirements

**CRITICAL:** Every Gherkin acceptance criterion MUST have an automated test.

This is **non-negotiable**:
- If the criterion doesn't have a test that fails when it breaks, it's not covered
- "I tested it manually" is NOT acceptable
- Each User Story cannot be closed until all Gherkin scenarios have passing tests

### Test Commands (inside container)

**IMPORTANT:** All test commands MUST be executed inside the `api` container (`docker compose exec api pytest ...`).

Per-module coverage minimums live in `[tool.coverage_thresholds]` of `pyproject.toml`; the rules for setting them are in `scripts/CLAUDE.md`.

### Mutation Testing (Advanced Quality Check)

Cosmic Ray (`cosmic-ray.toml`), run inside the `api` container, checks test quality beyond coverage. Target: mutation score > 85% (results in `mutation_testing_report.md`).

---

## Development Philosophy: Container-First

**IMPORTANT:** All development and testing MUST be done inside Docker containers (`docker compose exec ...`): never `poetry install`, pytest, migrations or PostgreSQL on the host. See Anti-patterns below.

---

## Git Hooks (Pre-commit Framework)

Hooks come from the pre-commit framework (`.pre-commit-config.yaml`). Once per clone: `pre-commit install --install-hooks && pre-commit install --hook-type pre-push`. Full documentation: `scripts/hooks/README.md`.

---

## Common Commands

### Testing (inside container)

```bash
# Skip slow tests (faster feedback)
docker compose exec api pytest -m "not slow"

# Run tests in parallel with pytest-xdist. Each worker gets its own database
# (btcpredictor_test_gw0, _gw1, ...); serial runs use btcpredictor_test.
# The dev database (btcpredictor) is never touched by the suite.
# ~40-50 s with 4 workers vs ~65 s serial.
# More workers than cores is slower (-n 8 took 80-100 s here).
# Use COVERAGE_CORE=sysmon if you combine -n with --cov.
docker compose exec api pytest -n 4 --dist loadscope
```

### Code Quality (inside container)

```bash
# Lint (same scope as CI: every production package, scripts included)
docker compose exec api ruff check shared api workers scripts

# Format code
docker compose exec api ruff format shared api workers scripts

# Types: mypy --strict on shared, workers, api and scripts, test code included
# (shared/tests, workers/*/tests, api/tests and scripts/tests; no test directory
# is excluded and no relaxed override remains in pyproject.toml).
docker compose exec api python -m mypy shared/shared shared/tests workers api scripts
```

Migration commands (`alembic upgrade head`, `revision --autogenerate`): see `shared/CLAUDE.md`.

### Manual Job Execution (inside container)

```bash
# Manually run fetch_price job
docker compose exec api python -m workers.fetch_price.main

# Manually run daily job
docker compose exec api python -m workers.daily
```

### Railway Deploy

```bash
# Deploy api service (automatic on push to main)
git push origin main

# IMPORTANT: After pushing to main, ALWAYS run Railway deployment monitoring
./scripts/hooks/monitor-railway.sh
```

### Main Branch Protection

The `main` branch is protected in GitHub: force-pushes and branch deletion are
disabled, and a merge needs five status checks (`Docker quality gate`,
`trivy-image`, `trivy-config`, `Socket Security: Project Report`, `Socket
Security: Pull Request Alerts`) on a branch that is up to date with `main`
(`strict`). No review is required. `enforce_admins` is intentionally `false`,
allowing the repository owner to push directly when necessary; this is an
explicit solo-maintainer exception, not an omission.

- The checks start a few minutes after a PR opens and `Docker quality gate` takes about 5 minutes. Until they pass, `gh pr merge` fails with "the base branch policy prohibits the merge".
- A PR that is behind `main` cannot merge. Update it with `gh api -X PUT repos/cuauhtemocbe/btc-predictor/pulls/<n>/update-branch` (this `gh` has no `pr update-branch`); that restarts the checks.
- `gh pr edit` fails on the deprecated Projects (classic) GraphQL error. Edit a PR body with `gh api -X PATCH repos/cuauhtemocbe/btc-predictor/pulls/<n> -f body=...`.

**Claude Code Automation:**
- Git does not support post-push hooks natively, so the monitor in *Railway Deploy* must be run explicitly after every push to `main`

---

## Anti-patterns to Avoid

❌ **DON'T** run pytest or any commands directly on host (always use `docker compose exec`)  
❌ **DON'T** install Python dependencies on host machine  
❌ **DON'T** duplicate database connection logic (use `shared/shared/db/database.py`)  
❌ **DON'T** hardcode configuration (use `pydantic-settings` in `shared/shared/config.py`)  
❌ **DON'T** commit `.env` file (use `.env.example` as template)  
❌ **DON'T** bypass UNIQUE constraints (they're for idempotency)  
❌ **DON'T** call `date.today()` in production code (use `shared.utils.utc_today()`)  
❌ **DON'T** skip tests ("I'll add them later" never happens)

---

## Notes for Future Sessions

- User prefers Spanish for communication (but code/docs in English is OK)
- Timezone: America/Mexico_City
- User follows agile methodology with User Stories

### Engram Memory

- **Project name:** `btc-predictor`, pinned in `.engram/config.json` (committed) so memory writes always target this project, whatever the cwd.
- **Diagnostics:** `engram doctor` (read-only) if memory behaves oddly.
