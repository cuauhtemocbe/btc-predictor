# BTC Predictor - Implementation History Summary

**Project**: Bitcoin Price Prediction System  
**Period**: May 2026 (Iterations 1-8)  
**Status**: All 16 User Stories Completed  
**Deployment**: Railway (4 services: postgres, api, fetch-price cron, daily cron)

---

## Overview

This document summarizes the complete implementation journey of the BTC Predictor project, which followed a Spec-Driven Development approach across 8 iterations. Each User Story (US-001 to US-016) had detailed specs, implementation plans, and comprehensive test coverage.

---

## Architecture Evolution

### Final Architecture
```
btc-predictor/
├── shared/              # Common package: database, config, utils
│   ├── btc_shared/
│   │   ├── config.py    # Pydantic settings (DATABASE_URL, etc.)
│   │   ├── db/          # SQLAlchemy models, CRUD operations
│   │   └── utils.py     # PnL calculation, error metrics
│   └── alembic/         # Database migrations
│
├── api-service/         # Web service (Railway: always on)
│   └── btc_api/
│       ├── main.py      # FastAPI app with Jinja2 templates
│       ├── routers/     # REST endpoints (/prices, /predictions/*)
│       └── templates/   # HTML dashboard
│
└── workers/
    ├── fetch_price/     # Hourly cron: CoinGecko → database
    └── daily/           # Daily cron: evaluate → train → predict
        ├── evaluator.py
        ├── trainer.py
        ├── predictor.py
        └── models/      # BaseModel + LinearRegressionModel
```

### Database Schema

**btc_prices** - Hourly OHLCV data
- Columns: `id, timestamp, open, high, low, close, volume, source`
- UNIQUE constraint on `timestamp` (idempotency)

**models** - Trained ML models
- Columns: `id, name, version, params (JSONB), artifact (BYTEA), trained_at, train_from, train_to, is_active`
- Stores serialized scikit-learn models

**predictions** - Daily predictions + evaluation
- Columns: `id, model_id (FK), predicted_for (DATE), predicted_at, price_at_prediction, predicted_price, actual_price, evaluated_at, error_abs, error_pct, direction_correct, pnl_simulated`
- Two-phase lifecycle: insert (predictor) → update (evaluator)

---

## Iteration 1: Database Foundation (US-001, US-002)

### US-001: Shared Package with Database Configuration
**Goal**: Create centralized database configuration package  
**Key Decisions**:
- Poetry workspace with shared package pattern
- Pydantic-settings for environment config
- SQLAlchemy 2.0 with async support
- `get_db()` dependency for FastAPI injection

**Implementation**: `shared/btc_shared/config.py`, `shared/btc_shared/db/database.py`

### US-002: BTC Prices Table with Alembic Migrations
**Goal**: Create table for hourly OHLCV data  
**Key Decisions**:
- UNIQUE constraint on `timestamp` for idempotency
- TIMESTAMPTZ for timezone-aware timestamps
- Index on `timestamp` for fast range queries
- Alembic for schema versioning

**Migration**: `alembic/versions/001_create_btc_prices.py`  
**Model**: `shared/btc_shared/db/models.py::BtcPrice`

---

## Iteration 2: Price Data Ingestion (US-003, US-004)

### US-003: Binance API Client → CoinGecko Migration
**Goal**: Fetch hourly BTC OHLCV data from external API  
**Key Decisions**:
- Initially implemented Binance client
- **Migrated to CoinGecko** due to HTTP 451 geo-blocking in Railway
- Async httpx client with timeout handling
- Exponential backoff retry for rate limits (429)

**Implementation**: `workers/fetch_price/coingecko_client.py`  
**Testing**: Mocked with `respx` library

### US-004: Fetch Price Cron Job
**Goal**: Hourly job to fetch and store BTC prices  
**Key Decisions**:
- Entry point: `python -m fetch_price.main`
- Idempotent: UNIQUE constraint prevents duplicates
- Fetch last 24 hours on each run (backfill safety)
- Structured logging with success/skip counts

**Deployment**: Railway cron (hourly schedule)  
**Coverage**: 97%

