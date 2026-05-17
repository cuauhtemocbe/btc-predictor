---
title: US-007 - Models Table for ML Model Versioning
status: draft
created: 2026-05-17
updated: 2026-05-17
issue: #8
iteration: 4
user_story: US-007
---

# US-007: Models Table for ML Model Versioning

## Objective

Create a PostgreSQL table to store trained ML models with their serialized artifacts, training metadata, and versioning information. This enables model tracking, versioning, and rollback capabilities for the BTC price prediction system.

## Context

### Problem Statement

After implementing the abstract `BaseModel` class and `LinearRegressionModel` (US-006), we need persistent storage for trained models. The daily cron job will:
1. Train a new model each day
2. Store the serialized model in the database
3. Retrieve the active model for predictions

Without a models table, we cannot:
- Version models over time
- Compare model performance across versions
- Rollback to a previous model if needed
- Track training metadata (date range, parameters)

### User Need

As a data scientist, I want to store trained models in the database so that I can:
- Version models and track which version is currently active
- Store training metadata (date range, hyperparameters)
- Deserialize and load models for prediction
- Compare performance across model versions
- Rollback to a previous model if the latest performs poorly

### Business Justification

Model versioning is essential for:
- **Reproducibility**: Know exactly which model generated a prediction
- **Debugging**: Track down issues to specific model versions
- **Performance tracking**: Compare error rates across versions
- **Operational safety**: Rollback if a new model performs poorly

## Requirements

### Functional Requirements

- [ ] Create SQLAlchemy `Model` class in `shared/shared/db/models.py`
- [ ] Generate Alembic migration for `models` table
- [ ] Support INSERT of trained models with serialized artifacts
- [ ] Support QUERY for active model by name
- [ ] Support storing training parameters as JSONB
- [ ] Support storing serialized model as BYTEA (pickle format)

### Non-Functional Requirements

- [ ] **Storage efficiency**: Serialized model artifact < 1MB (95th percentile)
- [ ] **Query performance**: Retrieve active model in < 10ms (P95)
- [ ] **Data integrity**: Foreign key constraints for predictions → models
- [ ] **Idempotency**: Can run migration multiple times safely

## Architecture

### Database Schema

```sql
CREATE TABLE models (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,          -- e.g., "linear_v1", "lstm_v1"
    version VARCHAR(50) NOT NULL,         -- e.g., "1.0.0", "2024-05-17-001"
    params JSONB NOT NULL,                -- {"window_days": 30, "features": ["close"]}
    artifact BYTEA NOT NULL,              -- Pickled model bytes
    trained_at TIMESTAMP NOT NULL,        -- When training completed
    train_from DATE NOT NULL,             -- Training data start date
    train_to DATE NOT NULL,               -- Training data end date
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    
    CONSTRAINT unique_model_version UNIQUE (name, version),
    CONSTRAINT valid_training_period CHECK (train_to >= train_from)
);

CREATE INDEX idx_models_active ON models (name, is_active) WHERE is_active = TRUE;
```

### Components

1. **SQLAlchemy Model** (`shared/shared/db/models.py`)
   - `Model` class with all columns
   - Relationships: `predictions` (one-to-many)
   
2. **Alembic Migration** (`shared/alembic/versions/XXX_create_models_table.py`)
   - Create `models` table
   - Add indexes for query performance
   - Add constraints for data integrity

3. **CRUD Functions** (future, not in this US)
   - `get_active_model(name: str) -> Model`
   - `save_model(name, version, params, artifact, ...) -> Model`
   - `deactivate_model(model_id: int) -> None`

### Data Model

**Entity: Model**
- Represents a trained ML model at a specific point in time
- Each model has a unique (name, version) combination
- Only 1 model per name can have `is_active=True` (enforced by application logic)

**Relationships:**
- `Model` → `Prediction` (one-to-many): A model generates many predictions
- Future: `Model` → `ModelEvaluation` for tracking aggregate metrics

### Technology Stack

- **ORM**: SQLAlchemy 2.0
- **Migrations**: Alembic
- **Serialization**: Python `pickle` module
- **Database**: PostgreSQL (JSONB, BYTEA support)

## User Stories

