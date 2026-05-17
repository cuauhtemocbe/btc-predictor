---
title: ML Model Base Class and Linear Regression Implementation
status: completed
created: 2026-05-17
updated: 2026-05-17
issue: #7
user_story: US-006
---

# ML Model Base Class and Linear Regression Implementation

## Objective

Create an abstract base class (`BaseModel`) that defines a standardized interface for all ML prediction models, and implement a concrete `LinearRegressionModel` using scikit-learn. This enables easy addition of new prediction models (LSTM, XGBoost, ARIMA) in the future without changing the infrastructure.

## Context

### Problem Statement

The BTC Predictor project needs to train ML models to predict Bitcoin prices. Currently, there's no standardized way to:
- Train models with historical data
- Make predictions with new data
- Serialize/deserialize models for storage in the database
- Swap between different ML algorithms

### User Need

Data scientists want to experiment with different prediction algorithms (Linear Regression, LSTM, XGBoost, ARIMA) without rewriting the daily prediction job infrastructure. A common interface ensures all models are interchangeable.

### Why Now

This is **Iteration 4** of the project. The foundation is ready:
- ✅ Database schema (`btc_prices`, `models`, `predictions` tables) - US-001, US-002
- ✅ Binance API client for fetching prices - US-003
- ✅ Hourly fetch-price job populating `btc_prices` - US-004
- ✅ API endpoint to query prices - US-005

Next step: Build the ML layer so we can start making predictions (US-008, US-009, US-010).

## Requirements

### Functional Requirements

- [ ] **FR-1**: Abstract `BaseModel` class with required methods: `train()`, `predict()`, `serialize()`, `deserialize()`
- [ ] **FR-2**: `BaseModel` cannot be instantiated directly (must raise `TypeError`)
- [ ] **FR-3**: `LinearRegressionModel` implements `BaseModel` using sklearn's `LinearRegression`
- [ ] **FR-4**: Train model with sliding window features (default: 30 days of close prices)
- [ ] **FR-5**: Predict next day's BTC close price given last N days
- [ ] **FR-6**: Serialize trained model to bytes (pickle format) for database storage
- [ ] **FR-7**: Deserialize bytes back to trained model instance
- [ ] **FR-8**: Track model training status via `is_trained` property

### Non-Functional Requirements

- [ ] **Performance**: Model training completes in < 1 second with 60 days of data
- [ ] **Storage**: Serialized model size < 1MB (sklearn models are lightweight)
- [ ] **Testability**: All code testable with synthetic data (no real Binance API calls)
- [ ] **Extensibility**: Adding new model types requires only implementing 4 methods
- [ ] **Type Safety**: Full type hints for all public methods

## Architecture

### Components

```
workers/daily/models/
├── __init__.py          # Export BaseModel, LinearRegressionModel
├── base.py              # Abstract BaseModel class
└── linear.py            # LinearRegressionModel implementation
```

### Class Diagram

```
┌─────────────────────────────────┐
│      BaseModel (ABC)            │
├─────────────────────────────────┤
│ + train(X, y) → None            │
│ + predict(X) → float            │
│ + serialize() → bytes           │
│ + deserialize(bytes) → Self     │ (class method)
│ + is_trained → bool             │ (property)
└─────────────────────────────────┘
              ▲
              │ inherits
              │
┌─────────────────────────────────┐
│   LinearRegressionModel         │
├─────────────────────────────────┤
│ - model: LinearRegression       │
│ - _is_trained: bool             │
│ - window_days: int              │
├─────────────────────────────────┤
│ + __init__(window_days=30)      │
│ + train(X, y) → None            │
│ + predict(X) → float            │
│ + serialize() → bytes           │
│ + deserialize(bytes) → Self     │
│ + is_trained → bool             │
└─────────────────────────────────┘
```

### Data Model

**No database changes needed** — this is pure ML logic.

Models will be stored in the existing `models` table (from US-002):
- `artifact` column: stores `model.serialize()` output (bytes)
- `params` column: stores model hyperparameters (JSONB)

### External Dependencies

- **scikit-learn** (`^1.5.0`): Linear regression implementation
- **numpy** (`^2.0.0`): Array operations for features/labels
- **pickle** (stdlib): Model serialization

### Feature Engineering

**Sliding Window Approach:**

Given `window_days=30`:
- **Input features (X)**: Last 30 days of close prices → shape `(n_samples, 30)`
- **Target label (y)**: Next day's close price → shape `(n_samples,)`

Example with 60 days of data:
```python
# Day 1-30 → predict day 31
# Day 2-31 → predict day 32
# Day 3-32 → predict day 33
# ...
# Day 30-59 → predict day 60
# Total: 30 training samples
```

## User Stories

**Reference**: GitHub Issue #7 (US-006)

**User Story:**
> **As** a data scientist  
> **I want** an abstract base class for ML models  
> **In order to** easily add new prediction models in the future

**Acceptance Criteria** (Gherkin format):

