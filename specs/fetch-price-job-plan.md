# Implementation Plan: Fetch Price Job

**Spec**: [fetch-price-job.md](./fetch-price-job.md)  
**Created**: 2026-05-16  
**Status**: completed

## Components

### 1. Job Structure & Entry Point
- **Purpose**: Create `workers/fetch_price/` package with proper structure
- **Files**: 
  - `workers/fetch_price/__init__.py`
  - `workers/fetch_price/main.py`
  - `workers/fetch_price/pyproject.toml` (Poetry config)
- **Effort**: XS (30 min)
- **Dependencies**: None

### 2. Core Fetch & Save Logic
- **Purpose**: Implement main function that fetches from Binance and saves to DB
- **Files**: `workers/fetch_price/main.py`
- **Key functions**:
  - `fetch_prices() -> List[Dict]` — Call BinanceClient, get last 24h
  - `filter_existing_timestamps(prices, session) -> List[Dict]` — Query DB, filter duplicates
  - `save_prices(prices, session) -> int` — Bulk insert filtered prices
  - `main()` — Orchestrate: fetch → filter → save → log summary
- **Effort**: M (2-3 hours)
- **Dependencies**: BinanceClient (US-003), shared DB engine (US-001), BtcPrice model (US-002)

### 3. Error Handling & Logging
- **Purpose**: Graceful error handling with structured logging
- **Files**: `workers/fetch_price/main.py`
- **Key aspects**:
  - Configure logging (INFO level, structured format)
  - Try/except blocks for:
    - Binance API errors (timeout, rate limit, invalid response)
    - Database errors (connection, integrity)
  - Exit codes: 0 (success), 1 (error)
- **Effort**: S (1 hour)
- **Dependencies**: Core logic (component 2)

### 4. Test Suite
- **Purpose**: Automated tests for all Gherkin scenarios
- **Files**:
  - `workers/fetch_price/tests/__init__.py`
  - `workers/fetch_price/tests/conftest.py` (fixtures)
  - `workers/fetch_price/tests/test_main.py` (test cases)
- **Test cases**:
  1. `test_fetch_and_save_new_prices` — First run, 24 inserts
  2. `test_skip_existing_prices` — Second run, skip duplicates
  3. `test_binance_timeout` — API timeout, exit 1
  4. `test_database_error` — DB connection failure, exit 1
  5. `test_empty_response` — Binance returns 0 candles
  6. `test_idempotency` — Run twice, same result
- **Effort**: M (2-3 hours)
- **Dependencies**: Core logic + error handling (components 2, 3)

### 5. Integration with Docker Compose
- **Purpose**: Ensure job runs inside container with correct dependencies
- **Files**: 
  - `workers/fetch_price/pyproject.toml` (add shared dependency)
  - Root `docker-compose.yml` (no changes needed, api service already has access)
- **Verification**: `docker compose exec api python -m fetch_price.main`
- **Effort**: XS (30 min)
- **Dependencies**: Job structure (component 1)

## Dependencies

### Build Order
1. **Component 1**: Job structure (foundation)
2. **Component 5**: Docker integration (verify structure works)
3. **Component 2**: Core logic (main implementation)
4. **Component 3**: Error handling (wrap core logic)
5. **Component 4**: Test suite (verify everything works)

### External Dependencies
- ✅ **US-003**: BinanceClient (already implemented)
- ✅ **US-002**: BtcPrice model + btc_prices table (already implemented)
- ✅ **US-001**: Shared DB engine (already implemented)
- `httpx`: Async HTTP (transitively via BinanceClient)
- `pytest`, `pytest-asyncio`, `respx`: Testing

## Risks & Assumptions

### Risks

**Risk 1: BinanceClient API changes**
- **Description**: BinanceClient from US-003 might have unexpected behavior
- **Mitigation**: Review BinanceClient implementation before integrating
- **Likelihood**: Low (US-003 already tested)