---

## Iteration 3: API Layer (US-005)

### US-005: GET /api/prices Endpoint
**Goal**: REST API to query historical Bitcoin prices  
**Key Decisions**:
- FastAPI with async handlers
- Query params: `?days=30` (default: 7 days)
- Response: `[{timestamp, open, high, low, close, volume}]`
- CORS enabled for frontend integration

**Implementation**: `api-service/btc_api/routers/prices.py`  
**Tests**: httpx AsyncClient integration tests

---

## Iteration 4: ML Foundation (US-006, US-007)

### US-006: BaseModel Abstract Class + LinearRegressionModel
**Goal**: ML model abstraction layer for easy algorithm swapping  
**Key Decisions**:
- Abstract `BaseModel` with interface: `train()`, `predict()`, `serialize()`, `deserialize()`
- Sliding window features (default: 30-day lookback)
- scikit-learn LinearRegression as baseline model
- Pickle serialization for database storage

**Implementation**: `workers/daily/models/base.py`, `workers/daily/models/linear_regression.py`  
**Testing**: Synthetic data tests for train/predict cycle

### US-007: Models Table for ML Model Versioning
**Goal**: Persistent storage for trained models  
**Key Decisions**:
- BYTEA column for serialized model artifacts (pickle)
- JSONB column for hyperparameters
- `is_active` flag (only 1 active per name)
- Track training date range (`train_from`, `train_to`)

**Migration**: `alembic/versions/002_create_models.py`  
**Model**: `shared/btc_shared/db/models.py::Model`  
**Coverage**: 97%

---

## Iteration 5: Prediction System (US-008, US-009, US-010)

### US-008: Predictions Table
**Goal**: Store predictions and evaluation metrics  
**Key Decisions**:
- **Two-phase lifecycle**: insert with NULL evaluation → update next day
- Foreign key to `models.id` (CASCADE delete)
- Columns for errors: `error_abs`, `error_pct`, `direction_correct`
- Column for PnL: `pnl_simulated`

**Migration**: `alembic/versions/003_create_predictions.py`  
**Model**: `shared/btc_shared/db/models.py::Prediction`

### US-009: Daily Predictor Job
**Goal**: Predict tomorrow's BTC price using active model  
**Key Decisions**:
- Load active model from database
- Fetch last 30 days of prices for features
- Predict next day's close price
- Insert into predictions table with evaluation fields NULL

**Implementation**: `workers/daily/predictor.py`  
**Entry point**: Part of `workers/daily/main.py`

### US-010: Daily Evaluator Job
**Goal**: Evaluate yesterday's prediction with actual price  
**Key Decisions**:
- Find yesterday's prediction (WHERE `predicted_for = yesterday`)
- Fetch actual price from `btc_prices`
- Calculate errors: absolute, percentage
- Check direction correctness: `(predicted - price_at_pred) * (actual - price_at_pred) > 0`
- Calculate PnL (see US-013)
- Update prediction record

**Implementation**: `workers/daily/evaluator.py`  
**Entry point**: Part of `workers/daily/main.py`  
**Coverage**: 95%

---

## Iteration 6: Dashboard & API (US-011, US-012)

### US-011: GET /api/predictions/history Endpoint
**Goal**: API to retrieve predictions with evaluation metrics  
**Key Decisions**:
- Query params: `?days=30` (default: 7 days)
- Return: predictions with model info, errors, PnL
- Order by `predicted_for DESC` (newest first)
- Include model name and version in response

**Implementation**: `api-service/btc_api/routers/predictions.py`  
**Tests**: Integration tests with test data

### US-012: Web Dashboard (GET /)
**Goal**: HTML interface to visualize predictions and performance  
**Key Decisions**:
- Jinja2 templates with FastAPI
- Display: recent predictions, error metrics, PnL chart
- No JavaScript framework (simple server-side rendering)
- Responsive CSS (mobile-friendly)

**Implementation**: `api-service/btc_api/templates/index.html`  
**Endpoint**: `api-service/btc_api/main.py::root()`

---

