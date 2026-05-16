# Implementation Plan: BTC Prices Table with Alembic Migrations

**Spec**: [btc-prices-table.md](./btc-prices-table.md)  
**Created**: 2026-05-16  
**Status**: completed  
**Completed**: 2026-05-16  
**Issue**: #3 (US-002)

---

## Components

### 1. SQLAlchemy Model (BtcPrice)
- **Purpose**: Define ORM model for btc_prices table with OHLCV schema
- **Files**: `shared/btc_shared/db/models.py` (new file)
- **Dependencies**: SQLAlchemy Base class, DateTime, Numeric, String types
- **Effort**: XS

**Details**:
- Use SQLAlchemy 2.0 `Mapped` and `mapped_column` syntax
- Define 8 columns: id, timestamp, open, high, low, close, volume, source
- UNIQUE constraint on timestamp
- Index on timestamp for query performance
- Use `TIMESTAMPTZ` for timezone-aware timestamps
- Use `NUMERIC(18,8)` for price precision

### 2. Alembic Initialization
- **Purpose**: Set up Alembic migration framework in shared package
- **Files**: 
  - `shared/alembic.ini` (config file)
  - `shared/alembic/env.py` (environment setup)
  - `shared/alembic/script.py.mako` (template)
  - `shared/alembic/versions/` (directory for migrations)
- **Dependencies**: Alembic package, btc_shared.config (DATABASE_URL)
- **Effort**: S

**Details**:
- Run `alembic init alembic` from `shared/` directory
- Configure `alembic.ini` to use `btc_shared.config.settings.database_url`
- Configure `env.py` to import models and set target_metadata
- Use generic/asyncio template (no need for async, use generic)

### 3. Create Migration (btc_prices table)
- **Purpose**: Generate Alembic migration to create btc_prices table
- **Files**: `shared/alembic/versions/xxxx_create_btc_prices_table.py`
- **Dependencies**: BtcPrice model, Alembic initialized
- **Effort**: XS

**Details**:
- Run `alembic revision --autogenerate -m "create btc_prices table"`
- Review generated migration (verify UNIQUE constraint and index)
- Test upgrade: `alembic upgrade head`
- Test downgrade: `alembic downgrade -1`

### 4. Integration Tests
- **Purpose**: Automated tests for all 4 Gherkin scenarios
- **Files**: `shared/tests/test_btc_prices.py`
- **Dependencies**: pytest, BtcPrice model, Alembic migrations applied
- **Effort**: M

**Details**:
- **Test 1**: Migration creates table with correct schema
- **Test 2**: Insert valid OHLCV record
- **Test 3**: Duplicate timestamp raises IntegrityError
- **Test 4**: Downgrade removes table

**Test fixtures needed**:
- `alembic_config`: Configure Alembic for tests
- `db_with_migrations`: Database with migrations applied
- `sample_price_data`: Factory for creating test records

### 5. Update Exports
- **Purpose**: Expose BtcPrice model from shared package
- **Files**: `shared/btc_shared/db/__init__.py`
- **Dependencies**: models.py created
- **Effort**: XS

**Details**:
- Add `from btc_shared.db.models import BtcPrice` to `__init__.py`
- Allows importing as `from btc_shared.db import BtcPrice`

---

## Dependencies

### Build Order

1. **Foundation** (build first):
   - Component 1: SQLAlchemy Model (models.py)
   - Component 2: Alembic Initialization

2. **Migration** (depends on foundation):
   - Component 3: Create Migration (depends on model)

3. **Testing** (depends on migration):
   - Component 4: Integration Tests (depends on model + migration)

4. **Exports** (depends on model):
   - Component 5: Update Exports (depends on model)

### Dependency Graph

```
models.py (Component 1)
    ↓
Alembic init (Component 2)
    ↓
Create migration (Component 3)
    ↓
Integration tests (Component 4)

models.py (Component 1)
    ↓
Update exports (Component 5)
```

### External Dependencies

- `alembic`: Migration framework (already in pyproject.toml via US-001)
- `sqlalchemy[postgresql]`: ORM (already in pyproject.toml via US-001)
- `psycopg2-binary`: PostgreSQL adapter (already in pyproject.toml via US-001)

**No new dependencies needed** ✅

---

## Risks & Assumptions

### Risks

1. **Risk**: Alembic autogenerate might not detect UNIQUE constraint correctly
   - **Likelihood**: Low
   - **Impact**: Medium
   - **Mitigation**: Manually review generated migration before applying

