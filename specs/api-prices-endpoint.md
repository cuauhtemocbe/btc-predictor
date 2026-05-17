---
title: API Endpoint for BTC Prices
status: approved
created: 2026-05-16
updated: 2026-05-16
issue: #6
iteration: 3
user_story: US-005
---

# API Endpoint for BTC Prices

## Objective

Create a REST API endpoint (`GET /api/prices`) that returns recent Bitcoin OHLCV price data from the database, enabling the dashboard and external consumers to display historical price charts and tables.

## Context

**Problem**: Frontend developers need access to historical Bitcoin price data to build the dashboard. Currently, prices are being fetched and stored in the `btc_prices` table by the `fetch-price` cron job (US-004), but there's no way to retrieve this data via the API.

**User Need**: As a frontend developer, I want a simple, fast endpoint that returns the last N hours of BTC prices in JSON format, ordered newest-first, so I can render price charts without implementing custom database queries.

**Business Value**: This endpoint is a foundational building block for:
- Dashboard price history visualization (US-011)
- External API consumers (future integrations)
- Model training data validation (dev/debugging)

**Dependencies**: 
- ✅ US-002: `btc_prices` table exists and is populated
- ✅ US-004: `fetch-price` cron job populating data

## Requirements

### Functional Requirements

- [ ] Endpoint path: `GET /api/prices`
- [ ] Default behavior: return last 24 hours of prices (24 records)
- [ ] Query parameter `limit` to control how many records to return
- [ ] Response format: JSON array of price objects
- [ ] Each price object includes: `timestamp`, `open`, `high`, `low`, `close`, `volume`, `source`
- [ ] Results ordered by `timestamp DESC` (newest first)
- [ ] Empty table returns empty array `[]` (not 404)
- [ ] Decimal values serialized as floats in JSON

### Non-Functional Requirements

- [ ] **Performance**: Response time < 100ms for default limit (24 records)
- [ ] **Performance**: P95 response time < 500ms for max limit (1000 records)
- [ ] **Validation**: Limit must be positive integer (1 to 1000)
- [ ] **Validation**: Invalid limit returns 422 Unprocessable Entity with clear error message
- [ ] **Scalability**: Endpoint uses indexed query (timestamp column is indexed)
- [ ] **API Design**: Follows REST conventions (GET for read-only, 200 for success)

## Architecture

### Components

```
api-service/
├── api/
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── routes.py (existing hello endpoint)
│   │   └── prices.py (NEW - prices endpoint)
│   └── main.py (register prices router)
└── tests/
    └── test_prices.py (NEW - endpoint tests)
```

### Data Flow

```
Client Request → FastAPI → Prices Router → SQLAlchemy Query → PostgreSQL
                    ↓
                Response (JSON)
```

1. Client sends `GET /api/prices?limit=24`
2. FastAPI validates query parameters (Pydantic)
3. Prices router gets DB session via `Depends(get_db)`
4. Execute SQLAlchemy query: `SELECT * FROM btc_prices ORDER BY timestamp DESC LIMIT 24`
5. Convert SQLAlchemy models to Pydantic response models
6. FastAPI serializes to JSON and returns

### Data Model

**Request Query Parameters** (Pydantic validation):
```python
limit: int = Query(default=24, ge=1, le=1000)
```

**Response Schema** (Pydantic model):
```python
class BtcPriceResponse(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    
    class Config:
        from_attributes = True  # Enable ORM mode
```

**Database Query**:
```python
db.query(BtcPrice)\
  .order_by(BtcPrice.timestamp.desc())\
  .limit(limit)\
  .all()
```

### External Dependencies

- **FastAPI**: Web framework (already in project)
- **SQLAlchemy**: ORM for database queries (already in project)
- **Pydantic**: Request/response validation (already in project)
- **shared.db.models.BtcPrice**: ORM model (already exists)
- **shared.db.database.get_db**: DB session dependency (already exists)

## User Stories

Reference: **US-005** — Endpoint GET /api/prices?limit=168

**As** a frontend developer  
**I want** an API endpoint that returns recent BTC prices  
**In order to** display price history in the dashboard

**Acceptance Criteria** (Gherkin):

