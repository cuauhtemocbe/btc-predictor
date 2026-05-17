# Implementation Plan: Daily BTC Price Predictor Job (US-009)

**Spec**: [us-009-daily-predictor.md](./us-009-daily-predictor.md)  
**Created**: 2026-05-17  
**Status**: approved

## Components

### 1. Predictor Logic (`workers/daily/predictor.py`)
- **Purpose**: Main entry point that orchestrates prediction workflow
- **Files**: `workers/daily/predictor.py`
- **Effort**: M (medium)
- **Key functions**:
  - `get_active_model()`: Load active model from DB
  - `get_recent_prices()`: Fetch last N prices for features
  - `prepare_features()`: Convert prices to feature vector
  - `check_existing_prediction()`: Verify no duplicate prediction exists
  - `save_prediction()`: Insert prediction record
  - `main()`: Orchestrate all steps

### 2. Test Suite (`workers/daily/tests/test_predictor.py`)
- **Purpose**: Comprehensive tests for all 4 Gherkin scenarios
- **Files**: `workers/daily/tests/test_predictor.py`
- **Effort**: M (medium)
- **Test categories**:
  - Happy path: Successful prediction
  - Error cases: No model, insufficient data
  - Idempotency: Prediction already exists

### 3. Integration with existing code
- **Purpose**: Wire up predictor with existing DB models and BaseModel
- **Files**: Imports only, no new files
- **Effort**: XS (extra small)
- **Dependencies**:
  - `shared.db.models`: Model, BtcPrice, Prediction
  - `shared.db.database`: Session management
  - `workers.daily.models.linear_regression`: LinearRegressionModel

## Dependencies

### Build Order

1. **Foundation** (already exists):
   - ✅ BaseModel abstract class (US-006)
   - ✅ LinearRegressionModel (US-006)
   - ✅ Model, Prediction SQLAlchemy classes (US-007, US-008)
   - ✅ Database session management

2. **Core predictor logic** (this PR):
   - Create `workers/daily/predictor.py`
   - Implement helper functions
   - Implement main orchestration

3. **Tests** (this PR):
   - Create test fixtures for models, prices, predictions
   - Write unit tests for helper functions
   - Write integration tests for end-to-end workflow

### External Dependencies

All dependencies already in `pyproject.toml`:
- `sqlalchemy`: Database ORM
- `numpy`: Feature preparation
- `pickle` (stdlib): Model deserialization

## Risks & Assumptions

### Risks

- **Risk 1**: Deserialization failure if model artifact is corrupted
  - **Mitigation**: Try/except around deserialize, log detailed error
  
- **Risk 2**: Race condition if predictor runs twice simultaneously
  - **Mitigation**: Use DB query to check existing prediction BEFORE insert (idempotency)

- **Risk 3**: Feature preparation mismatch with how model was trained
  - **Mitigation**: Use same feature preparation logic as trainer (will be shared in US-011)

### Assumptions

- ✅ Exactly one active model exists at any time (enforced by trainer logic)
- ✅ `btc_prices` table has continuous hourly data (no gaps)
- ⚠️ Model's `params['window_days']` matches the feature vector size it expects
- ✅ Tomorrow's date is calculated using system timezone (UTC in Docker)

## Milestones

- [ ] **M1**: Core predictor logic implemented and unit tested
- [ ] **M2**: Integration tests pass with real DB and serialized model
- [ ] **M3**: All 4 Gherkin scenarios covered with passing tests
- [ ] **M4**: Lint checks pass, ready for commit

## Tasks

### Foundation (Already Complete)
- [x] BaseModel abstract class exists
- [x] LinearRegressionModel implements BaseModel
- [x] Model, BtcPrice, Prediction tables exist
- [x] Alembic migrations applied

### Core Implementation (Build First)

