# Implementation Plan: API Endpoint for BTC Prices

**Spec**: [api-prices-endpoint.md](./api-prices-endpoint.md)  
**Created**: 2026-05-16  
**Status**: approved  
**Issue**: #6 (US-005)

## Overview

Implement a REST API endpoint that queries the `btc_prices` table and returns JSON responses. This is a straightforward CRUD endpoint with no complex business logic, making it ideal for TDD (Test-Driven Development).

**Total Estimated Effort**: 4-6 hours (S - Small)

---

## Components

### 1. Pydantic Response Model
**Purpose**: Define the JSON response schema for price data  
**Files**: `api-service/api/models/responses.py` (NEW)  
**Effort**: XS (30 min)

**What to build**:
- Create `BtcPriceResponse` Pydantic model
- Map SQLAlchemy `Decimal` fields to `float` for JSON serialization
- Enable `from_attributes=True` for ORM compatibility
- Add docstrings with example response

**Why separate file**: Keep models separate from routers for better organization and reusability.

### 2. Prices Router
**Purpose**: Handle GET /api/prices endpoint logic  
**Files**: `api-service/api/routers/prices.py` (NEW)  
**Effort**: S (1-2 hours)

**What to build**:
- Create FastAPI router with prefix `/api`
- Implement `GET /prices` endpoint
- Add query parameter `limit` with Pydantic validation (default=24, min=1, max=1000)
- Inject database session via `Depends(get_db)`
- Query `btc_prices` table ordered by timestamp DESC
- Convert ORM models to Pydantic responses
- Handle empty results gracefully (return `[]`)

**Key implementation details**:
```python
@router.get("/prices", response_model=list[BtcPriceResponse])
async def get_prices(
    limit: int = Query(default=24, ge=1, le=1000),
    db: Session = Depends(get_db)
) -> list[BtcPriceResponse]:
    # Query database
    # Return response
```

### 3. Router Registration
**Purpose**: Register prices router in main FastAPI app  
**Files**: `api-service/api/main.py` (MODIFY)  
**Effort**: XS (15 min)

**What to build**:
- Import prices router
- Add `app.include_router(prices_router)`
- Ensure router is registered before app starts

### 4. Integration Tests
**Purpose**: Verify endpoint behavior with real database  
**Files**: `api-service/tests/test_prices.py` (NEW)  
**Effort**: M (2-3 hours)

**What to build**:
- 8 test cases covering all Gherkin scenarios
- Pytest fixtures for test data (sample_prices)
- Test database session with automatic cleanup
- httpx AsyncClient for API calls

**Test cases**:
1. ✅ Default limit (24)
2. ✅ Custom limit (168)
3. ✅ Empty table
4. ✅ Invalid limit (negative)
5. ✅ Invalid limit (zero)
6. ✅ Invalid limit (> 1000)
7. ✅ Ordering verification
8. ✅ Response schema validation

### 5. Manual Verification & Performance Testing
**Purpose**: Verify endpoint works locally and in Railway  
**Files**: N/A (manual testing)  
**Effort**: S (1 hour)

**What to verify**:
- Local: `docker compose up` → `curl http://localhost:8000/api/prices`
- Railway: Push to main → verify deployment → `curl https://<domain>/api/prices`
- Performance: Populate DB with 10k records, measure response times

---

## Dependencies

### Build Order (Sequential)

```
1. Pydantic Response Model (foundation)
   ↓
2. Prices Router (depends on response model)
   ↓
3. Router Registration (depends on prices router)
   ↓
4. Integration Tests (depends on all above)
   ↓
5. Manual Verification (depends on tests passing)
```

### External Dependencies (Already Available)

| Dependency | Purpose | Status |
|------------|---------|--------|
| FastAPI | Web framework | ✅ Installed |
| SQLAlchemy | ORM for DB queries | ✅ Installed |
| Pydantic | Request/response validation | ✅ Installed |
| shared.db.models.BtcPrice | ORM model | ✅ Exists (US-002) |
| shared.db.database.get_db | DB session dependency | ✅ Exists (US-001) |
| pytest + httpx | Testing | ✅ Installed |

**No new dependencies required** ✅

---

## Risks & Assumptions

### Risks