**Primary User Story**: US-007 (Issue #8)

**Related Stories:**
- US-006: BaseModel abstract class (dependency - COMPLETED)
- US-008: Predictions table (depends on this US)
- US-009: Predictor job (will use this table)

## Testing Strategy

### Unit Tests

**Location**: `shared/tests/test_models.py`

Test the SQLAlchemy `Model` class:
- Create instance with valid data
- Validate JSONB params serialization
- Validate BYTEA artifact storage
- Test constraints (UNIQUE, CHECK)

### Integration Tests

**Location**: `shared/tests/test_models_integration.py`

Test database operations:
1. **Scenario: Create models table via migration**
   - Run `alembic upgrade head`
   - Verify table exists with correct columns
   - Verify indexes exist
   - Verify constraints exist

2. **Scenario: Insert trained model**
   - Serialize a `LinearRegressionModel` to bytes
   - Insert into `models` table
   - Query back and verify all fields match

3. **Scenario: Retrieve active model**
   - Insert 3 models with same name
   - Set only 1 to `is_active=True`
   - Query for active model
   - Verify correct model returned

4. **Scenario: Store params as JSONB**
   - Insert model with complex params dict
   - Query back and verify JSONB structure
   - Test JSONB query operators (e.g., `params->>'window_days'`)

5. **Scenario: Constraint validation**
   - Test UNIQUE constraint (duplicate name+version fails)
   - Test CHECK constraint (train_to < train_from fails)

### Coverage Target

**Minimum: 95% coverage** for `models.py` and migration

### Test Commands

```bash
# Run all model tests
docker compose exec api pytest shared/tests/test_models.py -v

# Run with coverage
docker compose exec api pytest shared/tests/test_models.py --cov=shared.db.models --cov-report=term-missing

# Run integration tests only
docker compose exec api pytest shared/tests/test_models_integration.py -v
```

## Boundaries & Constraints

### In Scope

- ✅ SQLAlchemy `Model` class definition
- ✅ Alembic migration for `models` table
- ✅ Schema with JSONB params and BYTEA artifact
- ✅ Indexes for query performance
- ✅ Constraints for data integrity
- ✅ Integration tests for all Gherkin scenarios

### Out of Scope

- ❌ CRUD helper functions (save_model, get_active_model) - will be added in US-009
- ❌ Model performance tracking/evaluation - separate US
- ❌ Model comparison/diff logic - future feature
- ❌ Automatic model deactivation logic - handled by trainer job
- ❌ Model artifact compression - can add later if needed
- ❌ S3/object storage for artifacts - start with BYTEA, migrate later if needed

### Technical Constraints

- **Database**: Must use PostgreSQL (JSONB and BYTEA support required)
- **Serialization**: Must use Python `pickle` (compatible with scikit-learn)
- **Schema**: Must support foreign key from `predictions.model_id` (future US-008)
- **Versioning**: Version string format is flexible (semantic versioning recommended)

### Assumptions

1. Model artifacts will remain < 1MB for linear models (sklearn models are small)
2. BYTEA column is acceptable for storage (no need for S3/object storage yet)
3. Only 1 active model per name at a time (enforced by application, not DB constraint)
4. `pickle` is safe within our controlled environment (not accepting external pickles)

## Success Criteria

- [ ] `models` table exists with all required columns
- [ ] All 4 Gherkin scenarios have passing automated tests
- [ ] Alembic migration runs successfully (up and down)
- [ ] Can insert a serialized `LinearRegressionModel` and retrieve it
- [ ] JSONB params can be queried and filtered
- [ ] UNIQUE constraint prevents duplicate (name, version)
- [ ] Code coverage ≥ 95% for models.py
- [ ] Lint/build passes (`ruff check`, no errors)
- [ ] Migration is reversible (`alembic downgrade -1` works)

## Implementation Plan

See `specs/us-007-models-table-plan.md` (to be created in Phase 2)

---

## Notes

### Design Decisions

1. **BYTEA vs. File Storage**
   - Choose BYTEA for simplicity (no file management, backups included)
   - Can migrate to S3 later if models grow large

2. **JSONB vs. JSON**
   - Choose JSONB for better query performance and indexing
   - Supports operators like `->`, `->>`, `@>` for filtering

3. **Version Format**
   - Flexible string (not enforced by DB)
   - Recommended: semantic versioning (e.g., "1.0.0") or timestamp (e.g., "2024-05-17-001")

4. **Active Model Enforcement**
   - Application logic (not DB constraint) to prevent multiple active models
   - Simpler to implement, easier to change logic later

### Related Documentation

- CLAUDE.md: Database schema overview
- ARCHITECTURE.md: Multi-service architecture
- US-006 spec: BaseModel and LinearRegressionModel

### Migration Path

This US is part of **Iteration 4: ML Foundation**
- US-006 (COMPLETED): Abstract BaseModel + LinearRegressionModel
- **US-007 (THIS)**: Models table
- US-008 (NEXT): Predictions table
- US-009: Predictor job (uses both tables)
