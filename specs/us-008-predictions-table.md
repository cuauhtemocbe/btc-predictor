---
title: US-008 - Predictions Table with Prediction + Evaluation Fields
status: completed
created: 2026-05-17
updated: 2026-05-17
issue: #9
iteration: 5
size: S (1 day)
---

# US-008: Predictions Table with Prediction + Evaluation Fields

## Objective

Create a `predictions` table to store daily Bitcoin price predictions and their subsequent evaluation, enabling tracking of model accuracy, errors, and profitability over time through a two-phase insert-then-update lifecycle.

## Context

This is the foundation for the prediction and evaluation system (Iteration 5). The predictions table implements a two-phase lifecycle:

1. **Phase 1 (Insert)**: When predictor job runs, insert prediction with `predicted_price`, leaving evaluation fields NULL
2. **Phase 2 (Update)**: Next day, evaluator job updates with `actual_price`, calculates errors, direction correctness, and simulated PnL

This design separates concerns: prediction logic runs independently from evaluation logic, making debugging easier and allowing predictions to exist before they can be evaluated.

### User Persona

**As** a data scientist  
**I want** a predictions table to store daily predictions and their evaluation  
**In order to** track model accuracy over time

### Related User Stories

- **US-007** (prerequisite): Models table - provides `model_id` foreign key
- **US-009** (next): Prediction job - will insert records into this table
- **US-010** (next): Evaluation job - will update records with evaluation data

## Requirements

### Functional Requirements

- [ ] Table `predictions` exists with all required columns
- [ ] `model_id` is a foreign key to `models.id` with CASCADE delete
- [ ] Predictions can be inserted with evaluation fields NULL (phase 1)
- [ ] Predictions can be updated with evaluation data (phase 2)
- [ ] Can query unevaluated predictions (`actual_price IS NULL`)
- [ ] Can query predictions by date range
- [ ] Can query predictions by model

### Non-Functional Requirements

- [ ] **Performance**: Index on `predicted_for` for date range queries (< 10ms)
- [ ] **Performance**: Index on `model_id` for model-specific queries (< 10ms)
- [ ] **Data Integrity**: Foreign key constraint prevents orphaned predictions
- [ ] **Data Integrity**: `predicted_for` should be DATE type (not timestamp)
- [ ] **Testability**: Migration reversible (`alembic downgrade -1` works)

## Architecture

### Database Schema

**Table**: `predictions`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY, AUTOINCREMENT | Unique identifier |
| `model_id` | INTEGER | FOREIGN KEY → models.id, NOT NULL | Model that made prediction |
| `predicted_for` | DATE | NOT NULL | Date being predicted (tomorrow) |
| `predicted_at` | TIMESTAMP | NOT NULL, DEFAULT NOW() | When prediction was made |
| `price_at_prediction` | NUMERIC(10,2) | NOT NULL | BTC price when prediction made |
| `predicted_price` | NUMERIC(10,2) | NOT NULL | Predicted BTC price |
| `actual_price` | NUMERIC(10,2) | NULL | Actual price (filled next day) |
| `evaluated_at` | TIMESTAMP | NULL | When evaluation happened |
| `error_abs` | NUMERIC(10,2) | NULL | Absolute error: \|actual - predicted\| |
| `error_pct` | NUMERIC(5,2) | NULL | Percentage error: (actual - predicted) / actual * 100 |
| `direction_correct` | BOOLEAN | NULL | True if predicted direction was correct |
| `pnl_simulated` | NUMERIC(10,2) | NULL | Simulated PnL from trading strategy |

**Indexes**:
- Primary key on `id`
- Index on `model_id` (for model-specific queries)
- Index on `predicted_for` (for date range queries)

**Foreign Keys**:
- `model_id` → `models.id` ON DELETE CASCADE

### Component Structure

```
shared/
├── shared/db/
│   └── models.py              # Add Prediction SQLAlchemy model
└── alembic/
    └── versions/
        └── {hash}_add_predictions_table.py  # New migration
```

### Data Flow

```
Phase 1 - Insert (Predictor Job):
  predictor → insert(model_id, predicted_for, predicted_price, price_at_prediction)
           → predictions table (actual_price = NULL)

Phase 2 - Update (Evaluator Job):
  evaluator → fetch(WHERE actual_price IS NULL AND predicted_for = yesterday)
           → calculate errors and PnL
           → update(actual_price, evaluated_at, errors, pnl)
           → predictions table (evaluation fields filled)
```

