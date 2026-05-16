# BTC Prices Table with Alembic Migrations

---
**Title**: BTC Prices Table with Alembic Migrations  
**Status**: completed  
**Created**: 2026-05-16  
**Updated**: 2026-05-16  
**Completed**: 2026-05-16
**Issue**: #3  
**User Story**: US-002  
**Size**: S (1 day)  
**Iteration**: 1

---

## Objective

Create a `btc_prices` table to store historical Bitcoin OHLCV (Open, High, Low, Close, Volume) data from Binance, using Alembic migrations for schema versioning. This table serves as the foundation for all price data used in predictions and model training.

## Context

The BTC Predictor application requires historical Bitcoin price data to:
1. Train machine learning models on historical patterns
2. Evaluate prediction accuracy by comparing predicted vs. actual prices
3. Calculate profit/loss (PnL) simulations based on trading strategies

This table will be populated hourly by the `fetch-price` cron job (US-003) and queried by:
- The `daily` cron job for model training and evaluation
- The API service for displaying price charts and historical data

**Dependencies:**
- ✅ US-001: Shared package with database configuration (COMPLETED)

## Requirements

### Functional Requirements

- [ ] Create SQLAlchemy model `BtcPrice` with OHLCV fields
- [ ] Initialize Alembic in `shared/alembic/` directory
- [ ] Generate Alembic migration to create `btc_prices` table
- [ ] Support idempotent inserts (UNIQUE constraint on timestamp)
- [ ] Support querying prices by timestamp or date range
- [ ] Support migration rollback (downgrade)

### Non-Functional Requirements

- [ ] **Data Integrity**: UNIQUE constraint on `timestamp` prevents duplicate records
- [ ] **Performance**: Index on `timestamp` for fast queries by date range
- [ ] **Timezone**: Use `TIMESTAMPTZ` (timezone-aware) for `timestamp` column
- [ ] **Precision**: Use `NUMERIC` or `FLOAT` for price/volume fields (flexible)
- [ ] **Testability**: All Gherkin scenarios covered by automated tests
- [ ] **Idempotency**: Running migration twice has no effect

## Architecture

### Components

```
shared/
├── btc_shared/
│   └── db/
│       ├── database.py       (✅ exists from US-001)
│       └── models.py          (🆕 create BtcPrice model)
├── alembic/
│   ├── env.py                 (🆕 Alembic environment config)
│   ├── script.py.mako         (🆕 migration template)
│   └── versions/
│       └── xxxx_create_btc_prices_table.py  (🆕 migration)
├── alembic.ini                (🆕 Alembic config file)
└── tests/
    └── test_btc_prices.py     (🆕 integration tests)
```

### Data Model

**Table**: `btc_prices`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `timestamp` | TIMESTAMPTZ | NOT NULL, UNIQUE | Price timestamp (UTC) |
| `open` | NUMERIC(18,8) | NOT NULL | Opening price |
| `high` | NUMERIC(18,8) | NOT NULL | Highest price |
| `low` | NUMERIC(18,8) | NOT NULL | Lowest price |
| `close` | NUMERIC(18,8) | NOT NULL | Closing price |
| `volume` | NUMERIC(18,8) | NOT NULL | Trading volume (BTC) |
| `source` | VARCHAR(50) | NOT NULL, DEFAULT 'binance' | Data source |

**Indexes:**
- PRIMARY KEY on `id`
- UNIQUE INDEX on `timestamp`

**SQLAlchemy Model:**
```python
class BtcPrice(Base):
    __tablename__ = "btc_prices"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=True, nullable=False, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="binance")
```

### External Dependencies

- **SQLAlchemy 2.0**: ORM and schema definition
- **Alembic**: Database migration tool
- **PostgreSQL**: Target database (via Docker container)
- **psycopg2-binary**: PostgreSQL adapter for Python

## User Stories

