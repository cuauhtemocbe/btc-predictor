---
title: Fetch Price Job - Binance to Database
status: completed
created: 2026-05-16
updated: 2026-05-16
issue: #5
implemented: workers/fetch_price/main.py
tests: workers/fetch_price/tests/test_main.py
coverage: 97%
---

# Fetch Price Job - Binance to Database

## Objective

Create a standalone job (`fetch_price`) that fetches hourly BTC/USDT OHLCV data from Binance and stores it in the `btc_prices` table with full idempotency and error handling. This job will be run manually initially and later scheduled as a cron job on Railway.

## Context

**Why this matters**: The `btc_prices` table is the foundation for all ML predictions. Without historical price data, we cannot train models or make predictions.

**Current state**: 
- ✅ US-001: Shared package with database configuration exists
- ✅ US-002: `btc_prices` table with Alembic migrations exists
- ✅ US-003: BinanceClient with async API calls exists

**What we're building**: A job that ties together the Binance client (US-003) and the database layer (US-001, US-002) to populate the `btc_prices` table with real market data.

**User persona**: Data engineer maintaining the data pipeline.

## Requirements

### Functional Requirements

- [ ] Fetch last 24 hours of BTC/USDT hourly candles from Binance (24 records)
- [ ] Insert fetched candles into `btc_prices` table
- [ ] Handle idempotency: skip existing timestamps (rely on UNIQUE constraint)
- [ ] Log summary: "Skipped X existing, inserted Y new"
- [ ] Exit with code 0 on success, code 1 on error
- [ ] Entry point: `python -m fetch_price.main` (must be runnable from any directory)

### Non-Functional Requirements

- [ ] **Performance**: Fetch + insert 24 records in < 5 seconds
- [ ] **Reliability**: Automatic rollback on partial failure (no orphaned records)
- [ ] **Idempotency**: Running twice produces same result (no duplicates)
- [ ] **Observability**: Structured logging (timestamp, level, message, context)
- [ ] **Error handling**: Graceful failures with specific error messages for:
  - Binance API timeout → log "Binance API timeout", exit 1
  - Invalid API response → log "Invalid response format", exit 1
  - Database connection error → log "Database connection failed", exit 1
- [ ] **Testability**: All Gherkin scenarios covered by automated tests

## Architecture

### Components

```
fetch_price/
├── __init__.py
├── main.py              # Entry point: fetch + save logic
├── requirements.txt     # (if needed, but prefer poetry deps)
└── tests/
    ├── __init__.py
    ├── conftest.py      # Fixtures: mock Binance client, test DB
    └── test_main.py     # Tests for all Gherkin scenarios
```

### Data Flow

```
Binance API
    ↓ (fetch last 24h hourly candles)
BinanceClient (US-003)
    ↓ (return list of BtcPrice objects)
fetch_price.main
    ↓ (bulk insert with idempotency)
PostgreSQL btc_prices table
```

### Key Design Decisions

1. **Bulk insert strategy**: Use `session.add_all()` with exception handling
   - If IntegrityError (duplicate timestamp) → catch, log, continue with next batch
   - Alternative: Check existing timestamps first, filter out duplicates → **Prefer this for cleaner logs**

2. **Fetch window**: Last 24 hours (24 records)
   - Why 24h: Balances freshness vs. API rate limits
   - Future: Parameterize window size via env var

3. **Logging**: Use Python `logging` module with structured format
   - Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
   - Level: INFO for job progress, ERROR for failures

4. **Error handling**: Fail fast on unrecoverable errors
   - Binance timeout → don't retry (let cron retry on next run)
   - DB connection error → don't retry (infrastructure issue)

### Data Model

Uses existing `BtcPrice` model from `shared/shared/db/models.py`:

```python
class BtcPrice(Base):
    __tablename__ = "btc_prices"
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), unique=True, nullable=False)
    open = Column(Numeric(precision=10, scale=2), nullable=False)
    high = Column(Numeric(precision=10, scale=2), nullable=False)
    low = Column(Numeric(precision=10, scale=2), nullable=False)
    close = Column(Numeric(precision=10, scale=2), nullable=False)
    volume = Column(Numeric(precision=20, scale=8), nullable=False)
    source = Column(String(50), nullable=False, default="binance")
```