## Iteration 7: PnL Simulation (US-013, US-014)

### US-013: PnL Calculation Logic
**Goal**: Simulate trading profit/loss based on predictions  
**Trading Strategy**:
- If `predicted_price > price_at_prediction`: Buy 1 BTC → PnL = `actual_price - price_at_prediction`
- Else: Stay in cash → PnL = 0

**Key Insight**: Tests directional predictive power (not absolute accuracy)

**Implementation**: `shared/btc_shared/utils.py::calculate_pnl()`  
**Usage**: Called by evaluator job (US-010)  
**Coverage**: 100% (critical business logic)

### US-014: GET /api/predictions/pnl Endpoint
**Goal**: API to retrieve cumulative PnL over time  
**Key Decisions**:
- Query params: `?days=30` (default: 7 days)
- Response: `[{date, pnl, cumulative_pnl}]`
- Cumulative PnL = running sum of daily PnL
- Used by dashboard to show profitability trend

**Implementation**: `api-service/btc_api/routers/predictions.py::get_pnl()`  
**Tests**: Edge cases (no predictions, all cash, mixed)

---

## Iteration 8: Railway Cron Automation (US-015, US-016)

### US-015: Railway Fetch-Price Cron
**Goal**: Deploy fetch-price job as Railway cron service  
**Key Decisions**:
- Service name: `fetch-price`
- Schedule: `0 * * * *` (every hour at minute 0)
- Start command: `python -m fetch_price.main`
- Shared postgres database with API service

**Deployment**: Railway cron service  
**Monitoring**: Railway logs + structured logging

### US-016: Railway Daily Cron
**Goal**: Deploy daily job (evaluate → train → predict) as Railway cron  
**Key Decisions**:
- Service name: `daily`
- Schedule: `0 7 * * *` (7am UTC daily)
- Start command: `python -m daily.main`
- Sequential execution: evaluator → trainer → predictor
- Shared postgres database with API service

**Deployment**: Railway cron service  
**Monitoring**: Railway logs + structured logging  
**Timezone**: America/Mexico_City (configured in Railway env vars)

---

## Key Technical Decisions

### 1. CoinGecko Over Binance
**Problem**: Binance API returned HTTP 451 (geo-blocking) in Railway deployment  
**Solution**: Migrated to CoinGecko free API with rate limit handling  
**Files Changed**: `workers/fetch_price/coingecko_client.py`