**As** a data engineer  
**I want** a btc_prices table with OHLCV fields  
**So that** I can store historical Bitcoin prices from Binance

## Testing Strategy

### Integration Tests (all tests run in Docker container)

**Test File**: `shared/tests/test_btc_prices.py`

All 4 Gherkin scenarios from US-002 must have automated tests:

1. **Scenario: Create btc_prices table via migration**
   - Test that `alembic upgrade head` creates the table
   - Verify table exists in database
   - Verify all columns exist with correct types
   - Verify UNIQUE constraint on timestamp

2. **Scenario: Insert valid OHLCV record**
   - Test inserting a valid record via SQLAlchemy ORM
   - Verify record is saved
   - Verify querying by timestamp returns the record
   - Test data types (NUMERIC, TIMESTAMPTZ, VARCHAR)

3. **Scenario: Duplicate timestamp is rejected**
   - Insert a record with timestamp T
   - Attempt to insert another record with same timestamp T
   - Verify IntegrityError is raised
   - Verify second record is NOT saved

4. **Scenario: Downgrade migration removes table**
   - Test that `alembic downgrade -1` removes the table
   - Verify table no longer exists

**Test Execution:**
```bash
# Run all tests
docker compose exec api pytest shared/tests/test_btc_prices.py -v

# Run with coverage
docker compose exec api pytest shared/tests/test_btc_prices.py --cov=btc_shared.db --cov-report=term-missing
```

### Test Fixtures

- `db_engine`: SQLAlchemy engine connected to test database
- `db_session`: SQLAlchemy session with automatic rollback
- `sample_btc_price`: Factory function for creating test price records

### Coverage Target

**Minimum: 100% coverage** for `btc_shared/db/models.py`

## Boundaries & Constraints

### In Scope
- Creating `btc_prices` table with OHLCV schema
- Alembic initialization and first migration
- SQLAlchemy model definition
- UNIQUE constraint on timestamp (idempotency)
- Integration tests for all Gherkin scenarios
- Migration upgrade and downgrade

### Out of Scope
- Populating the table with data (handled by US-003: fetch-price cron)
- API endpoints to query prices (handled by US-005)
- Data visualization or charts
- Performance optimization (indexing beyond timestamp)
- Data retention policies or archival
- Multiple data sources beyond Binance

### Technical Constraints
- **Database**: PostgreSQL 16 (via Docker container)
- **ORM**: SQLAlchemy 2.0+ (modern mapped_column syntax)
- **Migration Tool**: Alembic
- **Python Version**: 3.12+ (container has 3.13)
- **Container-First**: All commands run via `docker compose exec api`

### Edge Cases (from ZOMBIES analysis)

- **Zero**: `close=0.0` or `volume=0.0` → VALID (market can have 0 volume)
- **Boundaries**: `timestamp` at epoch 0 or far future → valid if within PostgreSQL TIMESTAMPTZ range
- **Exceptions**: `timestamp=NULL` → violates NOT NULL constraint (expected)
- **Interfaces**: Multiple services writing concurrently → UNIQUE constraint prevents race conditions

## Success Criteria

- [ ] `btc_prices` table created via `alembic upgrade head`
- [ ] Table has all required columns with correct types and constraints
- [ ] UNIQUE constraint on `timestamp` prevents duplicates
- [ ] Can insert valid OHLCV records via SQLAlchemy ORM
- [ ] Duplicate timestamp insertion raises `IntegrityError`
- [ ] `alembic downgrade -1` successfully removes the table
- [ ] All 4 Gherkin scenarios have passing automated tests
- [ ] Test coverage ≥ 100% for `models.py`
- [ ] Migration runs successfully in Docker container
- [ ] Code passes lint (ruff) with no errors

## Implementation Plan

See: [`specs/btc-prices-table-plan.md`](./btc-prices-table-plan.md) (to be created in Phase 2)

---

## Changelog

**2026-05-16**: Initial spec created from US-002
