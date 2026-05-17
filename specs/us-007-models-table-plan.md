# Implementation Plan: US-007 - Models Table

**Spec**: [us-007-models-table.md](./us-007-models-table.md)  
**Created**: 2026-05-17  
**Status**: approved  
**Estimated Effort**: 1 day (6-8 hours)

---

## Components

### 1. SQLAlchemy Model Class
**Purpose**: Define the ORM model for the `models` table  
**Files**: `shared/shared/db/models.py`  
**Effort**: S (2 hours)

**Details**:
- Add `Model` class to existing `models.py`
- Columns: id, name, version, params (JSONB), artifact (BYTEA), trained_at, train_from, train_to, is_active
- Constraints: UNIQUE(name, version), CHECK(train_to >= train_from)
- Relationship: `predictions` (one-to-many, foreign key from predictions table)

**Implementation Notes**:
- Use SQLAlchemy 2.0 syntax (declarative base already exists)
- JSONB type: `sqlalchemy.dialects.postgresql.JSONB`
- BYTEA type: `LargeBinary`
- Add `__repr__` for debugging

---

### 2. Alembic Migration
**Purpose**: Create the `models` table in PostgreSQL  
**Files**: `shared/alembic/versions/XXX_create_models_table.py`  
**Effort**: S (1.5 hours)

**Details**:
- Generate migration: `alembic revision --autogenerate -m "create models table"`
- Verify generated SQL (autogenerate may miss indexes/constraints)
- Manually add index: `idx_models_active ON models (name, is_active) WHERE is_active = TRUE`
- Test upgrade and downgrade

**Migration SQL**:
```sql
-- upgrade()
CREATE TABLE models (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    version VARCHAR(50) NOT NULL,
    params JSONB NOT NULL,
    artifact BYTEA NOT NULL,
    trained_at TIMESTAMP NOT NULL,
    train_from DATE NOT NULL,
    train_to DATE NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT unique_model_version UNIQUE (name, version),
    CONSTRAINT valid_training_period CHECK (train_to >= train_from)
);

CREATE INDEX idx_models_active ON models (name, is_active) WHERE is_active = TRUE;

-- downgrade()
DROP INDEX IF EXISTS idx_models_active;
DROP TABLE IF EXISTS models;
```

---

### 3. Unit Tests (SQLAlchemy Model)
**Purpose**: Test the ORM model definition  
**Files**: `shared/tests/test_models.py`  
**Effort**: S (1.5 hours)

**Test Cases**:
1. Create `Model` instance with valid data
2. Validate JSONB serialization (dict → JSONB)
3. Validate BYTEA storage (bytes → LargeBinary)
4. Test `__repr__` method

**Example Test**:
```python
def test_create_model_instance():
    model = Model(
        name="linear_v1",
        version="1.0.0",
        params={"window_days": 30},
        artifact=b"pickled_model_bytes",
        trained_at=datetime.now(),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=True
    )
    assert model.name == "linear_v1"
    assert model.params["window_days"] == 30
```

---

### 4. Integration Tests (Database Operations)
**Purpose**: Test actual database operations with the `models` table  
**Files**: `shared/tests/test_models_integration.py`  
**Effort**: M (3 hours)

**Test Scenarios** (map to 4 Gherkin scenarios):

1. **Scenario: Create models table via migration**
   - Run `alembic upgrade head`
   - Query `information_schema` to verify table exists
   - Verify columns, types, constraints, indexes

2. **Scenario: Insert trained model**
   - Serialize a real `LinearRegressionModel` using pickle
   - Insert into `models` table via SQLAlchemy
   - Query back and verify all fields match
   - Verify artifact can be deserialized

3. **Scenario: Retrieve active model**
   - Insert 3 models with `name="linear_v1"`, different versions
   - Set only 1 to `is_active=True`
   - Query: `session.query(Model).filter_by(name="linear_v1", is_active=True).first()`
   - Verify correct model returned

4. **Scenario: Store params as JSONB**
   - Insert model with params: `{"window_days": 30, "features": ["close", "volume"]}`
   - Query back: `model.params["window_days"]`
   - Test JSONB query: `session.query(Model).filter(Model.params['window_days'].astext == '30')`

