# Implementation Plan: Binance API Client

**Spec**: [binance-api-client.md](./binance-api-client.md)  
**Created**: 2026-05-16  
**Status**: completed  
**User Story**: US-003 (#4)

## Components

### 1. Project Structure
- **Purpose**: Set up workers/fetch_price package structure
- **Files**: 
  - `workers/fetch_price/__init__.py`
  - `workers/fetch_price/pyproject.toml` (Poetry package)
  - `workers/fetch_price/tests/__init__.py`
  - `workers/fetch_price/tests/conftest.py`
- **Effort**: XS (30 min)

### 2. Custom Exceptions
- **Purpose**: Define domain-specific exceptions for API errors
- **Files**: `workers/fetch_price/exceptions.py`
- **Effort**: XS (30 min)

### 3. BinanceClient Class
- **Purpose**: Core async client for fetching OHLCV data
- **Files**: `workers/fetch_price/binance_client.py`
- **Key Methods**:
  - `__init__(base_url, timeout)` - Initialize httpx client
  - `fetch_ohlcv(symbol, interval, limit)` - Main API call
  - `_parse_candle(raw_data)` - Parse JSON to tuple
  - `_validate_params(symbol, interval, limit)` - Input validation
- **Effort**: M (4 hours)

### 4. Unit Tests
- **Purpose**: Test all scenarios and edge cases
- **Files**: 
  - `workers/fetch_price/tests/test_binance_client.py` (main tests)
  - `workers/fetch_price/tests/test_exceptions.py` (exception tests)
- **Test Categories**:
  - Happy path (1 candle, 168 candles)
  - Error handling (timeout, rate limit, invalid symbol)
  - ZOMBIES edge cases (0, 1, 1000, 1001)
  - Data parsing (timestamp conversion, float parsing)
- **Effort**: M (4 hours)

## Dependencies

### Build Order
1. **Project Structure** (foundation)
   - Create package directories
   - Set up Poetry configuration
   - No external dependencies

2. **Custom Exceptions** (used by client)
   - Define exception classes
   - Depends on: nothing

3. **BinanceClient Class** (core logic)
   - Implement API client
   - Depends on: Custom Exceptions

4. **Unit Tests** (verification)
   - Write all test scenarios
   - Depends on: BinanceClient, Custom Exceptions

### External Dependencies
- **httpx**: Already in project dependencies (for async HTTP)
- **respx**: Need to add for mocking httpx in tests
- **pytest**: Already in project
- **pytest-asyncio**: Already in project for async tests

### New Dependencies to Add
Add to `workers/fetch_price/pyproject.toml`:
```toml
[tool.poetry.dependencies]
python = "^3.13"
httpx = "^0.28.1"
shared = {path = "../shared", develop = true}

[tool.poetry.group.dev.dependencies]
pytest = "^8.3.4"
pytest-asyncio = "^0.25.2"
respx = "^0.21.1"  # NEW - for mocking httpx
pytest-cov = "^6.0.0"
```

## Risks & Assumptions

### Risks

**Risk 1: Binance API format changes**
- **Impact**: Medium - Our parser would break
- **Likelihood**: Low - Binance maintains backwards compatibility
- **Mitigation**: 
  - Add version check in future iteration
  - Use try/except when parsing fields
  - Log warnings if unexpected fields appear

**Risk 2: Rate limiting in development**
- **Impact**: Low - Tests would fail intermittently
- **Likelihood**: Very Low - We're well under limits (tests use mocks)
- **Mitigation**: 
  - All tests use `respx` to mock API (no real calls)
  - Manual testing: limit to 1-2 calls per test run

**Risk 3: Timezone confusion**
- **Impact**: Medium - Wrong timestamps could corrupt data
- **Likelihood**: Medium - Easy to forget UTC conversion
- **Mitigation**: 
  - Always convert Unix ms to UTC datetime
  - Add explicit test for timezone (must be UTC)
  - Document in docstrings

### Assumptions

**Assumption 1**: Binance public API remains free and unauthenticated
- **Validation**: Check Binance docs (currently true as of 2026-05-16)
- **Fallback**: Would need to implement API key auth in future

**Assumption 2**: `httpx` is already installed in Docker container
- **Validation**: Check `docker compose exec api pip list | grep httpx`
- **Fallback**: Add to shared/pyproject.toml if missing

**Assumption 3**: Tests can run inside container without network access
- **Validation**: Use `respx` to mock all HTTP calls
- **Fallback**: Not applicable - mocking is requirement

## Milestones

- [ ] **M1: Structure Ready** - Package created, can import `fetch_price` module
- [ ] **M2: Client Implemented** - Can call `fetch_ohlcv()` and get data back
- [ ] **M3: Error Handling Complete** - All exceptions raised correctly
- [ ] **M4: All Tests Pass** - 100% of Gherkin scenarios passing
- [ ] **M5: Coverage >90%** - Test coverage meets target
- [ ] **M6: Manual Verification** - Can fetch real data from Binance API

## Tasks

### Foundation (Build First)

#### Task 1: Set up package structure
- **Acceptance**: 
  - `workers/fetch_price/` directory exists
  - `pyproject.toml` configured with dependencies
  - Can run `pytest workers/fetch_price/tests/` without errors (even if no tests yet)
- **Files**: 
  - `workers/fetch_price/__init__.py`
  - `workers/fetch_price/pyproject.toml`
  - `workers/fetch_price/tests/__init__.py`
  - `workers/fetch_price/tests/conftest.py`
- **Tests**: N/A (structural task)
- **Effort**: XS (30 min)

#### Task 2: Define custom exceptions
- **Acceptance**:
  - Can import `from fetch_price.exceptions import BinanceAPIError, RateLimitError, InvalidSymbolError`
  - `RateLimitError` has `retry_after` attribute
  - All exceptions inherit from `BinanceAPIError`
- **Files**: `workers/fetch_price/exceptions.py`
- **Tests**: `workers/fetch_price/tests/test_exceptions.py`
  - Test exception inheritance
  - Test `RateLimitError` with/without retry_after
- **Effort**: XS (30 min)

### Core Logic (Build Second)

#### Task 3: Implement BinanceClient.__init__
- **Acceptance**:
  - Can create `client = BinanceClient()`
  - Can create `client = BinanceClient(base_url="https://custom.api", timeout=5.0)`
  - Client has httpx.AsyncClient initialized
- **Files**: `workers/fetch_price/binance_client.py`
- **Tests**: `test_binance_client.py::test_client_initialization`
- **Effort**: S (1 hour)

#### Task 4: Implement parameter validation
- **Acceptance**:
  - `limit=0` raises `ValueError("limit must be between 1 and 1000")`
  - `limit=1001` raises `ValueError("limit must be between 1 and 1000")`
  - `symbol=""` raises `ValueError("symbol cannot be empty")`
  - Valid params pass without error
- **Files**: `workers/fetch_price/binance_client.py` (add `_validate_params` method)
- **Tests**: `test_binance_client.py::test_parameter_validation`
  - Test ZOMBIES: Zero (0), Boundary (1001), Empty string
- **Effort**: S (1 hour)

#### Task 5: Implement API call and response parsing
- **Acceptance**:
  - Can call `await client.fetch_ohlcv(symbol="BTCUSDT", interval="1h", limit=1)`
  - Returns `List[Tuple[datetime, float, float, float, float, float]]`
  - Timestamp is UTC datetime (not Unix ms)
  - OHLC values are floats
  - Candles ordered by timestamp descending (newest first)
- **Files**: `workers/fetch_price/binance_client.py` (implement `fetch_ohlcv` and `_parse_candle`)
- **Tests**: `test_binance_client.py::test_fetch_latest_candle`, `test_fetch_multiple_candles`
  - Mock API response with `respx`
  - Verify data structure
  - Verify timestamp conversion
  - Verify ordering
- **Effort**: M (3 hours)

#### Task 6: Implement error handling
- **Acceptance**:
  - Timeout (10s) raises `TimeoutError("Binance API timeout")`
  - 429 response raises `RateLimitError` with `retry_after` from headers
  - 400 response for invalid symbol raises `InvalidSymbolError`
  - 500 response raises `BinanceAPIError`
  - Network errors raise `BinanceAPIError` with context
- **Files**: `workers/fetch_price/binance_client.py` (add error handling in `fetch_ohlcv`)
- **Tests**: `test_binance_client.py` - Error scenarios:
  - `test_timeout_handling`
  - `test_rate_limit_handling`
  - `test_invalid_symbol_handling`
  - `test_server_error_handling`
  - `test_network_error_handling`
- **Effort**: M (3 hours)

### Testing & Verification (Build Third)

#### Task 7: Complete test suite
- **Acceptance**:
  - All 5 Gherkin scenarios have passing tests
  - All ZOMBIES edge cases covered
  - Test coverage ≥90%
  - All tests use `respx` (no real API calls)
  - Tests run in <10 seconds
- **Files**: `workers/fetch_price/tests/test_binance_client.py` (complete all scenarios)
- **Tests**: Run `pytest --cov=fetch_price --cov-report=term-missing`
- **Effort**: S (2 hours)

#### Task 8: Manual verification with real API
- **Acceptance**:
  - Can fetch real data from Binance in Docker container
  - Response time <5s for limit=168
  - Data looks correct (prices are reasonable)
  - No errors in logs
- **Files**: N/A (manual testing)
- **Tests**: Create `workers/fetch_price/manual_test.py` script:
  ```python
  import asyncio
  from binance_client import BinanceClient
  
  async def main():
      client = BinanceClient()
      data = await client.fetch_ohlcv(limit=168)
      print(f"Fetched {len(data)} candles")
      print(f"Latest: {data[0]}")
  
  asyncio.run(main())
  ```
- **Effort**: XS (30 min)

## Effort Estimate

**Total Estimated Time**: 1.5 - 2 days

| Phase | Tasks | Effort |
|-------|-------|--------|
| Foundation | Task 1-2 | 1 hour |
| Core Logic | Task 3-6 | 8 hours |
| Testing | Task 7-8 | 2.5 hours |
| **Buffer** | Debugging, code review | 2 hours |
| **Total** | 8 tasks | **13.5 hours (~2 days)** |

## Execution Strategy

### Approach 1: TDD (Recommended)
For each task:
1. Write test first (will fail)
2. Implement minimum code to pass test
3. Refactor if needed
4. Move to next test

**Pros**: Ensures 100% test coverage, catches bugs early
**Cons**: Slightly slower initially

### Approach 2: Implementation-first
1. Implement all of BinanceClient
2. Write tests after
3. Fix bugs found by tests

**Pros**: Faster to "working" code
**Cons**: May miss edge cases, lower coverage

**Recommendation**: Use TDD (Approach 1) - aligns with project philosophy "Every Gherkin criterion MUST have an automated test"

## Next Steps

After approval of this plan:

1. **Phase 3: TASKS** - Confirm task breakdown (already in this plan)
2. **Phase 4: IMPLEMENT** - Execute tasks in order
   - Start with Task 1 (structure)
   - Proceed through Task 8 (manual verification)
   - Update GitHub Issue #4 as tasks complete

## Notes

- All development happens inside Docker container (`docker compose exec api ...`)
- Tests must be run inside container: `docker compose exec api pytest workers/fetch_price/tests/`
- Manual testing script can be run: `docker compose exec api python -m fetch_price.manual_test`
- Future US-004 will use this client to store data in database
