# BTC Predictor — Project Context for Claude

## Project Overview

**BTC Predictor** is a data science web application that predicts Bitcoin's price for the next day using machine learning models. It tracks predictions, calculates historical errors, and simulates profit/loss (PnL) based on predicted direction.

**Status:** ✅ **All User Stories Complete** (US-001 to US-024 implemented and deployed to Railway)

---

## Tech Stack

- **Language:** Python 3.13
- **Framework:** FastAPI + Jinja2 (HTML templates)
- **Database:** PostgreSQL + SQLAlchemy 2.0 + Alembic (migrations)
- **ML:** scikit-learn (Linear Regression), pandas, numpy
- **Data Source:** CoinGecko API (migrated from Binance due to geo-blocking)
- **Deployment:** Railway (4 services: postgres, api, fetch-price cron, daily cron)
- **Dependency Management:** Poetry (workspace with 3 packages: shared, api-service, workers)

---

## Architecture

**For complete architecture details and implementation history, see:**
- `docs/archive/specs/IMPLEMENTATION_HISTORY.md` — Full implementation journey, decisions, and lessons learned

**Key structure:**

```
btc-predictor/
├── shared/              # Common package (config, DB, utils)
├── api-service/         # Web service (always on)
└── workers/
    ├── fetch_price/     # Hourly cron: fetch BTC prices
    └── daily/           # Daily cron: evaluate → train → predict
```

**Railway Services:**
- `postgres` — Shared database
- `api` — Web service (FastAPI + dashboard)
- `fetch-price` — Cron job daily at 6am UTC (`0 6 * * *`)
- `daily` — Cron job daily at 7am UTC (`0 7 * * *`)
- `weekly` — Cron job weekly on Mondays at 7am UTC (`0 7 * * 1`)

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

### 5. CoinGecko Over Binance
- Migrated from Binance API due to HTTP 451 geo-blocking in Railway
- CoinGecko free API with rate limit handling

### 6. Daily Data Frequency with 4-Hour Aggregation

- **Data Storage:** CoinGecko API returns 4-hour granularity for 1-30 day windows (~6 candles/day)
- **Fetch Strategy:** Daily worker fetches last 24 hours at 6am UTC, inserts ~6 new candles
- **Model Training:** Daily worker aggregates 4-hour data to daily using `DATE_TRUNC('day')`
- **Evaluator:** Uses first candle at/after 7am UTC (typically the 8am candle)
- **Rationale:**
  - Provides flexibility to test models with different frequencies (daily, 8h, 4h)
  - Daily frequency yields 65-66% ML accuracy vs 51-55% for hourly (research-backed)
  - Lower transaction costs: ~20-30 trades/month vs 180+ for hourly
  - Target users: part-time investors, not day traders
- **CoinGecko Limitation:** Beyond 30-day windows, granularity degrades to daily/4-day spacing

### 7. Dynamic Training Window Strategy

**Problem:** CoinGecko free API limits historical data to 30 days with 4-hour granularity. System needs to train models immediately while data accumulates.

**Solution:** Adaptive training strategy that adjusts window size and minimum data requirements based on available historical data:

| Phase | Days Available | Window Size | Min Days | Models Trained |
|-------|---------------|-------------|----------|----------------|
| **Phase 1 - Initial** | 30-44 days | 5 days | 30 | Linear, LSTM, XGBoost |
| **Phase 2 - Growth** | 45-59 days | 7 days | 40 | Linear, LSTM, XGBoost |
| **Phase 3 - Intermediate** | 60-89 days | 10 days | 55 | Linear, LSTM, XGBoost, ARIMA |
| **Phase 4 - Mature** | 90-144 days | 14 days | 75 | Linear, LSTM, XGBoost, ARIMA |
| **Phase 5 - Optimal** | 145+ days | 21 days | 110 | Linear, LSTM, XGBoost, ARIMA |

**Key Features:**
- **Auto-detection:** `count_available_days()` queries database for distinct days of data
- **Automatic scaling:** As data accumulates, window size grows automatically for better predictions
- **Train/Val split safety:** `min_days` ensures enough data for 70/20/10 split after sliding windows
- **ARIMA threshold:** ARIMA model requires 60+ days (excluded in Phases 1-2)
- **No user intervention:** System self-optimizes from day 30 to optimal configuration at 145+ days