5. **Scenario: Constraint validation**
   - Test UNIQUE: Insert duplicate (name, version) → should raise IntegrityError
   - Test CHECK: Insert with `train_to < train_from` → should raise IntegrityError

**Test Fixtures**:
```python
@pytest.fixture
def sample_model_artifact():
    """Create and serialize a real LinearRegressionModel"""
    from workers.daily.models.linear import LinearRegressionModel
    import pickle
    model = LinearRegressionModel(window_days=30)
    # Train with synthetic data
    X = np.array([[1, 2, 3]] * 10)  # 10 samples, 3 features
    y = np.array([50000.0] * 10)
    model.train(X, y)
    return pickle.dumps(model)
```

---

## Dependencies

### Build Order

1. **First**: SQLAlchemy `Model` class
   - Foundation for everything else
   - No dependencies (just SQLAlchemy)

2. **Second**: Alembic migration
   - Depends on: Model class definition
   - Creates actual table in database

3. **Third**: Unit tests
   - Depends on: Model class
   - Can run without migration (doesn't touch DB)

4. **Fourth**: Integration tests
   - Depends on: Model class + Migration
   - Requires database with `models` table

### External Dependencies

- **SQLAlchemy 2.0**: Already installed ✅
- **Alembic**: Already configured ✅
- **PostgreSQL**: Already running in docker-compose ✅
- **pytest**: Already installed ✅
- **US-006 (LinearRegressionModel)**: Already completed ✅

---

## Risks & Assumptions

### Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| **BYTEA size limit** | PostgreSQL has a 1GB limit per BYTEA, but large models could slow queries | Start with BYTEA, monitor artifact sizes. If > 1MB common, migrate to S3 in future US |
| **Pickle security** | Pickle can execute arbitrary code if loading untrusted data | Only load pickles we created ourselves. Document this constraint. |
| **JSONB query performance** | Complex JSONB queries can be slow without proper indexes | Add GIN index if we start filtering by params frequently |
| **Migration conflicts** | If other migrations created since last pull, may have conflicts | Run `alembic history` before generating migration, resolve conflicts |

### Assumptions

1. ✅ Model artifacts (sklearn linear models) will be < 100KB (validated in US-006)
2. ✅ Only 1 active model per name (enforced by application, not DB constraint)
3. ✅ Pickle is acceptable for serialization (standard for sklearn)
4. ✅ PostgreSQL JSONB supports our params structure (dict with simple types)
5. ✅ Training date range (train_from, train_to) is always known when saving model

---

## Milestones

### Milestone 1: Model Definition Complete
**Verification**: Can import `Model` class without errors  
**Checkpoint**: 
```python
from shared.db.models import Model
print(Model.__table__.columns.keys())  # Should print all column names
```

### Milestone 2: Migration Applied Successfully
**Verification**: `models` table exists in PostgreSQL  
**Checkpoint**:
```bash
docker compose exec api sh -c "cd shared && alembic upgrade head"
docker compose exec postgres psql -U btcpredictor -d btcpredictor -c "\d models"
```

### Milestone 3: Tests Passing
**Verification**: All 4 Gherkin scenarios have passing tests  
**Checkpoint**:
```bash
docker compose exec api pytest shared/tests/test_models.py -v
docker compose exec api pytest shared/tests/test_models_integration.py -v
```

---

## Tasks

### Phase 1: Foundation (Build First)

- [ ] **Task 1.1: Add Model class to SQLAlchemy models**
  - **Acceptance**: Can import `from shared.db.models import Model` without errors
  - **Files**: `shared/shared/db/models.py`
  - **Tests**: Unit test - create instance with valid data
  - **Effort**: S (1 hour)
  - **Details**:
    - Add `Model` class below existing `BtcPrice` class
    - Import `JSONB` from `sqlalchemy.dialects.postgresql`
    - Use `LargeBinary` for artifact column
    - Add UNIQUE constraint: `__table_args__ = (UniqueConstraint('name', 'version'),)`
    - Add CHECK constraint for train_to >= train_from

- [ ] **Task 1.2: Generate and verify Alembic migration**
  - **Acceptance**: Migration file exists and contains correct SQL
  - **Files**: `shared/alembic/versions/XXX_create_models_table.py`
  - **Tests**: Manual inspection of generated SQL
  - **Effort**: S (30 min)
  - **Details**:
    - Run: `docker compose exec api sh -c "cd shared && alembic revision --autogenerate -m 'create models table'"`
    - Open generated migration file
    - Verify it includes: table creation, UNIQUE constraint, CHECK constraint
    - Manually add partial index: `idx_models_active`

- [ ] **Task 1.3: Test migration up and down**
  - **Acceptance**: Can upgrade and downgrade migration without errors
  - **Files**: N/A (testing existing migration)
  - **Tests**: Manual verification
  - **Effort**: XS (15 min)
  - **Details**:
    - Run: `alembic upgrade head` → verify table exists
    - Run: `alembic downgrade -1` → verify table dropped
    - Run: `alembic upgrade head` again → verify idempotent

---

### Phase 2: Unit Tests (Build Second)

- [ ] **Task 2.1: Write unit tests for Model class**
  - **Acceptance**: Unit tests pass, can create Model instances
  - **Files**: `shared/tests/test_models.py` (create new file)
  - **Tests**: Self-testing
  - **Effort**: S (1 hour)
  - **Details**:
    - Test: Create `Model` instance with all fields
    - Test: JSONB params serialize correctly
    - Test: BYTEA artifact accepts bytes
    - Test: `__repr__` returns useful string

---

### Phase 3: Integration Tests (Build Third)

- [ ] **Task 3.1: Gherkin Scenario 1 - Create models table via migration**
  - **Acceptance**: Test verifies table structure in database
  - **Files**: `shared/tests/test_models_integration.py` (create new file)
  - **Tests**: Self-testing
  - **Effort**: S (45 min)
  - **Details**:
    - Query `information_schema.tables` to verify `models` exists
    - Query `information_schema.columns` to verify all columns
    - Verify constraints exist

- [ ] **Task 3.2: Gherkin Scenario 2 - Insert trained model**
  - **Acceptance**: Can insert and retrieve serialized model
  - **Files**: `shared/tests/test_models_integration.py`
  - **Tests**: Self-testing
  - **Effort**: M (1 hour)
  - **Details**:
    - Create fixture: `sample_model_artifact()` that pickles a real LinearRegressionModel
    - Insert model into database
    - Query back and verify all fields match
    - Deserialize artifact and verify it's a valid model

- [ ] **Task 3.3: Gherkin Scenario 3 - Retrieve active model**
  - **Acceptance**: Can query for active model among multiple versions
  - **Files**: `shared/tests/test_models_integration.py`
  - **Tests**: Self-testing
  - **Effort**: S (45 min)
  - **Details**:
    - Insert 3 models with same name, different versions
    - Set only 1 to `is_active=True`
    - Query: `filter_by(name=X, is_active=True)`
    - Assert correct model returned

- [ ] **Task 3.4: Gherkin Scenario 4 - Store params as JSONB**
  - **Acceptance**: JSONB params can be queried and filtered
  - **Files**: `shared/tests/test_models_integration.py`
  - **Tests**: Self-testing
  - **Effort**: S (45 min)
  - **Details**:
    - Insert model with complex params dict
    - Query back: `model.params["window_days"]`
    - Test JSONB operators: `Model.params['window_days'].astext == '30'`

- [ ] **Task 3.5: Test constraint validation**
  - **Acceptance**: Constraints raise appropriate errors
  - **Files**: `shared/tests/test_models_integration.py`
  - **Tests**: Self-testing
  - **Effort**: S (30 min)
  - **Details**:
    - Test UNIQUE constraint: duplicate (name, version) → IntegrityError
    - Test CHECK constraint: train_to < train_from → IntegrityError

---

### Phase 4: Verification (Build Last)

- [ ] **Task 4.1: Run full test suite with coverage**
  - **Acceptance**: All tests pass, coverage ≥ 95%
  - **Files**: N/A (testing)
  - **Tests**: Coverage report
  - **Effort**: XS (15 min)
  - **Details**:
    - Run: `pytest shared/tests/test_models*.py --cov=shared.db.models --cov-report=term-missing`
    - Verify coverage ≥ 95%
    - Fix any missed branches

- [ ] **Task 4.2: Lint and type check**
  - **Acceptance**: No lint errors, type hints correct
  - **Files**: All modified files
  - **Tests**: Linter output
  - **Effort**: XS (10 min)
  - **Details**:
    - Run: `ruff check shared/shared/db/models.py`
    - Run: `ruff format shared/shared/db/models.py`
    - Fix any issues

- [ ] **Task 4.3: Update GitHub Issue #8**
  - **Acceptance**: All Definition of Done checkboxes marked
  - **Files**: N/A (GitHub)
  - **Tests**: Manual verification
  - **Effort**: XS (5 min)
  - **Details**:
    - Mark all Gherkin scenarios as ✅
    - Mark "Code review approved" as ✅
    - Mark "Lint/build green" as ✅
    - Close issue with summary comment

---

## Effort Estimate

| Phase | Tasks | Estimated Time |
|-------|-------|----------------|
| Foundation | 3 tasks | 1.75 hours |
| Unit Tests | 1 task | 1 hour |
| Integration Tests | 5 tasks | 3.75 hours |
| Verification | 3 tasks | 0.5 hours |
| **Total** | **12 tasks** | **7 hours (1 day)** |

**Confidence**: High (straightforward DB schema, similar to US-002 btc_prices table)

---

## Testing Strategy Summary

### Test Pyramid

```
        /\
       /  \  E2E: None (table-only US)
      /----\
     / INT  \ Integration: 5 scenarios (DB operations)
    /--------\
   /   UNIT   \ Unit: 4 tests (Model class)
  /____________\
```

### Coverage Target

- **Unit tests**: 100% of Model class (simple, should be fully covered)
- **Integration tests**: 95%+ of database operations
- **Overall**: ≥ 95% for `shared/shared/db/models.py`

### Test Execution

All tests run inside Docker container:
```bash
docker compose exec api pytest shared/tests/test_models.py -v
docker compose exec api pytest shared/tests/test_models_integration.py -v
docker compose exec api pytest shared/tests/test_models*.py --cov --cov-report=term-missing
```

---

## Implementation Notes

### JSONB Column Tips

```python
# Querying JSONB in SQLAlchemy
from sqlalchemy import cast, String

# Access nested key
query = session.query(Model).filter(
    Model.params['window_days'].astext.cast(Integer) == 30
)

# Check if key exists
query = session.query(Model).filter(
    Model.params.has_key('window_days')
)

# Match entire structure
query = session.query(Model).filter(
    Model.params.contains({'window_days': 30})
)
```

### BYTEA Column Tips

```python
# Store pickled model
import pickle
artifact_bytes = pickle.dumps(trained_model)
model_record = Model(artifact=artifact_bytes, ...)

# Load pickled model
loaded_model = pickle.loads(model_record.artifact)
```

### Partial Index Syntax (Alembic)

```python
# In migration file
from sqlalchemy import Index

def upgrade():
    # ... create table ...
    
    # Partial index (only indexes rows where is_active=True)
    op.create_index(
        'idx_models_active',
        'models',
        ['name', 'is_active'],
        postgresql_where=sa.text('is_active = TRUE')
    )
```

---

## Definition of Done Checklist

Before closing US-007:

- [ ] SQLAlchemy `Model` class exists in `shared/shared/db/models.py`
- [ ] Alembic migration created and applied successfully
- [ ] All 4 Gherkin scenarios have passing automated tests
- [ ] Code coverage ≥ 95% for models.py
- [ ] Lint passes: `ruff check` no errors
- [ ] Migration is reversible: `alembic downgrade -1` works
- [ ] Can insert and retrieve a real `LinearRegressionModel` artifact
- [ ] JSONB params can be queried with SQLAlchemy
- [ ] UNIQUE and CHECK constraints validated with tests
- [ ] GitHub Issue #8 updated and closed with summary

---

## Next Steps (After US-007)

1. **US-008**: Create `predictions` table with foreign key to `models.id`
2. **US-009**: Implement predictor job that uses both `models` and `predictions` tables
3. **Future**: Add CRUD helper functions for common model operations