- [ ] **Task 1**: Create `workers/daily/predictor.py` skeleton
  - **Acceptance**: File exists with main() entry point
  - **Files**: `workers/daily/predictor.py`
  - **Tests**: None yet (just skeleton)
  - **Effort**: XS

- [ ] **Task 2**: Implement `get_active_model(session)` function
  - **Acceptance**: Loads model where `is_active=True`, deserializes artifact, returns BaseModel instance
  - **Files**: `workers/daily/predictor.py`
  - **Tests**: Unit test with mocked session
  - **Effort**: S
  - **Error handling**:
    - No active model → raise ValueError with message "No active model found"
    - Multiple active models → raise ValueError (data integrity issue)
    - Deserialization fails → raise RuntimeError with details

- [ ] **Task 3**: Implement `get_recent_prices(session, window_days)` function
  - **Acceptance**: Fetches last N close prices from btc_prices, ordered by timestamp DESC
  - **Files**: `workers/daily/predictor.py`
  - **Tests**: Unit test with mocked session
  - **Effort**: S
  - **Error handling**:
    - Insufficient data → raise ValueError with message "Insufficient data: need X, have Y"

- [ ] **Task 4**: Implement `prepare_features(prices)` function
  - **Acceptance**: Converts list of Decimal close prices to numpy array of shape (1, N)
  - **Files**: `workers/daily/predictor.py`
  - **Tests**: Unit test with sample prices
  - **Effort**: XS
  - **Logic**:
    - Input: List of Decimal (from DB)
    - Output: `np.array([[float(p1), float(p2), ..., float(pN)]])`

- [ ] **Task 5**: Implement `check_existing_prediction(session, predicted_for)` function
  - **Acceptance**: Returns True if prediction already exists for given date, False otherwise
  - **Files**: `workers/daily/predictor.py`
  - **Tests**: Unit test with mocked session
  - **Effort**: XS

- [ ] **Task 6**: Implement `save_prediction(session, model_id, predicted_for, current_price, predicted_price)` function
  - **Acceptance**: Inserts new Prediction record with all required fields, actual_price=NULL
  - **Files**: `workers/daily/predictor.py`
  - **Tests**: Integration test with real DB
  - **Effort**: S
  - **Fields to populate**:
    - `model_id`: From active model
    - `predicted_for`: Tomorrow's date
    - `predicted_at`: `datetime.now(timezone.utc)`
    - `price_at_prediction`: Current BTC price
    - `predicted_price`: Model output
    - `actual_price`: NULL
    - All evaluation fields: NULL

- [ ] **Task 7**: Implement `main()` orchestration function
  - **Acceptance**: Calls all helper functions in correct order, handles errors, logs steps
  - **Files**: `workers/daily/predictor.py`
  - **Tests**: Integration test with full workflow
  - **Effort**: M
  - **Workflow**:
    1. Get DB session
    2. Calculate tomorrow's date
    3. Check if prediction already exists → if yes, log and exit 0
    4. Get active model
    5. Get window_days from model.params
    6. Get recent prices
    7. Prepare features
    8. Call model.predict()
    9. Get current price (latest from btc_prices)
    10. Save prediction
    11. Commit transaction
    12. Log success

### Testing (Build Second)

- [ ] **Task 8**: Create test fixtures in `workers/daily/tests/conftest.py`
  - **Acceptance**: Fixtures for db_session, sample_model, sample_prices, sample_predictions
  - **Files**: `workers/daily/tests/conftest.py`
  - **Tests**: N/A (fixtures)
  - **Effort**: S

- [ ] **Task 9**: Write unit tests for helper functions
  - **Acceptance**: All helper functions tested in isolation
  - **Files**: `workers/daily/tests/test_predictor.py`
  - **Tests**: 
    - `test_get_active_model_success()`
    - `test_get_active_model_not_found()`
    - `test_get_recent_prices_success()`
    - `test_get_recent_prices_insufficient_data()`
    - `test_prepare_features()`
    - `test_check_existing_prediction()`
    - `test_save_prediction()`
  - **Effort**: M

