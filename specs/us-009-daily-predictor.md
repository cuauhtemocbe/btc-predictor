---
title: Daily BTC Price Predictor Job
status: completed
created: 2026-05-17
updated: 2026-05-17
issue: #10
---

# Daily BTC Price Predictor Job (US-009)

## Objective

Create an automated job (`workers/daily/predictor.py`) that loads the active ML model, fetches recent BTC price data, predicts tomorrow's price, and stores the prediction in the database for later evaluation.

## Context

This job is part of the three-step daily workflow:
1. **Evaluator** (US-010): Evaluate yesterday's prediction
2. **Trainer** (US-011): Train model with updated data
3. **Predictor** (US-009): Predict tomorrow's price ← **This spec**

The predictor job runs as the final step in the daily cron, creating a new prediction record that will be evaluated the next day. This creates a continuous cycle of predict → evaluate → train → predict.

**Dependencies**:
- US-006: BaseModel abstract class ✅
- US-007: Models table ✅
- US-008: Predictions table ✅

## Requirements

### Functional Requirements

- [ ] Load the active model from `models` table (`is_active=True`)
- [ ] Fetch the last N close prices from `btc_prices` (where N = model's `window_days` param)
- [ ] Prepare feature vector X from historical prices
- [ ] Call `model.predict(X)` to get predicted price
- [ ] Get current BTC price (latest `close` from `btc_prices`)
- [ ] Insert prediction into `predictions` table with:
  - `predicted_for = tomorrow's date`
  - `predicted_at = now()`
  - `price_at_prediction = current price`
  - `predicted_price = model output`
  - `actual_price = NULL` (will be filled by evaluator next day)
- [ ] Handle edge cases:
  - No active model → log error, exit 1
  - Insufficient historical data → log error, exit 1
  - Prediction for tomorrow already exists → log info, exit 0 (idempotent)

### Non-Functional Requirements

- [ ] **Idempotency**: Running multiple times should not create duplicate predictions
- [ ] **Error handling**: Clear error messages for all failure modes
- [ ] **Logging**: Log all important steps (model loaded, data fetched, prediction created)
- [ ] **Performance**: Complete in < 5 seconds (simple linear regression)
- [ ] **Testability**: All logic testable with mocked DB and model

## Architecture

### Components

```
workers/daily/
├── __init__.py
├── predictor.py          ← Main predictor logic (this spec)
└── tests/
    └── test_predictor.py ← Test suite
```

### Data Flow

```
1. DB: models table (is_active=True)
   ↓
2. Load active model → deserialize from BYTEA
   ↓
3. DB: btc_prices (last N records)
   ↓
4. Prepare features → model.predict(X)
   ↓
5. DB: predictions (INSERT new record)
```

### Database Interactions

**Read**:
- `models` table: Find model where `is_active=True`
- `btc_prices` table: Fetch last N records ordered by timestamp DESC

**Write**:
- `predictions` table: INSERT new prediction record

### External Dependencies

- `shared.db.models`: Model, BtcPrice, Prediction SQLAlchemy classes
- `shared.db.database`: Database session
- `workers.daily.models.base`: BaseModel abstract class
- `workers.daily.models.linear_regression`: LinearRegressionModel (for deserialization)

## User Stories

**As** a data scientist  
**I want** a job that predicts tomorrow's BTC price  
**In order to** generate daily forecasts

**GitHub Issue**: #10

## Testing Strategy

### Unit Tests

- Test prediction logic with mocked model and DB
- Test feature preparation (converting prices to feature vector)
- Test error handling for all edge cases
- Test idempotency (prediction already exists)

### Integration Tests

- Test with real DB (PostgreSQL in Docker)
- Test with real serialized LinearRegressionModel
- Verify prediction record is created correctly
- Verify all fields are populated as expected

### Coverage Target

**Minimum: 95% coverage** (core prediction logic is critical)

### Test Data

- Mock models table with active/inactive models
- Mock btc_prices with varying amounts of data (0, 10, 30+ records)
- Mock predictions table with existing predictions

## Acceptance Criteria (Gherkin)

```gherkin
Feature: Daily price prediction

  Scenario: Predict next day price
    Given the models table has an active LinearRegressionModel (window_days=30)
    And the btc_prices table has 30+ records
    When I run "python -m daily.predictor"
    Then a new record is inserted into predictions
    And predicted_for = tomorrow's date
    And predicted_price is a float > 0
    And actual_price is NULL (not evaluated yet)

  Scenario: Insufficient historical data
    Given the btc_prices table has only 10 records
    And the active model requires window_days=30
    When I run "python -m daily.predictor"
    Then a ValueError is logged: "Insufficient data: need 30, have 10"
    And no prediction is inserted

  Scenario: No active model
    Given the models table has no record with is_active=True
    When I run "python -m daily.predictor"
    Then a ValueError is logged: "No active model found"
    And the job exits with code 1

  Scenario: Prediction already exists for tomorrow
    Given a prediction already exists for predicted_for=tomorrow
    When I run "python -m daily.predictor"
    Then the job logs "Prediction for tomorrow already exists, skipping"
    And the job exits with code 0 (success, idempotent)
```

## Boundaries & Constraints

### In Scope

- Load active model from database
- Fetch historical prices for feature preparation
- Generate prediction for tomorrow only (not multiple days ahead)
- Store prediction in database
- Error handling for common failure modes
- Idempotency (safe to run multiple times)

### Out of Scope

- Training or retraining models (US-011)
- Evaluating predictions (US-010)
- Multi-day forecasts (future enhancement)
- Confidence intervals (future enhancement)
- Real-time predictions (this is a daily batch job)
- Email/Slack notifications on prediction (future enhancement)

### Technical Constraints

- **Language**: Python 3.13
- **Database**: PostgreSQL via SQLAlchemy
- **Model format**: Serialized pickle in models.artifact (BYTEA)
- **Execution environment**: Docker container (same as fetch-price job)
- **Entry point**: `python -m daily.predictor`

## Success Criteria

- [ ] All 4 Gherkin scenarios have passing automated tests
- [ ] Predictor can load and deserialize active model from DB
- [ ] Prediction record is created with all required fields
- [ ] Job is idempotent (running twice doesn't create duplicates)
- [ ] Error messages are clear and actionable
- [ ] Code coverage >= 95%
- [ ] Lint checks pass (ruff)
- [ ] Integration test with real DB passes

## Implementation Plan

See: `specs/us-009-daily-predictor-plan.md`