### External Dependencies

- **SQLAlchemy 2.0**: ORM for model definition
- **Alembic**: Database migration tool
- **PostgreSQL**: Target database (NUMERIC type support)

## User Stories

See GitHub Issue #9 for complete user story.

**Gherkin Acceptance Criteria**:

```gherkin
Feature: Predictions table

  Scenario: Create predictions table via migration
    When I run "alembic upgrade head"
    Then a table named "predictions" exists
    And it has columns: id, model_id, predicted_for, predicted_at, price_at_prediction, predicted_price, actual_price, evaluated_at, error_abs, error_pct, direction_correct, pnl_simulated
    And model_id is a foreign key to models.id

  Scenario: Insert new prediction (before evaluation)
    Given a trained model with id=123
    When I insert a prediction for predicted_for="2026-05-17" with predicted_price=68000.0
    And actual_price, error_abs, error_pct, direction_correct, pnl_simulated are NULL
    Then the record is saved successfully

  Scenario: Update prediction with evaluation (next day)
    Given a prediction exists for predicted_for="2026-05-16" with predicted_price=67000.0
    And actual_price is NULL
    When I update the record with actual_price=67500.0, error_abs=500.0, error_pct=0.74
    Then the record is updated successfully
    And evaluated_at is set to current timestamp

  Scenario: Query unevaluated predictions
    Given predictions table has 10 records
    And 3 have actual_price=NULL (unevaluated)
    When I query for predictions WHERE actual_price IS NULL
    Then I receive 3 records
```

## Testing Strategy

### Integration Tests

**File**: `shared/tests/test_predictions_model.py`

1. **Migration test**: Verify `alembic upgrade head` creates table with correct schema
2. **Insert test**: Insert prediction with NULL evaluation fields
3. **Update test**: Update prediction with evaluation data
4. **Query test**: Query unevaluated predictions
5. **Foreign key test**: Verify CASCADE delete when model is deleted
6. **Constraint test**: Verify NOT NULL constraints on required fields

### Test Database Setup

Use same postgres container with pytest fixtures (as per CLAUDE.md):
- Fixtures create test data before each test
- Automatic cleanup via `yield` pattern
- No separate test database needed

### Coverage Target

**Minimum 95% coverage** for:
- `shared/shared/db/models.py` (Prediction model)
- Alembic migration file

### Test Commands

```bash
# Run all prediction tests
docker compose exec api pytest shared/tests/test_predictions_model.py -v

# Run specific scenario
docker compose exec api pytest shared/tests/test_predictions_model.py::test_insert_prediction_phase1 -v

# With coverage
docker compose exec api pytest shared/tests/test_predictions_model.py --cov=shared.db.models --cov-report=term-missing
```

## Boundaries & Constraints

### In Scope
- SQLAlchemy `Prediction` model definition
- Alembic migration to create `predictions` table
- Integration tests for all Gherkin scenarios
- Database indexes for performance
- Foreign key relationship to `models` table

### Out of Scope
- Prediction job implementation (US-009)
- Evaluation job implementation (US-010)
- PnL calculation logic (in US-010)
- Error calculation logic (in US-010)
- API endpoints to query predictions (US-011)
- Dashboard UI to display predictions (US-012)

### Technical Constraints
- Must use SQLAlchemy 2.0 declarative style
- Must use Alembic for migrations (no manual SQL)
- Must run inside Docker container (`docker compose exec api`)
- Must follow existing model patterns (see `BtcPrice`, `Model` classes)
- Must be compatible with PostgreSQL (NUMERIC type, CASCADE)

## Success Criteria

- [ ] All 4 Gherkin scenarios have passing automated tests
- [ ] Migration creates table with correct schema (`alembic upgrade head`)
- [ ] Migration is reversible (`alembic downgrade -1` works)
- [ ] Foreign key constraint works (deleting model deletes predictions)
- [ ] Can insert prediction with NULL evaluation fields
- [ ] Can update prediction with evaluation data
- [ ] Can query unevaluated predictions
- [ ] Code coverage ≥ 95% for Prediction model
- [ ] Lint check passes (`ruff check`)
- [ ] Type hints present on all methods

## Implementation Plan

See `specs/us-008-predictions-table-plan.md` (to be created in Phase 2)

---

## Changelog

- **2026-05-17**: Initial spec created (Phase 1: Specify)