2. **Risk**: NUMERIC type might have precision issues with large Bitcoin prices
   - **Likelihood**: Low
   - **Impact**: Low
   - **Mitigation**: NUMERIC(18,8) supports up to 10^10 (10 billion) with 8 decimals, sufficient for BTC prices

3. **Risk**: Timezone handling might cause confusion with UTC vs local time
   - **Likelihood**: Medium
   - **Impact**: Medium
   - **Mitigation**: Always use TIMESTAMPTZ and store in UTC, document clearly

4. **Risk**: Tests might pollute production database if not isolated
   - **Likelihood**: Low (fixtures handle cleanup)
   - **Impact**: High
   - **Mitigation**: Use test fixtures with automatic rollback/cleanup

### Assumptions

- PostgreSQL 16 is running in Docker container (from US-001)
- DATABASE_URL environment variable is configured correctly
- Alembic package is already installed (it should be from US-001 requirements)
- Tests run in same container as application code

---

## Milestones

- [ ] **M1: Model Created** — BtcPrice model defined in models.py
- [ ] **M2: Alembic Initialized** — `alembic init` completed, env.py configured
- [ ] **M3: Migration Generated** — First migration created and reviewed
- [ ] **M4: Migration Applied** — `alembic upgrade head` creates table successfully
- [ ] **M5: Tests Pass** — All 4 Gherkin scenarios have passing tests
- [ ] **M6: Code Quality** — Lint passes, 100% coverage achieved

---

## Tasks

### Foundation (Build First)

- [ ] **Task 1: Create BtcPrice SQLAlchemy model**
  - **Acceptance**: 
    - `shared/btc_shared/db/models.py` exists
    - BtcPrice class defined with all 8 columns
    - UNIQUE constraint on timestamp
    - Uses SQLAlchemy 2.0 Mapped syntax
  - **Files**: 
    - `shared/btc_shared/db/models.py` (create)
  - **Tests**: Unit test that model class exists and has correct attributes
  - **Effort**: XS (~30 min)

- [ ] **Task 2: Initialize Alembic in shared package**
  - **Acceptance**:
    - `shared/alembic/` directory exists with env.py, script.py.mako
    - `shared/alembic.ini` exists and configured
    - `env.py` imports BtcPrice and sets target_metadata
    - `sqlalchemy.url` in alembic.ini uses btc_shared.config.settings.database_url
  - **Files**:
    - `shared/alembic.ini` (create)
    - `shared/alembic/env.py` (create/modify)
    - `shared/alembic/script.py.mako` (create)
    - `shared/alembic/versions/` (create directory)
  - **Tests**: Verify `alembic current` runs without error
  - **Effort**: S (~1 hour)

### Migration (Build Second)

- [ ] **Task 3: Generate and review migration for btc_prices table**
  - **Acceptance**:
    - Migration file created in `shared/alembic/versions/`
    - Migration creates table with all columns
    - UNIQUE constraint on timestamp is present
    - Index on timestamp is present
    - Migration reviewed and manually adjusted if needed
  - **Files**:
    - `shared/alembic/versions/xxxx_create_btc_prices_table.py` (generate)
  - **Tests**: Run `alembic upgrade head` in test environment
  - **Effort**: XS (~30 min)

- [ ] **Task 4: Test migration upgrade and downgrade**
  - **Acceptance**:
    - `docker compose exec api alembic upgrade head` creates table
    - `docker compose exec api alembic downgrade -1` drops table
    - Can run upgrade → downgrade → upgrade without errors
  - **Files**: None (testing existing migration)
  - **Tests**: Manual verification + automated test
  - **Effort**: XS (~15 min)

### Testing (Build Third)

- [ ] **Task 5: Create test fixtures for btc_prices tests**
  - **Acceptance**:
    - `shared/tests/conftest.py` has fixtures for Alembic and migrations
    - Fixture `db_with_migrations` applies migrations before tests
    - Fixture `sample_price_data` factory for creating test records
  - **Files**:
    - `shared/tests/conftest.py` (modify)
  - **Tests**: Fixtures work and clean up correctly
  - **Effort**: S (~1 hour)

- [ ] **Task 6: Write integration tests for Gherkin Scenario 1 (create table)**
  - **Acceptance**:
    - Test verifies btc_prices table exists after migration
    - Test verifies all columns exist with correct types
    - Test verifies UNIQUE constraint exists
    - Test passes when run via `docker compose exec api pytest`
  - **Files**:
    - `shared/tests/test_btc_prices.py` (create)
  - **Tests**: `test_migration_creates_btc_prices_table`
  - **Effort**: S (~30 min)