- [ ] **Task 10**: Write integration tests for all Gherkin scenarios
  - **Acceptance**: All 4 Gherkin scenarios have passing tests
  - **Files**: `workers/daily/tests/test_predictor.py`
  - **Tests**:
    - `test_predict_next_day_price()` (Scenario 1)
    - `test_insufficient_historical_data()` (Scenario 2)
    - `test_no_active_model()` (Scenario 3)
    - `test_prediction_already_exists()` (Scenario 4)
  - **Effort**: M

### Polish (Build Third)

- [ ] **Task 11**: Add logging throughout predictor.py
  - **Acceptance**: Log all major steps (model loaded, prices fetched, prediction saved)
  - **Files**: `workers/daily/predictor.py`
  - **Tests**: None (logging verification optional)
  - **Effort**: XS
  - **Log levels**:
    - INFO: Normal operations (model loaded, prediction saved)
    - WARNING: Idempotent skip (prediction exists)
    - ERROR: Failures (no model, insufficient data)

- [ ] **Task 12**: Run lint and fix issues
  - **Acceptance**: `ruff check` and `ruff format` pass
  - **Files**: All files
  - **Tests**: Lint as test
  - **Effort**: XS

- [ ] **Task 13**: Verify coverage >= 95%
  - **Acceptance**: `pytest --cov` shows >= 95% coverage for predictor.py
  - **Files**: N/A
  - **Tests**: Coverage report
  - **Effort**: XS

## Implementation Details

### Feature Preparation Logic

The feature vector must match what the model expects:

```python
def prepare_features(prices: list[Decimal]) -> npt.NDArray[np.float64]:
    """
    Convert list of close prices to feature vector.
    
    Args:
        prices: List of close prices, oldest to newest
    
    Returns:
        Numpy array of shape (1, len(prices)) for single prediction
    """
    # Convert Decimal to float
    prices_float = [float(p) for p in prices]
    # Reshape to (1, N) for single sample prediction
    return np.array([prices_float])
```

### Tomorrow's Date Calculation

```python
from datetime import date, timedelta, timezone

tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
```

### Query for Active Model

```python
from sqlalchemy import select
from shared.db.models import Model

stmt = select(Model).where(Model.is_active == True)
model_record = session.execute(stmt).scalar_one_or_none()

if model_record is None:
    raise ValueError("No active model found")
```

### Query for Recent Prices

```python
from sqlalchemy import select
from shared.db.models import BtcPrice

stmt = (
    select(BtcPrice.close)
    .order_by(BtcPrice.timestamp.desc())
    .limit(window_days)
)
results = session.execute(stmt).scalars().all()

if len(results) < window_days:
    raise ValueError(f"Insufficient data: need {window_days}, have {len(results)}")

# Reverse to get oldest to newest (for feature vector)
prices = list(reversed(results))
```

## Error Handling Strategy

All errors should be logged clearly and exit with appropriate codes:

| Error | Exit Code | Log Level | Message |
|-------|-----------|-----------|---------|
| No active model | 1 | ERROR | "No active model found in database" |
| Insufficient data | 1 | ERROR | "Insufficient data: need {window_days}, have {count}" |
| Deserialization error | 1 | ERROR | "Failed to deserialize model: {details}" |
| Prediction exists | 0 | WARNING | "Prediction for {date} already exists, skipping (idempotent)" |
| DB error | 1 | ERROR | "Database error: {details}" |

## Effort Estimate

**Total Estimated Time**: 1.5 - 2 days

| Phase | Effort |
|-------|--------|
| Core implementation (Tasks 1-7) | 1 day |
| Testing (Tasks 8-10) | 0.5 day |
| Polish & documentation (Tasks 11-13) | 0.5 day |

**Note**: Estimate assumes:
- Developer familiar with codebase (US-006, US-007, US-008 already completed)
- No major blockers or surprises
- Test database already configured