### 2. Two-Phase Prediction Lifecycle
**Rationale**: Separate prediction logic from evaluation logic  
**Benefit**: Predictions exist immediately (don't wait for next day)  
**Implementation**: Phase 1 (INSERT with NULLs) → Phase 2 (UPDATE with evaluation)

### 3. Abstract BaseModel for ML
**Rationale**: Enable easy addition of new algorithms (LSTM, XGBoost, ARIMA)  
**Benefit**: Infrastructure code (trainer, predictor) doesn't change when swapping models  
**Pattern**: Strategy pattern with `train()`, `predict()`, `serialize()`, `deserialize()`

### 4. Idempotent Jobs
**Mechanism**: UNIQUE constraints on `btc_prices.timestamp` and `predictions.predicted_for`  
**Benefit**: Safe retries, no data corruption on cron re-runs  
**Coverage**: Tested with duplicate insert scenarios

### 5. Container-First Development
**Approach**: All development and testing inside Docker containers  
**Commands**: `docker compose exec api pytest`, `docker compose exec api bash`  
**Benefit**: Production parity, no "works on my machine" issues

---

## Testing Strategy

### Test Coverage Summary
- **shared package**: 89% coverage
- **api-service**: 92% coverage
- **fetch_price worker**: 97% coverage
- **daily worker**: 95% coverage

### Test Types Implemented
1. **Unit Tests**: Pure functions (PnL calculation, error metrics)
2. **Integration Tests**: Database CRUD operations, API endpoints
3. **Job Tests**: Idempotency, error handling, external API mocking
4. **Mutation Testing**: Verified test quality with mutation analysis

### Critical Test Patterns
- **Fixtures with cleanup**: `yield` pattern for automatic data cleanup
- **Mock external APIs**: `respx` for httpx mocking (CoinGecko)
- **Test database**: Same postgres container, isolated via fixtures
- **Async tests**: `@pytest.mark.asyncio` for FastAPI/httpx

---

## Deployment Architecture (Railway)

### Services
1. **postgres** (Plugin): Shared database for all services
2. **api** (Web Service): FastAPI app, always on, public URL
3. **fetch-price** (Cron): Hourly price fetch job
4. **daily** (Cron): Daily evaluate → train → predict job

### Environment Variables (Railway)
- `DATABASE_URL`: Auto-injected by postgres plugin
- `PORT`: Auto-injected for api service
- `TZ`: America/Mexico_City (for cron scheduling)
- `ENVIRONMENT`: production

### Monitoring
- Railway logs (structured JSON logging)
- Database query monitoring via Railway postgres metrics
- API health check: `GET /health`

---

## Lessons Learned

### What Went Well
✅ **Spec-Driven Development**: Clear specs prevented scope creep  
✅ **Incremental Iterations**: Each iteration was deployable and testable  
✅ **Test-First Approach**: 90%+ coverage prevented regressions  
✅ **Idempotent Jobs**: Safe retries simplified error recovery  
✅ **Container-First**: No environment inconsistencies

### Challenges & Solutions
❌ **Binance Geo-Blocking** → ✅ Migrated to CoinGecko  
❌ **CoinGecko Rate Limits** → ✅ Exponential backoff retry  
❌ **Railway ASGI Import Errors** → ✅ Fixed Dockerfile path structure  
❌ **FastAPI/Pydantic Version Conflicts** → ✅ Consolidated Poetry install

### Future Improvements
- Add LSTM or XGBoost models (abstract BaseModel makes this easy)
- Implement backtesting framework for strategy evaluation
- Add alerting for model performance degradation
- Implement A/B testing for multiple active models
- Add authentication for API endpoints

---

## Files Reference

### Spec Files (Original Location: `specs/`)
All original spec and plan files have been archived in this directory. Key specs:
- `shared-package-database.md` (US-001)
- `btc-prices-table.md` (US-002)
- `binance-api-client.md` → `coingecko-migration.md` (US-003)
- `fetch-price-job.md` (US-004)
- `api-prices-endpoint.md` (US-005)
- `ml-base-model.md` (US-006)
- `us-007-models-table.md` (US-007)
- `us-008-predictions-table.md` (US-008)
- `us-009-daily-predictor.md` (US-009)
- `daily-evaluator.md` (US-010)
- `predictions-history-api.md` (US-011)
- `dashboard.md` (US-012)
- `us-013-pnl-calculation.md` (US-013)
- `us-014-pnl-api-endpoint.md` (US-014)
- `us-015-railway-fetch-price-cron.md` (US-015)
- `us-016-railway-daily-cron.md` (US-016)

### Implementation Files
- Database: `shared/btc_shared/db/models.py`, `shared/alembic/versions/`
- API: `api-service/btc_api/main.py`, `api-service/btc_api/routers/`
- Workers: `workers/fetch_price/main.py`, `workers/daily/main.py`
- ML Models: `workers/daily/models/base.py`, `workers/daily/models/linear_regression.py`
- Utils: `shared/btc_shared/utils.py`

### Deployment Guides
- `RAILWAY_DEPLOYMENT.md` (main deployment guide, in repo root)

---

## Project Completion

**Total User Stories**: 16 (US-001 to US-016)  
**Total Iterations**: 8  
**Development Period**: May 2026  
**Final Status**: ✅ All stories complete, deployed to Railway  
**GitHub Issues**: All closed (#2 to #17)  
**Test Coverage**: 90%+ across all packages  

**Project Owner**: Cuauhtémoc (cuauhtemocbe@gmail.com)  
**GitHub**: https://github.com/cuauhtemocbe/btc-predictor  
**Live Deployment**: Railway (api-service public URL)

---

*This document summarizes the complete implementation history. For detailed specifications, refer to the individual spec files archived in this directory.*