**Timeline:**
- **Month 1 (30 days):** First models can be trained (Phase 1: window=5)
- **Month 2 (60 days):** ARIMA becomes available (Phase 3: window=10)
- **Month 3 (90 days):** Mature configuration (Phase 4: window=14)
- **Month 5+ (145 days):** Optimal configuration achieved (Phase 5: window=21) ✅

**Implementation:** `workers/daily/trainer.py` → `calculate_dynamic_window()` function

### 8. Docker Image Hardening

- **Production `Dockerfile`:** base image pinned by immutable `sha256` digest
  (`python:3.13-slim@sha256:...`) so prod builds are byte-for-byte
  reproducible and can't silently pick up an upstream base image change.
- **`Dockerfile.dev`:** intentionally keeps the floating `python:3.13-slim`
  tag — dev images rebuild often and should track the latest patch release
  instead of requiring a manual digest bump for every security fix.
- **API healthcheck:** the `api` stage of `Dockerfile` (and the `api`
  service in `docker-compose.yml`) declare a `HEALTHCHECK` against the
  existing `GET /health` endpoint (`api-service/api/main.py`), using
  Python's stdlib `urllib` since the slim base image ships neither `curl`
  nor `wget`.
- **`fetch` and `ml-worker` stages:** intentionally have no `HEALTHCHECK` —
  they're one-shot Railway cron jobs, not long-running processes, so there's
  nothing for a container healthcheck to probe.

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

# Run tests for specific package
docker compose exec api pytest shared/tests/
docker compose exec api pytest api-service/tests/
docker compose exec api pytest workers/fetch_price/tests/
docker compose exec api pytest workers/daily/tests/

# Run specific test
docker compose exec api pytest shared/tests/test_utils.py::test_calculate_pnl
```

**Current Coverage:** 95% across all packages

### Test Performance

**Execution Time:** ~94 seconds (1 min 34 seg) for 515 tests

**Optimizations Applied** (May 2026):
- ✅ **Cached model artifacts** (module-scoped): Linear, XGBoost, LSTM models train ONCE per test module instead of per test
- ✅ **Cached price data** (module-scoped): Pre-calculated price datasets (180-720 records) generated once per module
- ✅ **Pytest markers**: Registered `slow`, `integration`, `unit`, `db` for selective test execution

**Performance History:**
- Baseline (May 23, 2026): 127.74s (2 min 7 seg)
- After optimization (May 24, 2026): 93.67s (1 min 33 seg)
- **Improvement**: 26.7% faster ⚡

**Commands:**
```bash
# Run all tests (optimized)
docker compose exec api pytest

# Run without slow tests (faster feedback)
docker compose exec api pytest -m "not slow"
```

### Mutation Testing (Advanced Quality Check)

Mutation testing evaluates test **quality**, not just coverage. It introduces bugs (mutations) in code and checks if tests detect them.

**Framework:** Cosmic Ray 8.3 (configured in `cosmic-ray.toml` and `pyproject.toml`)

```bash
# IMPORTANT: All commands run inside api container
docker compose exec api <command>

# Initialize mutation testing session
cosmic-ray init cosmic-ray.toml session.sqlite

# Execute mutation testing (run mutants against tests)
cosmic-ray exec cosmic-ray.toml session.sqlite

# Generate report
cr-report session.sqlite

# View detailed results
cr-html session.sqlite > mutation-report.html

# Continue interrupted session
cosmic-ray exec cosmic-ray.toml session.sqlite --no-local-import

# Baseline test (verify tests pass before mutating)
cosmic-ray --verbosity=INFO baseline cosmic-ray.toml
```

**How it works:**
1. Cosmic Ray changes code (e.g., `>` → `>=`, `True` → `False`, remove lines)
2. Runs tests against each mutated version
3. ✅ **Mutant killed** = Tests detected the bug (good)
4. ❌ **Mutant survived** = Tests didn't detect the bug (bad - need more tests)

**Metrics Goal:**
- Coverage: >90% ✅
- Mutation Score: >85% (target)

**Latest Results:** 100% mutation score on `shared/db/crud.py` (274/274 mutants killed - see `mutation_testing_report.md`)

---

## Development Philosophy: Container-First

**IMPORTANT:** All development and testing MUST be done inside Docker containers.

### Why Containers?

- **Consistency:** Same environment for all developers and CI/CD
- **No "works on my machine":** Postgres version, Python version, dependencies are identical
- **Production parity:** Development environment matches Railway deployment

### DO NOT:
❌ Install Python dependencies locally (`poetry install` on host)  
❌ Run pytest on host machine  
❌ Run migrations from host  
❌ Install PostgreSQL on host

### DO:
✅ Execute all commands via `docker compose exec`  
✅ Use volumes for code hot-reload  
✅ Keep host machine clean (only Docker, IDE, git)

---

## Git Hooks (Pre-commit Framework)

**IMPORTANT:** This project uses [pre-commit](https://pre-commit.com/) framework for git hooks.

### First-time Setup (per developer)

```bash
# Install pre-commit (only once per machine)
pip install pre-commit