- [ ] **Task 7: Write integration tests for Gherkin Scenario 2 (insert valid record)**
  - **Acceptance**:
    - Test inserts record with all OHLCV fields
    - Test queries record by timestamp
    - Test verifies data types (NUMERIC, TIMESTAMPTZ)
    - Test passes
  - **Files**:
    - `shared/tests/test_btc_prices.py` (modify)
  - **Tests**: `test_insert_valid_ohlcv_record`
  - **Effort**: S (~30 min)

- [ ] **Task 8: Write integration tests for Gherkin Scenario 3 (duplicate timestamp)**
  - **Acceptance**:
    - Test inserts record with timestamp T
    - Test attempts to insert duplicate with same timestamp T
    - Test verifies IntegrityError is raised
    - Test verifies second record is NOT saved
    - Test passes
  - **Files**:
    - `shared/tests/test_btc_prices.py` (modify)
  - **Tests**: `test_duplicate_timestamp_rejected`
  - **Effort**: S (~30 min)

- [ ] **Task 9: Write integration tests for Gherkin Scenario 4 (downgrade)**
  - **Acceptance**:
    - Test runs `alembic downgrade -1`
    - Test verifies btc_prices table no longer exists
    - Test passes
  - **Files**:
    - `shared/tests/test_btc_prices.py` (modify)
  - **Tests**: `test_downgrade_removes_table`
  - **Effort**: S (~30 min)

### Exports & Documentation (Build Last)

- [ ] **Task 10: Update db package exports**
  - **Acceptance**:
    - `shared/btc_shared/db/__init__.py` exports BtcPrice
    - Can import via `from btc_shared.db import BtcPrice`
  - **Files**:
    - `shared/btc_shared/db/__init__.py` (modify)
  - **Tests**: Import test
  - **Effort**: XS (~5 min)

- [ ] **Task 11: Run full test suite and verify coverage**
  - **Acceptance**:
    - All tests pass: `docker compose exec api pytest shared/tests/`
    - Coverage ≥ 100% for `shared/btc_shared/db/models.py`
    - Coverage report generated
  - **Files**: None
  - **Tests**: Full test suite
  - **Effort**: XS (~15 min)

- [ ] **Task 12: Lint and format code**
  - **Acceptance**:
    - `docker compose exec api ruff check shared/` passes
    - `docker compose exec api ruff format shared/` applied
    - No lint errors
  - **Files**: All modified files
  - **Tests**: Lint check
  - **Effort**: XS (~5 min)

---

## Effort Estimate

**Total Estimated Time**: 4-6 hours (within S size, 1 day)

| Phase | Tasks | Effort |
|-------|-------|--------|
| Foundation | Task 1-2 | 1.5 hours |
| Migration | Task 3-4 | 0.75 hours |
| Testing | Task 5-9 | 3 hours |
| Exports & Docs | Task 10-12 | 0.5 hours |
| **Total** | **12 tasks** | **5.75 hours** |

**Breakdown by Complexity**:
- XS tasks (5): ~1.5 hours
- S tasks (7): ~4.25 hours
- M tasks (0): 0 hours

---

## Execution Strategy

### Sequential Execution (Recommended)

Execute tasks in order 1 → 12. Each task depends on previous tasks being complete.

**Rationale**: 
- Model must exist before Alembic can detect it
- Alembic must be initialized before generating migrations
- Migration must exist before testing it
- Tests verify the entire chain works

### Verification Checkpoints

After each major phase, verify:

1. **After Foundation**: Can import BtcPrice, Alembic commands run without error
2. **After Migration**: Table exists in database, has correct schema
3. **After Testing**: All 4 Gherkin scenarios pass, coverage ≥ 100%
4. **After Exports**: Can import from shared package cleanly

---

## Rollback Plan

If issues occur during implementation:

1. **Model issues**: Fix model definition, regenerate migration
2. **Alembic issues**: `alembic downgrade -1` to undo migration
3. **Test failures**: Fix code, re-run tests (tests use rollback fixtures)
4. **Data corruption**: Not possible (tests use isolated fixtures)

**Safe to retry**: Yes, Alembic migrations are idempotent.

---

## Notes

- All commands MUST run inside Docker container: `docker compose exec api <command>`
- Alembic commands run from `shared/` directory: `cd shared && alembic <command>`
- Tests automatically clean up (fixture rollback pattern)
- PostgreSQL container must be running before executing tasks
- First migration will be empty database → btc_prices table (clean slate)

---

## Next Steps

After plan approval:
1. **Phase 3: TASKS** — Create GitHub Issue with task checklist (optional)
2. **Phase 4: IMPLEMENT** — Execute tasks 1-12 sequentially
