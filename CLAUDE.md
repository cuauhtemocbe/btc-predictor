# BTC Predictor — Project Context for Claude

## Project Overview

**BTC Predictor** is a data science web application that predicts Bitcoin's price for the next day using machine learning models. It tracks predictions, calculates historical errors, and simulates profit/loss (PnL) based on predicted direction.

---

## Tech Stack

Python 3.13, FastAPI + Jinja2, PostgreSQL + SQLAlchemy 2.0 + Alembic, Poetry workspace (shared, api-service, workers). Versions and dependencies are in the `pyproject.toml` files.

- **ML:** the crons train and predict with Linear Regression only. XGBoost, LSTM and ARIMA are enabled in code and tests (#124).
- **Data:** Binance only, free, no API key (Design Decision 5). Assets: `BTCUSDT` and `PAXGUSDT` (gold proxy, Design Decision 6b).

---

## Architecture

**For complete architecture details and implementation history, see:**
- `docs/archive/specs/IMPLEMENTATION_HISTORY.md` — Full implementation journey, decisions, and lessons learned

**Railway Services:**
- `postgres` — Shared database
- `api` — Web service (FastAPI + dashboard)
- `fetch-price` — Cron job daily at 6am UTC (`0 6 * * *`)
- `daily` — Cron job daily at 7am UTC (`0 7 * * *`)
- `weekly-predictor` — Cron job weekly on Mondays at 7am UTC (`0 7 * * 1`)
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

### 3. Abstract BaseModel for ML Extensibility
- All ML models inherit from `BaseModel` abstract class
- Easy to add LSTM, XGBoost, ARIMA without changing infrastructure

### 4. Two-Phase Prediction Lifecycle
- **Phase 1:** Predictor inserts prediction with `actual_price=NULL`
- **Phase 2:** Evaluator updates with actual price + errors + PnL next day

### 5. Binance Vision as the Only Data Source

- **Why:** the free `data.binance.vision` files give 9 years of daily bars with volume, free and without an API key. The previous data source capped history at 30 days and had no volume, so it was replaced (#102). The Binance REST API is geo-blocked from Railway (HTTP 451), so the REST fallback uses `data-api.binance.vision`.
- **Stored data:** one closed UTC daily bar per symbol in `prices` (`symbol`, `timestamp` = 00:00 UTC open, OHLCV, `source`), UNIQUE on `(symbol, timestamp)`.
- **History:** `scripts/load_binance_history.py` loads the monthly files once (`BTCUSDT` from 2017-08, `PAXGUSDT` from 2020-08), verifying each SHA256 checksum.
- **Daily ingest:** `fetch-price` (6am UTC) reads the `daily/` file of each symbol and falls back to REST if the file is not published yet. It backfills missed days and never stores the still-open day.
- **No intraday data is stored.** The spike on 1h data (#109, `docs/spikes/109-intraday-prediction.md`) found a ~1 pp direction edge worth ~2 bps per trade against 20 bps of fees, so intraday was dropped.

### 6. Daily Bars and Return-Based Features

- **Frequency:** the whole pipeline works on daily bars. There is no intraday aggregation.
- **Features** (`shared/shared/features.py`): `W` lagged log returns, their standard deviation as volatility, and `W` log volume changes (`2W + 1` features). **Target:** next-day log return. The predicted price is `last close * exp(predicted return)`.
- **Same code in production and backtest:** the daily trainer, the predictor and the walk-forward backtest all call `shared.features` and `workers.daily.models.factory`.
- **Evaluator:** the predictor runs at 07:00 UTC on day D, uses the close of the bar opened on D-1 and predicts the bar opened on D, which closes at 00:00 UTC on D+1 (`predicted_for`). The evaluator settles it against that close once `fetch-price` has ingested it, and leaves it pending if the bar is missing (`fetch_actual_price` in `workers/daily/evaluator.py`).
- **Baselines:** every reported accuracy or PnL sits next to *always-up*, *persistence* and *buy-and-hold*, with the sample size, the edge and a binomial p-value (`shared/shared/baselines.py`).

### 6b. PAXG as a Proxy for Gold

- Binance has no XAU spot pair. Gold is shown through `PAXGUSDT`, the PAX Gold token (1 token = 1 troy ounce of London Good Delivery gold), which trades 24/7.
- It is a proxy, not XAU spot: it can trade at a small premium or discount to gold and follows crypto-exchange liquidity and hours, not the LBMA fixing. Weekend moves have no gold-market counterpart.
- The dashboard states this next to the data (`shared/shared/assets.py`, `Asset.note`). History starts in 2020-08, so there are fewer days than for BTC. The daily and weekly workers train and predict `BTCUSDT` only (`DEFAULT_SYMBOL`); PAXG is ingested and shown on the dashboard.

### 7. Fixed Training Window

- The sliding-window size is `training_window_days` in `shared/shared/config.py` (default 21, override with the `TRAINING_WINDOW_DAYS` environment variable) and is stored in `models.params["window_days"]`.
- The daily and weekly trainers use every stored `BTCUSDT` daily row and fail with the required and available row counts when there are fewer than `(window + 1) * 5` (plus `horizon - 1` for the weekly model): `required_training_days()` in `workers/daily/trainer.py`.

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

**IMPORTANT:** All test commands MUST be executed inside the `api` container.

```bash
# Start services first (if not running)
docker compose up -d

# Run all tests
docker compose exec api pytest

# Run tests with coverage
docker compose exec api pytest --cov --cov-report=term-missing

# Per-module coverage thresholds (after a run that wrote /tmp/coverage.xml)
docker compose exec api python scripts/check_coverage_thresholds.py /tmp/coverage.xml

# Run tests for specific package
docker compose exec api pytest shared/tests/
docker compose exec api pytest api-service/tests/
docker compose exec api pytest workers/fetch_price/tests/
docker compose exec api pytest workers/daily/tests/

# Run specific test
docker compose exec api pytest shared/tests/test_utils.py::test_calculate_pnl
```

Per-module coverage minimums live in `[tool.coverage_thresholds]` of `pyproject.toml`; the rules for setting them are in `scripts/CLAUDE.md`.

### Mutation Testing (Advanced Quality Check)

Cosmic Ray (`cosmic-ray.toml`), run inside the `api` container, checks test quality beyond coverage. Target: mutation score > 85%. Latest: 100% on `shared/db/crud.py` (274/274 mutants killed, see `mutation_testing_report.md`).

---

## Development Philosophy: Container-First

**IMPORTANT:** All development and testing MUST be done inside Docker containers (`docker compose exec ...`): never `poetry install`, pytest, migrations or PostgreSQL on the host. See Anti-patterns below.

---

## Git Hooks (Pre-commit Framework)

Hooks come from the pre-commit framework (`.pre-commit-config.yaml`): ruff lint and format on commit, pytest with 90% coverage on push. Once per clone: `pre-commit install --install-hooks && pre-commit install --hook-type pre-push`. Full documentation: `scripts/hooks/README.md`.

---

## Common Commands

### Development (local) — ALL commands run in containers

```bash
# Start all services (postgres + api with hot-reload)
docker compose up

# Start services in background
docker compose up -d

# View logs
docker compose logs -f api

# Stop services
docker compose down

# Rebuild containers (after dependency changes)
docker compose build
```

### Testing (inside container)

```bash
# Skip slow tests (faster feedback)
docker compose exec api pytest -m "not slow"

# Run tests in parallel with pytest-xdist. Each worker gets its own database
# (btcpredictor_test_gw0, _gw1, ...); serial runs use btcpredictor_test.
# The dev database (btcpredictor) is never touched by the suite.
# ~40-50 s with 4 workers vs ~65 s serial. LSTM/XGBoost/ARIMA are imported
# lazily, so workers only pay the TensorFlow import if a test needs it.
# More workers than cores is slower (-n 8 took 80-100 s here).
# Use COVERAGE_CORE=sysmon if you combine -n with --cov.
docker compose exec api pytest -n 4 --dist loadscope

# The LSTM/XGBoost/ARIMA tests run with the rest (#124). Importing TensorFlow adds
# a one-off cost to every pytest process that collects them.
```

### Code Quality (inside container)

```bash
# Lint (same scope as CI: every production package, scripts included)
docker compose exec api ruff check shared api workers scripts

# Format code
docker compose exec api ruff format shared api workers scripts

# Types: mypy --strict on shared, workers, api and scripts, test code included
# (workers/*/tests, api/tests and scripts/tests; no test directory is excluded).
# Only the "tests.*" modules of shared/tests keep a relaxed override in pyproject.toml.
docker compose exec api python -m mypy shared/shared shared/btc_shared shared/tests workers api scripts
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

# View logs
railway logs --service api
railway logs --service fetch-price
railway logs --service daily
```

### Main Branch Protection

The `main` branch is protected in GitHub with force-pushes and branch deletion
disabled. `enforce_admins` is intentionally `false`, allowing the repository
owner to push directly when necessary; this is an explicit solo-maintainer
exception, not an omission. Pull-request and required status-check enforcement
will be added when the repository adopts hosted CI checks that GitHub can
require.

**Claude Code Automation:**
- After successfully pushing to `main` branch, ALWAYS execute `./scripts/hooks/monitor-railway.sh`
- This monitors Railway deployment status and reports any issues
- Git does not support post-push hooks natively, so this must be done explicitly

---

## Anti-patterns to Avoid

❌ **DON'T** run pytest or any commands directly on host (always use `docker compose exec`)  
❌ **DON'T** install Python dependencies on host machine  
❌ **DON'T** duplicate database connection logic (use `shared/shared/db/database.py`)  
❌ **DON'T** hardcode configuration (use `pydantic-settings` in `shared/shared/config.py`)  
❌ **DON'T** commit `.env` file (use `.env.example` as template)  
❌ **DON'T** bypass UNIQUE constraints (they're for idempotency)  
❌ **DON'T** skip tests ("I'll add them later" never happens)

✅ **DO** execute ALL commands inside Docker containers  
✅ **DO** write tests for every Gherkin scenario  
✅ **DO** use Alembic for all schema changes  
✅ **DO** keep services decoupled (communicate via DB only)  
✅ **DO** log important events (predictions, errors, model training)  
✅ **DO** validate inputs (Pydantic models for API, assertions in ML code)

---

## Notes for Future Sessions

- User prefers Spanish for communication (but code/docs in English is OK)
- Timezone: America/Mexico_City
- User follows agile methodology with User Stories

### Engram Memory

- **Project name:** `btc-predictor`, pinned in `.engram/config.json` (committed) so memory writes always target this project, whatever the cwd.
- **Setup:** the `engram@engram` Claude Code plugin plus the `engram` binary (v2.2.0), with the MCP server registered globally as `engram mcp --tools=agent`. Nothing repo-specific to install.
- **Recovery:** after a context reset or compaction, call `mem_context` before continuing.
- **Save proactively** with `mem_save` after decisions, bug fixes, discoveries and established patterns; call `mem_session_summary` before closing a session.
- **Diagnostics:** `engram doctor` (read-only) if memory behaves oddly.