```gherkin
Feature: API endpoint for BTC prices

  Scenario: Fetch last 24 prices (default)
    Given the btc_prices table has 100 records
    When I send GET /api/prices
    Then the response status is 200 OK
    And the response body is a JSON array with 24 items (default limit)
    And each item has keys: timestamp, open, high, low, close, volume, source
    And items are ordered by timestamp DESC (newest first)

  Scenario: Fetch last 168 prices (1 week)
    Given the btc_prices table has 500 records
    When I send GET /api/prices?limit=168
    Then the response body is a JSON array with 168 items
    And items are ordered by timestamp DESC

  Scenario: Empty table returns empty array
    Given the btc_prices table is empty
    When I send GET /api/prices
    Then the response status is 200 OK
    And the response body is an empty JSON array []

  Scenario: Invalid limit parameter
    Given I send GET /api/prices?limit=-1
    Then the response status is 422 Unprocessable Entity
    And the error message indicates "limit must be positive"
```

## Testing Strategy

### Unit Tests
**Not applicable** — this endpoint has no business logic to unit test. It's a thin layer over a database query.

### Integration Tests
**Primary focus** — test the endpoint with a real database (test container).

**Test file**: `api-service/tests/test_prices.py`

**Test cases** (maps 1:1 to Gherkin scenarios):
1. `test_get_prices_default_limit()` — Default 24 records
2. `test_get_prices_custom_limit()` — Custom limit (168)
3. `test_get_prices_empty_table()` — Empty table returns `[]`
4. `test_get_prices_invalid_limit_negative()` — Negative limit returns 422
5. `test_get_prices_invalid_limit_zero()` — Zero limit returns 422
6. `test_get_prices_invalid_limit_exceeds_max()` — Limit > 1000 returns 422
7. `test_get_prices_ordering()` — Verify DESC timestamp order
8. `test_get_prices_response_schema()` — Verify all fields present and correct types

**Test fixtures** (pytest):
- `db_session`: Database session with automatic rollback
- `test_client`: FastAPI test client (`httpx.AsyncClient`)
- `sample_prices`: Insert N price records for testing

**Coverage target**: 100% (simple endpoint, should be fully testable)

### E2E Tests
**Not in this iteration** — E2E tests with dashboard UI will come in US-011 (Dashboard).

### Performance Tests
**Manual verification** (not automated):
- Populate database with 10,000 records
- Measure response time for `limit=24` (should be < 100ms)
- Measure response time for `limit=1000` (should be < 500ms)

## Boundaries & Constraints

### In Scope
- ✅ Read-only endpoint (GET)
- ✅ Return last N prices
- ✅ Query parameter validation
- ✅ JSON serialization of Decimal fields
- ✅ Comprehensive test coverage

### Out of Scope
- ❌ Pagination (offset/cursor-based) — not needed for this iteration
- ❌ Filtering by date range — not in US-005 requirements
- ❌ Filtering by source — assume single source for now
- ❌ Aggregations (daily average, etc.) — future feature
- ❌ WebSocket streaming — future feature
- ❌ Rate limiting — not needed for now (internal dashboard only)
- ❌ Authentication — API is public for now

### Technical Constraints
- **Database**: PostgreSQL (via shared package)
- **Python version**: 3.13
- **Framework**: FastAPI
- **Decimal handling**: SQLAlchemy stores as NUMERIC(18,8), serialize as float in JSON
- **Testing**: All commands executed inside Docker containers (`docker compose exec api pytest`)

## Success Criteria

- [ ] Endpoint accessible at `GET /api/prices`
- [ ] All 4 Gherkin scenarios have passing automated tests
- [ ] Test coverage ≥ 95% for new code
- [ ] Response time < 100ms for default limit (24 records) with 10k records in DB
- [ ] Lint checks pass (`ruff check`)
- [ ] Type checks pass (if mypy enabled)
- [ ] Manual verification: `curl http://localhost:8000/api/prices` returns valid JSON
- [ ] Deployed to Railway production environment
- [ ] Endpoint verified working in Railway: `curl https://<railway-domain>/api/prices` returns valid JSON
- [ ] Code review approved
- [ ] US-005 GitHub issue closed

## Implementation Plan

See: `specs/api-prices-endpoint-plan.md` (to be created in Phase 2)

## Notes

- **Decimal to float**: SQLAlchemy models use `Decimal` for precision, but JSON doesn't support Decimal. Pydantic's `from_attributes=True` handles conversion automatically.
- **Timestamp timezone**: Database stores timestamps in UTC. Response will include timezone info (ISO 8601 format).
- **Index usage**: Query uses `ORDER BY timestamp DESC LIMIT N`, which leverages the existing index on `timestamp` column (created in US-002 migration).
- **Migration from Binance to CoinGecko**: Recent change (2026-05-16) switched data source from Binance to CoinGecko to avoid geo-blocking. The `source` field will reflect this change in data.