**Risk 1: Decimal to Float Precision Loss**
- **Description**: SQLAlchemy uses `Decimal` for price precision, but JSON only supports `float`. Conversion might lose precision for very small or very large numbers.
- **Impact**: Low — Bitcoin prices are in the range $20k-$100k with 8 decimal places, which float64 handles fine.
- **Mitigation**: Pydantic automatically converts Decimal to float. Verify in tests that precision is acceptable (8 decimals preserved).

**Risk 2: Performance with Large Result Sets**
- **Description**: Query for `limit=1000` might be slow if database has millions of records.
- **Impact**: Low — Current data volume is small (hours of data), and `timestamp` column is indexed.
- **Mitigation**: Performance test with 10k records. If needed, add pagination in future iteration.

**Risk 3: Timezone Confusion**
- **Description**: Database stores timestamps in UTC, but clients might expect local time.
- **Impact**: Low — ISO 8601 format includes timezone info, so clients can convert.
- **Mitigation**: Document in API response that timestamps are in UTC. Frontend handles conversion.

### Assumptions

✅ **Database has data**: Assumes `fetch-price` job (US-004) has run at least once and populated the table.  
✅ **Single source**: Assumes all prices come from one source (CoinGecko). No need to filter by `source` field yet.  
✅ **No authentication**: API is public (no auth required for this iteration).  
✅ **No rate limiting**: Internal dashboard only, no need for rate limiting yet.  
✅ **No pagination**: Simple limit-based query is sufficient (no offset/cursor pagination).

---

## Milestones

### Milestone 1: Foundation (Models + Router)
**Goal**: Basic endpoint structure in place  
**Verification**: 
- [ ] Pydantic response model defined
- [ ] Prices router file created with endpoint skeleton
- [ ] Router registered in main.py
- [ ] Endpoint accessible (returns empty array if no data)

**Checkpoint**: `curl http://localhost:8000/api/prices` returns `[]`

---

### Milestone 2: Database Integration
**Goal**: Endpoint queries database and returns data  
**Verification**:
- [ ] Database query implemented (ORDER BY timestamp DESC LIMIT N)
- [ ] Manual insertion of test data works
- [ ] Endpoint returns actual data from database

**Checkpoint**: Insert 5 records manually → `curl http://localhost:8000/api/prices?limit=5` returns 5 records

---

### Milestone 3: Full Test Coverage
**Goal**: All Gherkin scenarios covered with automated tests  
**Verification**:
- [ ] All 8 test cases implemented
- [ ] All tests passing
- [ ] Coverage ≥ 95%
- [ ] Lint checks pass

**Checkpoint**: `docker compose exec api pytest api-service/tests/test_prices.py -v` → all green

---

### Milestone 4: Production Deployment
**Goal**: Endpoint deployed and verified in Railway  
**Verification**:
- [ ] Code pushed to main branch
- [ ] Railway deployment successful
- [ ] Endpoint accessible in production
- [ ] Response validated in production

**Checkpoint**: `curl https://<railway-domain>/api/prices` returns valid JSON

---

## Tasks

### Phase 1: Foundation (Build First)

- [ ] **Task 1.1: Create Pydantic response model**
  - **Acceptance**: `BtcPriceResponse` model defined with all OHLCV fields
  - **Files**: `api-service/api/models/__init__.py`, `api-service/api/models/responses.py`
  - **Tests**: Type checking (if mypy enabled)
  - **Effort**: XS (30 min)
  - **Details**:
    - Create `api-service/api/models/` directory
    - Define `BtcPriceResponse` with fields: timestamp, open, high, low, close, volume, source
    - Use `float` type for all price fields (Pydantic converts Decimal automatically)
    - Add `Config` class with `from_attributes = True`
    - Add docstring with example JSON response

- [ ] **Task 1.2: Create prices router skeleton**
  - **Acceptance**: Router file exists with basic endpoint structure
  - **Files**: `api-service/api/routers/prices.py`
  - **Tests**: Manual curl test (returns empty list)
  - **Effort**: XS (30 min)
  - **Details**:
    - Create `prices.py` in routers directory
    - Define router with prefix `/api`
    - Implement `GET /prices` endpoint (returns `[]` for now)
    - Add query parameter `limit` with Pydantic Query validation

- [ ] **Task 1.3: Register prices router**
  - **Acceptance**: Router accessible via main FastAPI app
  - **Files**: `api-service/api/main.py`
  - **Tests**: Manual curl test to `/api/prices`
  - **Effort**: XS (15 min)
  - **Details**:
    - Import prices router in main.py
    - Add `app.include_router(prices_router)`
    - Start local dev server, verify endpoint responds