**Risk 2: Database session management in job context**
- **Description**: Jobs don't have FastAPI dependency injection, need to manage sessions manually
- **Mitigation**: Use context manager pattern: `with SessionLocal() as session:`
- **Likelihood**: Medium (need to verify pattern)

**Risk 3: Poetry workspace dependency resolution**
- **Description**: fetch_price package needs to depend on shared package
- **Mitigation**: Use `shared = {path = "../shared", develop = true}` in pyproject.toml
- **Likelihood**: Low (same pattern as api-service)

### Assumptions

- **Assumption 1**: BinanceClient returns List[Dict] compatible with BtcPrice model
  - Validation: Check BinanceClient return type in US-003 code
  
- **Assumption 2**: UNIQUE constraint on timestamp is sufficient for idempotency
  - Validation: Already tested in US-002 migrations
  
- **Assumption 3**: 24-hour window is optimal fetch size
  - Validation: Can adjust later via env var if needed

## Milestones

- [ ] **Milestone 1**: Job structure created, runs via `python -m fetch_price.main` (exits immediately, no logic yet)
  - **Verification**: `docker compose exec api python -m fetch_price.main` returns exit code 0

- [ ] **Milestone 2**: Core logic implemented, can fetch and save prices
  - **Verification**: Run job, check `SELECT COUNT(*) FROM btc_prices` shows new records

- [ ] **Milestone 3**: Error handling complete, logs structured messages
  - **Verification**: Simulate errors (disconnect DB), verify exit 1 + error logs

- [ ] **Milestone 4**: All tests passing, coverage ≥ 90%
  - **Verification**: `pytest --cov=fetch_price --cov-report=term-missing`

## Tasks

### Foundation (Build First)

- [ ] **Task 1.1**: Create workers/fetch_price package structure
  - **Acceptance**: Directory exists with `__init__.py`, `main.py`, `pyproject.toml`
  - **Files**: 
    - `workers/fetch_price/__init__.py`
    - `workers/fetch_price/main.py` (empty stub with `def main(): pass`)
    - `workers/fetch_price/pyproject.toml`
  - **Tests**: None yet (structure only)
  - **Effort**: XS

- [ ] **Task 1.2**: Configure Poetry dependencies for fetch_price
  - **Acceptance**: `pyproject.toml` declares dependency on shared package
  - **Files**: `workers/fetch_price/pyproject.toml`
  - **Tests**: None (configuration)
  - **Effort**: XS

- [ ] **Task 1.3**: Verify job runs inside Docker container
  - **Acceptance**: `docker compose exec api python -m fetch_price.main` exits 0
  - **Files**: None (verification only)
  - **Tests**: Manual test
  - **Effort**: XS

### Core Implementation (Build Second)

- [ ] **Task 2.1**: Implement fetch_prices() function
  - **Acceptance**: Function calls BinanceClient, returns list of price dicts for last 24h
  - **Files**: `workers/fetch_price/main.py`
  - **Tests**: `test_fetch_prices_success`, `test_fetch_prices_empty_response`
  - **Effort**: S

- [ ] **Task 2.2**: Implement filter_existing_timestamps() function
  - **Acceptance**: Query btc_prices table, return only new timestamps
  - **Files**: `workers/fetch_price/main.py`
  - **Tests**: `test_filter_existing_timestamps`
  - **Effort**: S

- [ ] **Task 2.3**: Implement save_prices() function
  - **Acceptance**: Bulk insert prices using session.add_all(), return count
  - **Files**: `workers/fetch_price/main.py`
  - **Tests**: `test_save_prices_bulk_insert`
  - **Effort**: S

- [ ] **Task 2.4**: Implement main() orchestration
  - **Acceptance**: Fetch → filter → save → log summary, return exit code
  - **Files**: `workers/fetch_price/main.py`
  - **Tests**: `test_main_end_to_end`
  - **Effort**: M

### Error Handling (Build Third)

