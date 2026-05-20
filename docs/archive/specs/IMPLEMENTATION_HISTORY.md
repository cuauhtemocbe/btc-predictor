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
- ~~Implement backtesting framework for strategy evaluation~~ ✅ Completed in Iteration 9
- Add alerting for model performance degradation
- Implement A/B testing for multiple active models
- Add authentication for API endpoints

---

## Iteration 9: Advanced Trading Analysis (US-017 to US-021)

### US-017: Multiple PnL Trading Strategies
**Goal**: Calculate 4 different PnL strategies for comparative analysis  
**Key Decisions**:
- Keep `pnl_simulated` for backward compatibility
- Add 3 new strategies: `pnl_long_short`, `pnl_threshold`, `pnl_realistic`
- `pnl_long_short`: Symmetric long/short (profit from both UP and DOWN predictions)
- `pnl_threshold`: Only trade if predicted change > 1% (avoid noise)
- `pnl_realistic`: Include trading fees (0.1%) and stop-loss (2%)

**Implementation**: 
- Migration: `alembic/versions/00X_add_pnl_strategies.py` (3 new NUMERIC columns)
- Functions: `shared/btc_shared/utils.py::calculate_pnl_*()` (4 functions)
- Integration: `workers/daily/evaluator.py` (calculate all 4 on evaluation)

**Testing**: 100% coverage on all 4 PnL functions with edge cases (fees, stop-loss, zero trades)

### US-018: PnL Strategies Comparison Dashboard
**Goal**: Visual comparison of trading strategies performance  
**Key Decisions**:
- Aggregate metrics per strategy: Total PnL, Win Rate, Max Drawdown, Avg Win/Loss
- Cumulative PnL chart with 4 color-coded lines (one per strategy)
- Highlight best performer with badge
- Calculate Sharpe Ratio for risk-adjusted returns

**Implementation**:
- API endpoint: `api-service/btc_api/routers/predictions.py::get_strategy_comparison()`
- Dashboard section: Extended `api-service/btc_api/templates/index.html`
- Visualization: Chart.js line chart for cumulative PnL

**Metrics**:
- Win Rate: `(wins / total_trades) * 100`
- Max Drawdown: `min(daily_pnl)`
- Sharpe Ratio: `(mean_return - 0) / std_dev_returns`

**Testing**: Integration tests for metrics calculation with edge cases (N/A for zero trades)

### US-019: Backfill Historical BTC Prices
**Goal**: Load 90+ days of historical prices for backtesting  
**Key Decisions**:
- CoinGecko API: `/coins/bitcoin/market_chart` endpoint
- Configurable days parameter (default: 90)
- Batch insert for performance (~2,160 records for 90 days)
- Rate limit handling: exponential backoff on HTTP 429
- Idempotent: UNIQUE constraint prevents duplicates

**Implementation**:
- Script: `scripts/backfill_prices.py` (standalone, can run in container)
- Reuse: `workers/fetch_price/coingecko_client.py` (same API client)
- Logging: Progress indicators (X of Y prices inserted, Z duplicates skipped)

**Usage**: `docker compose exec api python scripts/backfill_prices.py --days=90`

**Testing**: Mock CoinGecko responses for success, rate limit, empty response, timeout scenarios

### US-020: Walk-Forward Backtesting System
**Goal**: Validate model on historical data without lookahead bias  
**Key Decisions**:
- Walk-forward methodology: train on past 30 days, predict next day, evaluate, roll window
- New table: `backtest_results` (separate from `predictions` for production isolation)
- UUID-based `backtest_run_id` (allows multiple backtest experiments)
- Each backtest day: train → predict → fetch actual → calculate PnL (all 4 strategies)
- Reuse production model code (`workers/daily/models/`) for consistency

**Implementation**:
- Migration: `alembic/versions/00X_create_backtest_results.py`
- Model: `shared/btc_shared/db/models.py::BacktestResult`
- Script: `scripts/backtest.py --start-date=YYYY-MM-DD --end-date=YYYY-MM-DD`
- Edge cases: Skip days with insufficient training data, log warnings on training failures

**Schema**:
```sql
backtest_results (
  id, backtest_run_id (UUID), predicted_for (DATE), 
  predicted_at, price_at_prediction, predicted_price, actual_price,
  pnl_simple, pnl_long_short, pnl_threshold, pnl_realistic,
  model_params (JSONB), created_at
)
```

**Testing**: 
- Test walk-forward logic with synthetic 60-day dataset
- Verify no lookahead bias (train data < prediction date)
- Test edge cases: 1 day backtest, insufficient data, training failure

### US-021: Backtesting Results Dashboard
**Goal**: Visualize historical backtesting results  
**Key Decisions**:
- New route: `GET /backtesting` (separate from main dashboard)
- Cumulative PnL chart for historical performance
- Strategy comparison table with backtest metrics
- Date range filter
- Metrics: Win Rate, Max Drawdown, Sharpe Ratio, Best/Worst Day

**Implementation**:
- Router: `api-service/btc_api/routers/backtesting.py`
- Template: `api-service/btc_api/templates/backtesting.html`
- Query: Aggregate backtest_results by strategy, calculate cumulative PnL
- Chart: Chart.js with same color scheme as main dashboard

**Metrics Calculated**:
- Win Rate: `(count(pnl > 0) / count(pnl != 0)) * 100`
- Max Drawdown: `min(daily_pnl)`
- Best Day: `max(daily_pnl)`
- Worst Day: `min(daily_pnl)`
- Sharpe Ratio: `mean(returns) / std(returns)`

**Testing**: 
- Integration tests with mock backtest data
- Test empty state (no backtest results)
- Test date range filtering
- Test metrics calculation accuracy

---

## Iteration 9 Key Outcomes

**New Features**:
✅ 4 PnL trading strategies for comprehensive analysis  
✅ Visual strategy comparison dashboard  
✅ Historical data backfill (90+ days from CoinGecko)  
✅ Walk-forward backtesting framework  
✅ Backtesting results visualization

**Technical Achievements**:
- No lookahead bias in backtesting (walk-forward methodology)
- Idempotent backfill (safe retries)
- Production model code reused for backtesting (consistency)
- Separate `backtest_results` table (production isolation)
- Realistic trading simulation (fees, stop-loss, thresholds)

**Testing**:
- All 5 user stories have comprehensive test coverage
- Edge cases covered: rate limits, empty data, zero trades, training failures
- Mutation testing validates test quality

**Impact**:
- Traders can now validate model effectiveness on 90 days of historical data
- Risk-adjusted returns visible via Sharpe Ratio
- Multiple strategies allow approach comparison (aggressive vs. conservative)

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

**Total User Stories**: 21 (US-001 to US-021)  
**Total Iterations**: 9  
**Development Period**: May 2026  
**Final Status**: ✅ All stories complete, deployed to Railway  
**GitHub Issues**: All closed (#2 to #23)  
**Test Coverage**: 90%+ across all packages  

**Project Owner**: Cuauhtémoc (cuauhtemocbe@gmail.com)  
**GitHub**: https://github.com/cuauhtemocbe/btc-predictor  
**Live Deployment**: Railway (api-service public URL)

---

*This document summarizes the complete implementation history. For detailed specifications, refer to the individual spec files archived in this directory.*