---

### Phase 2: Database Integration (Build Second)

- [ ] **Task 2.1: Implement database query**
  - **Acceptance**: Endpoint queries `btc_prices` and returns data
  - **Files**: `api-service/api/routers/prices.py`
  - **Tests**: Manual test with sample data
  - **Effort**: S (1 hour)
  - **Details**:
    - Inject DB session via `Depends(get_db)`
    - Query: `db.query(BtcPrice).order_by(BtcPrice.timestamp.desc()).limit(limit).all()`
    - Convert ORM models to Pydantic responses
    - Return list of BtcPriceResponse

- [ ] **Task 2.2: Test with real data**
  - **Acceptance**: Endpoint returns valid data from database
  - **Files**: N/A (manual verification)
  - **Tests**: Insert test data, verify response
  - **Effort**: XS (30 min)
  - **Details**:
    - Start local environment: `docker compose up -d`
    - Insert 10 sample records via Python shell or SQL
    - Test: `curl http://localhost:8000/api/prices?limit=10`
    - Verify: JSON array with 10 items, ordered newest-first

---

### Phase 3: Test Coverage (Build Third)

- [ ] **Task 3.1: Set up test fixtures**
  - **Acceptance**: Reusable fixtures for database and test client
  - **Files**: `api-service/tests/conftest.py` (MODIFY)
  - **Tests**: Fixtures work independently
  - **Effort**: S (30 min)
  - **Details**:
    - Add `sample_prices` fixture (creates N BtcPrice records)
    - Ensure `db_session` fixture rolls back after each test
    - Verify `test_client` fixture works with API

- [ ] **Task 3.2: Write integration tests (Scenarios 1-4)**
  - **Acceptance**: 4 core Gherkin scenarios covered
  - **Files**: `api-service/tests/test_prices.py`
  - **Tests**: 4 tests passing
  - **Effort**: M (1.5 hours)
  - **Details**:
    - Test 1: Default limit (24)
    - Test 2: Custom limit (168)
    - Test 3: Empty table
    - Test 4: Invalid limit (negative)

- [ ] **Task 3.3: Write edge case tests (Scenarios 5-8)**
  - **Acceptance**: All edge cases covered
  - **Files**: `api-service/tests/test_prices.py`
  - **Tests**: 8 tests passing total
  - **Effort**: M (1 hour)
  - **Details**:
    - Test 5: Invalid limit (zero)
    - Test 6: Invalid limit (> 1000)
    - Test 7: Ordering verification
    - Test 8: Response schema validation

- [ ] **Task 3.4: Verify coverage and lint**
  - **Acceptance**: Coverage ≥ 95%, lint passes
  - **Files**: N/A
  - **Tests**: Coverage report, ruff check
  - **Effort**: XS (30 min)
  - **Details**:
    - Run: `docker compose exec api pytest --cov=api --cov-report=term-missing`
    - Run: `docker compose exec api ruff check api-service/`
    - Fix any issues

---

### Phase 4: Deployment & Verification (Build Last)

- [ ] **Task 4.1: Local performance test**
  - **Acceptance**: Response times meet performance requirements
  - **Files**: N/A (manual test)
  - **Tests**: Measure response time with 10k records
  - **Effort**: S (30 min)
  - **Details**:
    - Populate database with 10,000 records (script or manual)
    - Measure: `time curl http://localhost:8000/api/prices` (should be < 100ms)
    - Measure: `time curl http://localhost:8000/api/prices?limit=1000` (should be < 500ms)

- [ ] **Task 4.2: Deploy to Railway**
  - **Acceptance**: Code deployed to production
  - **Files**: N/A (git push)
  - **Tests**: Railway build success
  - **Effort**: XS (15 min)
  - **Details**:
    - Commit all changes
    - Push to main: `git push origin main`
    - Monitor Railway dashboard for deployment status
    - Verify build succeeds

- [ ] **Task 4.3: Verify production endpoint**
  - **Acceptance**: Endpoint works in Railway
  - **Files**: N/A (manual verification)
  - **Tests**: Curl production endpoint
  - **Effort**: XS (15 min)
  - **Details**:
    - Get Railway domain from dashboard
    - Test: `curl https://<domain>/api/prices`
    - Verify: Valid JSON response
    - Test with limit: `curl https://<domain>/api/prices?limit=5`