- [ ] **Task 3.1**: Configure structured logging
  - **Acceptance**: Logger configured with format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
  - **Files**: `workers/fetch_price/main.py`
  - **Tests**: `test_logging_format` (verify log output)
  - **Effort**: S

- [ ] **Task 3.2**: Add error handling for Binance API failures
  - **Acceptance**: Catch TimeoutError, RateLimitError, InvalidSymbolError → log + exit 1
  - **Files**: `workers/fetch_price/main.py`
  - **Tests**: `test_binance_timeout`, `test_binance_rate_limit`
  - **Effort**: S

- [ ] **Task 3.3**: Add error handling for database failures
  - **Acceptance**: Catch OperationalError, IntegrityError → log + exit 1
  - **Files**: `workers/fetch_price/main.py`
  - **Tests**: `test_database_connection_error`
  - **Effort**: S

### Testing (Build Fourth)

- [ ] **Task 4.1**: Set up test fixtures (conftest.py)
  - **Acceptance**: Fixtures for mock BinanceClient, test DB session, sample price data
  - **Files**: `workers/fetch_price/tests/conftest.py`
  - **Tests**: N/A (fixture setup)
  - **Effort**: S

- [ ] **Task 4.2**: Write Gherkin Scenario 1 tests (first run inserts)
  - **Acceptance**: Test verifies 24 new records inserted on empty DB
  - **Files**: `workers/fetch_price/tests/test_main.py`
  - **Tests**: `test_first_run_inserts_new_prices`
  - **Effort**: S

- [ ] **Task 4.3**: Write Gherkin Scenario 2 tests (skip existing)
  - **Acceptance**: Test verifies only new timestamps inserted, existing skipped
  - **Files**: `workers/fetch_price/tests/test_main.py`
  - **Tests**: `test_second_run_skips_existing_prices`
  - **Effort**: S

- [ ] **Task 4.4**: Write Gherkin Scenario 3 tests (Binance timeout)
  - **Acceptance**: Test verifies error logged, exit 1
  - **Files**: `workers/fetch_price/tests/test_main.py`
  - **Tests**: `test_binance_timeout`
  - **Effort**: S

- [ ] **Task 4.5**: Write Gherkin Scenario 4 tests (DB failure)
  - **Acceptance**: Test verifies error logged, exit 1
  - **Files**: `workers/fetch_price/tests/test_main.py`
  - **Tests**: `test_database_connection_failure`
  - **Effort**: S

- [ ] **Task 4.6**: Run coverage report and fill gaps
  - **Acceptance**: Coverage ≥ 90% for fetch_price/main.py
  - **Files**: N/A (verification)
  - **Tests**: `pytest --cov=fetch_price`
  - **Effort**: S

### Integration & Polish (Build Fifth)

- [ ] **Task 5.1**: Manual end-to-end test
  - **Acceptance**: Run job in Docker, verify data in DB, run again to verify idempotency
  - **Files**: N/A (manual verification)
  - **Tests**: Manual: `docker compose exec api python -m fetch_price.main`
  - **Effort**: S

- [ ] **Task 5.2**: Code quality checks
  - **Acceptance**: `ruff check` passes, no linting errors
  - **Files**: N/A (verification)
  - **Tests**: `docker compose exec api ruff check workers/fetch_price`
  - **Effort**: XS

- [ ] **Task 5.3**: Security scan
  - **Acceptance**: No HIGH/CRITICAL vulnerabilities in dependencies
  - **Files**: N/A (verification)
  - **Tests**: `/trivy-scan` skill
  - **Effort**: XS

- [ ] **Task 5.4**: Update spec status to completed
  - **Acceptance**: Spec frontmatter updated: `status: completed`
  - **Files**: `specs/fetch-price-job.md`
  - **Tests**: N/A (documentation)
  - **Effort**: XS

## Effort Estimate

**Total Estimated Time**: 1.5 - 2 days