# Install git hooks (only once per repo clone)
pre-commit install --install-hooks
pre-commit install --hook-type pre-push
```

### What Gets Checked Automatically

**Pre-commit** (runs on `git commit`):
- ✅ Ruff lint (auto-fixes when possible)
- ✅ Ruff format (code style)

**Pre-push** (runs on `git push`):
- ✅ Pytest with 90% coverage requirement
- ✅ Auto-starts Docker Compose if needed

### Manual Hook Execution

```bash
# Run all pre-commit hooks manually
pre-commit run --all-files

# Run only pre-push hooks (tests)
pre-commit run --hook-stage push --all-files

# Update hook versions
pre-commit autoupdate
```

See `scripts/hooks/README.md` for full documentation.

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
# Run all tests (inside api container)
docker compose exec api pytest

# Run tests with coverage
docker compose exec api pytest --cov --cov-report=term-missing

# Run tests in parallel (faster)
docker compose exec api pytest -n auto
```

### Code Quality (inside container)

```bash
# Lint
docker compose exec api ruff check shared api-service workers

# Format code
docker compose exec api ruff format shared api-service workers
```

### Database Migrations (inside container)

```bash
# Run migrations
docker compose exec api sh -c "cd shared && alembic upgrade head"

# Create new migration
docker compose exec api sh -c "cd shared && alembic revision --autogenerate -m 'description'"

# Downgrade migration
docker compose exec api sh -c "cd shared && alembic downgrade -1"

# View migration history
docker compose exec api sh -c "cd shared && alembic history"
```

### Manual Job Execution (inside container)

```bash
# Manually run fetch_price job
docker compose exec api python -m fetch_price.main

# Manually run daily job
docker compose exec api python -m daily.main
```

### Shell Access (for debugging)

```bash
# Open shell inside api container
docker compose exec api bash

# Open PostgreSQL psql shell
docker compose exec postgres psql -U btcpredictor -d btcpredictor
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

**Claude Code Automation:**
- After successfully pushing to `main` branch, ALWAYS execute `./scripts/hooks/monitor-railway.sh`
- This monitors Railway deployment status and reports any issues
- Git does not support post-push hooks natively, so this must be done explicitly

---

## Anti-patterns to Avoid

❌ **DON'T** run pytest or any commands directly on host (always use `docker compose exec`)  
❌ **DON'T** install Python dependencies on host machine  
❌ **DON'T** duplicate database connection logic (use `shared/btc_shared/db/database.py`)  
❌ **DON'T** hardcode configuration (use `pydantic-settings` in `shared/btc_shared/config.py`)  
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

## Project Context Links

- **GitHub Repository:** https://github.com/cuauhtemocbe/btc-predictor
- **Project Board:** https://github.com/users/cuauhtemocbe/projects/1/views/1
- **Implementation History:** `docs/archive/specs/IMPLEMENTATION_HISTORY.md`
- **User Stories:** GitHub Issues #2 to #17 (all closed ✅)
- **License:** [MIT](LICENSE)
- **Changelog:** [CHANGELOG.md](CHANGELOG.md) (Keep a Changelog format)

---

## Owner

**Name:** Cuauhtémoc (cuauhtemocbe)  
**Email:** cuauhtemocbe@gmail.com  
**GitHub:** https://github.com/cuauhtemocbe  
**Timezone:** America/Mexico_City

---

## Notes for Future Sessions

- User prefers Spanish for communication (but code/docs in English is OK)
- User follows agile methodology with User Stories
- All 16 User Stories (US-001 to US-016) are complete and deployed to Railway
- User is comfortable with command-line tools (gh, docker, poetry)
- User has engram memory plugin active (save important decisions to engram)