- [ ] **Task 4.4: Update documentation and close issue**
  - **Acceptance**: All Definition of Done items checked
  - **Files**: Spec file, GitHub issue
  - **Tests**: N/A
  - **Effort**: XS (15 min)
  - **Details**:
    - Update spec status to `completed`
    - Check all success criteria in spec
    - Update US-005 GitHub issue with completion summary
    - Close issue

---

## Effort Estimate

**Total Estimated Time**: 4-6 hours (S - Small)

| Phase | Effort | Duration |
|-------|--------|----------|
| Foundation | XS + XS + XS | 1-1.5 hours |
| Database Integration | S + XS | 1.5 hours |
| Test Coverage | S + M + M + XS | 3-3.5 hours |
| Deployment & Verification | S + XS + XS + XS | 1-1.5 hours |
| **TOTAL** | **Small** | **4-6 hours** |

**Effort Legend**:
- XS: < 30 min
- S: 30 min - 2 hours
- M: 2-4 hours
- L: 4-8 hours (1 day)
- XL: > 8 hours (multiple days)

---

## Development Strategy

### Test-Driven Development (TDD)

This feature is **ideal for TDD** because:
1. Requirements are clear (Gherkin scenarios)
2. No complex business logic (just CRUD)
3. Easy to test (database query + JSON response)

**Recommended flow**:
1. Write test first (Red)
2. Implement minimal code to pass (Green)
3. Refactor if needed (Refactor)
4. Repeat

**Example TDD cycle**:
```python
# 1. Write test (RED)
def test_get_prices_default_limit():
    response = client.get("/api/prices")
    assert response.status_code == 200
    assert len(response.json()) == 24

# 2. Implement (GREEN)
@router.get("/prices")
async def get_prices(db: Session = Depends(get_db)):
    prices = db.query(BtcPrice).order_by(...).limit(24).all()
    return prices

# 3. Refactor (if needed)
# Add query param, response model, etc.
```

### Container-First Development

**All commands must run inside Docker containers**:

```bash
# Start environment
docker compose up -d

# Run tests
docker compose exec api pytest api-service/tests/test_prices.py -v

# Run specific test
docker compose exec api pytest api-service/tests/test_prices.py::test_get_prices_default_limit -v

# Check coverage
docker compose exec api pytest --cov=api --cov-report=term-missing

# Lint
docker compose exec api ruff check api-service/

# Manual test
curl http://localhost:8000/api/prices
```

---

## Quality Gates

Before marking a task as complete, verify:

✅ **Code Quality**:
- [ ] Lint passes (`ruff check`)
- [ ] Type hints present (if using mypy)
- [ ] Docstrings present for functions
- [ ] No commented-out code

✅ **Testing**:
- [ ] All tests passing
- [ ] Coverage ≥ 95%
- [ ] Tests run inside container
- [ ] Test data cleaned up after each test

✅ **Functionality**:
- [ ] Manual verification successful
- [ ] Meets all acceptance criteria
- [ ] No regressions (existing tests still pass)

✅ **Documentation**:
- [ ] Docstrings added
- [ ] API example in docstring
- [ ] Success criteria checked off in spec

---

## Rollback Plan

If deployment fails or bugs are discovered:

1. **Revert code**: `git revert <commit-hash>`
2. **Redeploy**: Railway auto-deploys on push to main
3. **Hotfix**: Create fix → test locally → push

**Risk**: Low — This is a new endpoint (not modifying existing code), so rollback is straightforward.

---

## Post-Implementation

### What's Next (Future Iterations)

Features explicitly out of scope for this iteration but may be added later:

- **Pagination**: Offset/cursor-based pagination for large datasets
- **Date range filtering**: `GET /api/prices?from=2024-01-01&to=2024-01-31`
- **Source filtering**: `GET /api/prices?source=coingecko`
- **Aggregations**: Daily average, weekly high/low, etc.
- **WebSocket streaming**: Real-time price updates
- **Rate limiting**: Throttle requests for public API
- **Authentication**: API key or JWT for private access

### Integration Points

This endpoint enables:
- **US-011**: Dashboard price history visualization
- **US-012**: Price chart component
- **Future**: External API consumers, mobile apps, etc.
