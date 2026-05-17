# Implementation Plan: US-008 - Predictions Table

**Spec**: `specs/us-008-predictions-table.md`  
**Created**: 2026-05-17  
**Status**: completed

## Components

### 1. Prediction SQLAlchemy Model
- **Purpose**: Define `Prediction` class with all columns, relationships, and constraints
- **Files**: `shared/shared/db/models.py`
- **Effort**: S
- **Details**: 
  - Add class after `Model` class
  - Define 12 columns with correct types
  - Add `relationship()` to `Model` table
  - Add `__repr__` for debugging

### 2. Alembic Migration
- **Purpose**: Create database migration to add `predictions` table
- **Files**: `shared/alembic/versions/{hash}_add_predictions_table.py`
- **Effort**: S
- **Details**:
  - Auto-generate migration with `alembic revision --autogenerate`
  - Verify schema matches spec (indexes, foreign keys)
  - Test both `upgrade` and `downgrade` paths

### 3. Integration Tests
- **Purpose**: Test all 4 Gherkin scenarios
- **Files**: `shared/tests/test_predictions_model.py`
- **Effort**: M
- **Details**:
  - Test migration creates correct schema
  - Test insert with NULL evaluation fields
  - Test update with evaluation data
  - Test query unevaluated predictions
  - Test foreign key CASCADE delete
  - Test NOT NULL constraints

### 4. Test Fixtures
- **Purpose**: Create reusable fixtures for prediction tests
- **Files**: `shared/tests/conftest.py`
- **Effort**: XS
- **Details**:
  - Add `sample_model` fixture (prerequisite for predictions)
  - Add `sample_prediction` fixture with phase 1 data
  - Add `evaluated_prediction` fixture with phase 2 data

## Dependencies

### Build Order
1. **Prediction Model** (foundation) - defines schema
2. **Alembic Migration** (depends on #1) - creates table
3. **Test Fixtures** (depends on #1) - provides test data
4. **Integration Tests** (depends on #1-3) - validates everything

### External Dependencies
- **SQLAlchemy 2.0**: Already in use (from US-001)
- **Alembic**: Already configured (from US-002)
- **pytest**: Already in use (from US-002+)
- **Model table**: Must exist (from US-007) ✅ Already merged

## Risks & Assumptions

### Risks
- **Risk 1**: Foreign key constraint might fail if `Model` table structure changed
  - **Mitigation**: Verify US-007 is merged and deployed before starting
  
- **Risk 2**: Auto-generated migration might miss indexes
  - **Mitigation**: Manual review of migration before running tests

- **Risk 3**: NUMERIC precision might cause rounding issues in tests
  - **Mitigation**: Use `Decimal` type in Python, compare with tolerance in tests

### Assumptions
- ✅ US-007 (models table) is complete and merged
- ✅ Alembic is configured and working (from US-002)
- ✅ Test infrastructure is in place (from previous US)
- PostgreSQL NUMERIC(10,2) supports required precision for BTC prices

## Milestones

- [ ] **Milestone 1**: Model defined, migration generated (no errors)
- [ ] **Milestone 2**: Migration runs successfully (up and down)
- [ ] **Milestone 3**: All 4 Gherkin scenarios have passing tests
- [ ] **Milestone 4**: Coverage ≥ 95%, lint passes

## Tasks

### Foundation (Build First)

- [ ] **Task 1**: Define Prediction SQLAlchemy model
  - **Acceptance**: 
    - `Prediction` class exists in `shared/shared/db/models.py`
    - All 12 columns defined with correct types
    - `model_id` has `relationship()` and `ForeignKey`
    - `__repr__` method for debugging
  - **Files**: `shared/shared/db/models.py`
  - **Tests**: None yet (tested via migration)
  - **Effort**: S (30 min)

- [ ] **Task 2**: Generate Alembic migration
  - **Acceptance**: 
    - Migration file created via `alembic revision --autogenerate`
    - `upgrade()` creates `predictions` table with all columns
    - `downgrade()` drops `predictions` table
    - Indexes on `model_id` and `predicted_for` present
    - Foreign key constraint to `models.id` with CASCADE
  - **Files**: `shared/alembic/versions/{hash}_add_predictions_table.py`
  - **Tests**: Manual verification (run up/down)
  - **Effort**: S (20 min)

### Testing (Build Second)

- [ ] **Task 3**: Add test fixtures for predictions
  - **Acceptance**: 
    - `sample_model` fixture creates a Model record
    - `sample_prediction` fixture creates phase 1 prediction (NULL evaluation)
    - `evaluated_prediction` fixture creates phase 2 prediction (with evaluation)
    - All fixtures use `yield` pattern for cleanup
  - **Files**: `shared/tests/conftest.py`
  - **Tests**: Fixtures will be used by Task 4
  - **Effort**: XS (15 min)

- [ ] **Task 4**: Write integration tests for all Gherkin scenarios
  - **Acceptance**: 
    - ✅ Test 1: Migration creates table with correct schema
    - ✅ Test 2: Insert prediction with NULL evaluation fields
    - ✅ Test 3: Update prediction with evaluation data
    - ✅ Test 4: Query unevaluated predictions
    - ✅ Test 5: Foreign key CASCADE delete works
    - ✅ Test 6: NOT NULL constraints enforced
    - All tests passing
    - Coverage ≥ 95% for `Prediction` model
  - **Files**: `shared/tests/test_predictions_model.py`
  - **Tests**: Run with `docker compose exec api pytest shared/tests/test_predictions_model.py -v`
  - **Effort**: M (1-2 hours)

### Verification (Build Third)

- [ ] **Task 5**: Run full test suite and verify
  - **Acceptance**: 
    - All tests passing (`pytest`)
    - Coverage ≥ 95% (`pytest --cov`)
    - Lint passes (`ruff check`)
    - Migration reversible (up/down works)
  - **Files**: All files
  - **Tests**: `docker compose exec api pytest --cov`
  - **Effort**: XS (10 min)

- [ ] **Task 6**: Update GitHub issue status
  - **Acceptance**: 
    - All Definition of Done checkboxes marked
    - Comment with test results and coverage
    - Ready for code review
  - **Files**: GitHub Issue #9
  - **Tests**: None
  - **Effort**: XS (5 min)

## Effort Estimate

**Total Estimated Time**: ~3 hours (fits within S/1 day estimate)

| Phase | Effort |
|-------|--------|
| Foundation (Tasks 1-2) | 50 min |
| Testing (Tasks 3-4) | 2 hours |
| Verification (Tasks 5-6) | 15 min |
| **Total** | ~3 hours |

## Implementation Order

```
1. Define Prediction model (30 min)
   ↓
2. Generate migration (20 min)
   ↓
3. Run migration to verify (5 min)
   ↓
4. Add test fixtures (15 min)
   ↓
5. Write integration tests (1-2 hours)
   ↓
6. Run full test suite (10 min)
   ↓
7. Update GitHub issue (5 min)
   ↓
✅ US-008 Complete
```

## Notes

- Follow existing patterns from `BtcPrice` and `Model` classes
- Use `Decimal` type in Python for NUMERIC columns (avoid float precision issues)
- Test both happy path and error cases (foreign key violation, NOT NULL violation)
- Ensure migration is reversible (important for production rollback)