```gherkin
Feature: ML model abstraction

  Scenario: BaseModel cannot be instantiated
    When I attempt to instantiate BaseModel()
    Then a TypeError is raised with message "Cannot instantiate abstract class"

  Scenario: Train LinearRegressionModel with valid data
    Given I have 60 days of BTC close prices
    When I create features with window_days=30
    And I call model.train(X, y) with 30 samples
    Then the model trains successfully
    And model.is_trained is True

  Scenario: Predict next price
    Given a trained LinearRegressionModel
    When I call model.predict(X_new) with the last 30 close prices
    Then the model returns a float predicted_price
    And predicted_price is > 0

  Scenario: Serialize model to bytes
    Given a trained LinearRegressionModel
    When I call model.serialize()
    Then it returns a bytes object (pickled model)
    And the bytes size is < 1MB

  Scenario: Deserialize model from bytes
    Given a serialized model as bytes
    When I call LinearRegressionModel.deserialize(bytes)
    Then it returns a trained LinearRegressionModel instance
    And model.is_trained is True
```

## Testing Strategy

### Unit Tests

**File**: `workers/daily/tests/test_models.py`

Test coverage for each Gherkin scenario:

1. **Abstract class validation**:
   - Attempt `BaseModel()` instantiation → raises `TypeError`
   - Verify all methods are abstract

2. **Training**:
   - Train with synthetic data (60 days, window=30)
   - Verify `is_trained` property
   - Train with edge case: minimum data (31 days)
   - Train with large data (365 days)

3. **Prediction**:
   - Predict with trained model
   - Verify output is float > 0
   - Predict with untrained model → raises error
   - Predict with wrong input shape → raises error

4. **Serialization**:
   - Serialize trained model → verify bytes type
   - Verify size < 1MB
   - Serialize untrained model → should work (store empty state)

5. **Deserialization**:
   - Deserialize bytes → verify model works
   - Verify `is_trained` preserved
   - Deserialize corrupted bytes → raises error

**Coverage Target**: 100% (this is core infrastructure)

**Test Data**: Synthetic close prices (use `np.random` or linear trend)

### Integration Tests

**Not needed for this US** — integration with database happens in US-007 (daily job).

### Performance Tests

- Train with 365 days of data → measure time (should be < 1 second)
- Verify serialized size < 1MB

## Boundaries & Constraints

### In Scope

- Abstract `BaseModel` class with 4 required methods + 1 property
- `LinearRegressionModel` implementation using sklearn
- Sliding window feature engineering (30 days default)
- Pickle-based serialization
- Complete unit test suite for all Gherkin scenarios

### Out of Scope

- ❌ Database integration (handled in US-007 - daily job)
- ❌ Actual Binance data fetching (use synthetic data for tests)
- ❌ Model hyperparameter tuning (use sklearn defaults)
- ❌ Cross-validation or train/test split (daily job handles this)
- ❌ Feature scaling or normalization (future optimization)
- ❌ Other model types (LSTM, XGBoost) — future iterations
- ❌ Model versioning logic (US-007 handles active model selection)

### Technical Constraints

- **Python**: 3.13
- **Framework**: Pure Python + sklearn (no ML frameworks like TensorFlow/PyTorch yet)
- **Serialization**: Must use pickle (compatible with `BYTEA` column in Postgres)
- **Window size**: Configurable, default 30 days
- **Dependencies**: Must be added to `workers/pyproject.toml`

### Assumptions

- Historical price data is available (from `btc_prices` table via US-004)
- Close price is sufficient for prediction (no need for OHLV initially)
- Linear relationship between past prices and future price is acceptable baseline
- 30-day window provides enough signal (can be tuned later)

## Success Criteria

- [ ] All 5 Gherkin scenarios have passing automated tests
- [ ] `BaseModel` cannot be instantiated (raises `TypeError`)
- [ ] `LinearRegressionModel` trains successfully with 60+ days of data
- [ ] Trained model predicts positive float values
- [ ] Serialized model size < 1MB
- [ ] Deserialized model produces same predictions as original
- [ ] Code passes lint checks (`ruff check`)
- [ ] Test coverage ≥ 100% for `models/` directory
- [ ] Type hints pass `mypy` validation
- [ ] Documentation includes usage examples

## Implementation Plan

See: [specs/ml-base-model-plan.md](./ml-base-model-plan.md)

## Related User Stories

- **US-001**: Shared package with database configuration (prerequisite)
- **US-002**: btc_prices table with Alembic migrations (prerequisite)
- **US-007**: Daily job - trainer component (depends on this)
- **US-008**: Daily job - predictor component (depends on this)
- **US-009**: Daily job - evaluator component (depends on this)

## References

- [scikit-learn LinearRegression docs](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LinearRegression.html)
- Python ABC module: `from abc import ABC, abstractmethod`
- GitHub Issue #7: https://github.com/cuauhtemocbe/btc-predictor/issues/7