**Key constraint**: `UNIQUE(timestamp)` ensures idempotency at DB level.

### External Dependencies

- `shared` package: Database engine, BtcPrice model, config
- `httpx` (via BinanceClient): Async HTTP client for Binance API
- `sqlalchemy`: ORM and session management
- `pytest`, `pytest-asyncio`, `respx`: Testing

## User Stories

**Primary User Story (US-004)**:

**As** a data engineer  
**I want** a job that fetches BTC prices from Binance and saves them to the database  
**In order to** populate the btc_prices table without duplicates

### Acceptance Criteria (Gherkin)

See full scenarios in GitHub Issue #5. Key scenarios:

1. **First run inserts new prices** → 24 new records inserted
2. **Second run skips existing prices** → Only new timestamps inserted
3. **Binance API timeout** → Job logs error and exits 1
4. **Database connection failure** → Job logs error and exits 1

## Testing Strategy

### Unit Tests

**Target coverage**: 90%+ for `fetch_price/main.py`

**Test cases**:
1. `test_fetch_and_save_new_prices` — Mock Binance client, verify 24 inserts
2. `test_skip_existing_prices` — Pre-populate DB, verify only new records inserted
3. `test_binance_timeout` — Mock timeout, verify error logging + exit 1
4. `test_database_error` — Mock DB connection failure, verify error logging + exit 1
5. `test_empty_response` — Mock Binance returning 0 candles, verify exit 0
6. `test_idempotency` — Run job twice, verify same result (no duplicates)

### Integration Tests

1. **End-to-end with test database**:
   - Start test postgres container
   - Run job against real Binance API (or mock)
   - Verify records in test DB
   - Clean up test data

2. **Concurrent execution**:
   - Run 2 job instances simultaneously
   - Verify UNIQUE constraint prevents duplicates
   - Verify one job succeeds, other logs "already exists"

### Manual Testing

```bash
# Start services
docker compose up -d

# Run job manually (inside container)
docker compose exec api python -m fetch_price.main

# Verify data
docker compose exec postgres psql -U btcpredictor -d btcpredictor -c "SELECT COUNT(*) FROM btc_prices;"

# Run again to test idempotency
docker compose exec api python -m fetch_price.main
```

## Boundaries & Constraints

### In Scope

- Fetch last 24 hours of hourly BTC/USDT candles from Binance
- Insert into `btc_prices` table
- Idempotent behavior (skip duplicates)
- Error handling and logging
- Automated tests for all Gherkin scenarios
- Manual execution via `python -m fetch_price.main`

### Out of Scope

- ❌ Automated scheduling (US-015: Railway cron configuration)
- ❌ Fetching historical data beyond 24 hours (future enhancement)
- ❌ Multiple symbols (only BTC/USDT for now)
- ❌ Real-time streaming (this is batch, not live)
- ❌ Data backfilling logic (separate US if needed)
- ❌ Retry logic with exponential backoff (fail fast, cron will retry)

### Technical Constraints

- **Runtime**: Must run inside Docker container (has access to shared package)
- **Database**: PostgreSQL only (no SQLite fallback)
- **Python version**: 3.13
- **Dependency management**: Poetry (not pip)
- **Logging**: Standard library `logging` module (no third-party loggers)

## Success Criteria

- [ ] All 4 Gherkin scenarios have passing automated tests
- [ ] Job can be run manually: `docker compose exec api python -m fetch_price.main`
- [ ] Running job twice produces same result (idempotent)
- [ ] Job completes in < 5 seconds for 24 records
- [ ] Logs show clear summary: "Skipped X, inserted Y"
- [ ] Code coverage ≥ 90% for `fetch_price/main.py`
- [ ] Lint passes (ruff check)
- [ ] No security vulnerabilities (trivy scan)
- [ ] PR merged to main branch
- [ ] GitHub Issue #5 closed

## Implementation Plan

See: `specs/fetch-price-job-plan.md` (to be created in Phase 2)

## Notes

- This job will later be scheduled as a Railway cron job (US-015)
- The BinanceClient (US-003) already handles rate limiting and retries
- The `btc_prices` table UNIQUE constraint is our idempotency guarantee
- We deliberately choose to fail fast (exit 1) rather than retry, as cron will handle retries