| Phase | Effort | Time |
|-------|--------|------|
| Foundation (Tasks 1.1-1.3) | XS | 1-2 hours |
| Core Implementation (Tasks 2.1-2.4) | M | 4-6 hours |
| Error Handling (Tasks 3.1-3.3) | S | 2-3 hours |
| Testing (Tasks 4.1-4.6) | M | 4-5 hours |
| Integration & Polish (Tasks 5.1-5.4) | S | 1-2 hours |
| **TOTAL** | | **12-18 hours** |

**Confidence**: High (all dependencies already implemented, clear requirements)

## Implementation Strategy

### Recommended Order

**Day 1 (Morning)**:
1. Tasks 1.1-1.3: Set up structure (1-2 hours)
2. Tasks 2.1-2.3: Core functions (2-3 hours)

**Day 1 (Afternoon)**:
3. Task 2.4: Main orchestration (2 hours)
4. Tasks 3.1-3.3: Error handling (2-3 hours)

**Day 2 (Morning)**:
5. Tasks 4.1-4.6: Full test suite (4-5 hours)

**Day 2 (Afternoon)**:
6. Tasks 5.1-5.4: Integration, QA, polish (1-2 hours)

### Testing Approach

**Test-Driven Development (TDD)**:
- Write test first (red)
- Implement minimal code to pass (green)
- Refactor (clean)

**Order**:
1. Unit tests for individual functions (fetch, filter, save)
2. Integration test for main() orchestration
3. Error path tests (mocked failures)
4. Idempotency test (run twice)

### Key Implementation Notes

**BinanceClient Integration**:
```python
from workers.binance_client.client import BinanceClient

async def fetch_prices():
    client = BinanceClient()
    candles = await client.get_ohlcv(symbol="BTCUSDT", interval="1h", limit=24)
    return candles
```

**Database Session Management**:
```python
from shared.db.database import SessionLocal
from shared.db.models import BtcPrice

def save_prices(prices: List[Dict], session):
    btc_prices = [BtcPrice(**price) for price in prices]
    session.add_all(btc_prices)
    session.commit()
    return len(btc_prices)
```

**Filtering Existing Timestamps**:
```python
def filter_existing_timestamps(prices: List[Dict], session):
    timestamps = [p["timestamp"] for p in prices]
    existing = session.query(BtcPrice.timestamp).filter(
        BtcPrice.timestamp.in_(timestamps)
    ).all()
    existing_set = {t[0] for t in existing}
    return [p for p in prices if p["timestamp"] not in existing_set]
```

**Main Orchestration**:
```python
import asyncio
import sys
import logging

logger = logging.getLogger(__name__)

async def main():
    try:
        # Fetch
        prices = await fetch_prices()
        logger.info(f"Fetched {len(prices)} candles from Binance")
        
        # Filter
        with SessionLocal() as session:
            new_prices = filter_existing_timestamps(prices, session)
            skipped = len(prices) - len(new_prices)
            
            # Save
            if new_prices:
                inserted = save_prices(new_prices, session)
                logger.info(f"Skipped {skipped}, inserted {inserted}")
            else:
                logger.info(f"No new prices to insert (all {len(prices)} already exist)")
        
        return 0
    except Exception as e:
        logger.error(f"Job failed: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
```

## Verification Checklist

Before marking this feature as complete:

- [ ] All 16 tasks completed
- [ ] All 4 Gherkin scenarios have passing tests
- [ ] Coverage report shows ≥ 90% for fetch_price/main.py
- [ ] Manual test: `docker compose exec api python -m fetch_price.main` succeeds
- [ ] Manual test: Run job twice, verify idempotency
- [ ] Lint passes: `ruff check workers/fetch_price`
- [ ] Security scan clean: No HIGH/CRITICAL vulnerabilities
- [ ] Logs show clear summary: "Skipped X, inserted Y"
- [ ] Job completes in < 5 seconds
- [ ] Code review approved
- [ ] PR merged to main
- [ ] GitHub Issue #5 closed
- [ ] Spec updated: `status: completed`
