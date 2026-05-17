# Implementation Plan: ML Model Base Class and Linear Regression

**Spec**: [ml-base-model.md](./ml-base-model.md)  
**Created**: 2026-05-17  
**Status**: completed  
**Issue**: #7

## Components

### 1. BaseModel Abstract Class
- **Purpose**: Define standard interface for all ML models
- **Files**: `workers/daily/models/base.py`
- **Effort**: XS (1-2 hours)
- **Key Features**:
  - ABC with abstract methods: `train()`, `predict()`, `serialize()`, `deserialize()`
  - Property: `is_trained`
  - Type hints for all methods
  - Docstrings with usage examples

### 2. LinearRegressionModel Implementation
- **Purpose**: Concrete model using sklearn's LinearRegression
- **Files**: `workers/daily/models/linear.py`
- **Effort**: S (3-4 hours)
- **Key Features**:
  - Sliding window feature engineering
  - Configurable `window_days` parameter
  - Pickle-based serialization
  - Error handling for untrained predictions

### 3. Test Suite
- **Purpose**: Validate all 5 Gherkin scenarios
- **Files**: `workers/daily/tests/test_models.py`
- **Effort**: M (4-6 hours)
- **Key Features**:
  - Test fixtures for synthetic data
  - 100% code coverage
  - Edge case validation (ZOMBIES)

### 4. Module Structure
- **Purpose**: Package organization and exports
- **Files**: `workers/daily/models/__init__.py`
- **Effort**: XS (15 minutes)
- **Key Features**:
  - Export `BaseModel` and `LinearRegressionModel`
  - Module-level docstring

## Dependencies

### Build Order
1. **BaseModel** (foundation) - must be created first
2. **LinearRegressionModel** (depends on BaseModel) - implements abstract interface
3. **Test Suite** (depends on both) - validates implementation
4. **Module Init** (depends on all) - exports public API

### External Dependencies

Add to `workers/pyproject.toml`:
```toml
[tool.poetry.dependencies]
scikit-learn = "^1.5.0"
numpy = "^2.0.0"
```

### Internal Dependencies
- Uses `shared` package for config (already available from US-001)
- No database access needed (pure ML logic)

## Risks & Assumptions

### Risks

**Risk 1: Pickle Security**
- **Description**: Pickle deserialization can execute arbitrary code if bytes are tampered
- **Mitigation**: 
  - Only deserialize bytes from trusted source (our own database)
  - Add validation: check model type after deserialization
  - Future: consider joblib or custom serialization

**Risk 2: Sklearn Version Compatibility**
- **Description**: Model serialized with sklearn 1.5.0 may not deserialize with 1.6.0
- **Mitigation**:
  - Pin sklearn version in pyproject.toml
  - Store sklearn version in `models.params` JSONB column
  - Add deserialization version check

**Risk 3: Window Size Too Small/Large**
- **Description**: 30 days may be insufficient or excessive for good predictions
- **Mitigation**:
  - Make `window_days` configurable (not hardcoded)
  - Document in `models.params` for each trained model
  - Future: add hyperparameter tuning (US-014+)

### Assumptions

- Close price alone is sufficient for prediction (validated assumption from ARCHITECTURE.md)
- 30-day window provides enough signal (can be tuned later)
- Linear relationship is acceptable baseline (before trying LSTM, XGBoost)
- Pickle serialization is fast enough (< 100ms for sklearn models)
- Test data doesn't need to match real BTC price distributions

## Milestones

- [ ] **M1: BaseModel Abstract Class** - abstract methods defined, cannot instantiate
- [ ] **M2: LinearRegressionModel Core** - train + predict working with synthetic data
- [ ] **M3: Serialization** - serialize/deserialize preserves model state
- [ ] **M4: Test Suite Complete** - all 5 Gherkin scenarios passing
- [ ] **M5: Code Quality** - lint, type hints, 100% coverage

## Tasks

### Foundation (Build First)

#### Task 1: Create BaseModel Abstract Class
- **Acceptance**: 
  - `BaseModel` class exists in `workers/daily/models/base.py`
  - Inherits from `ABC`
  - Has abstract methods: `train()`, `predict()`, `serialize()`, `deserialize()`
  - Has abstract property: `is_trained`
  - Cannot be instantiated (raises `TypeError`)
- **Files**: 
  - Create: `workers/daily/models/base.py`
  - Create: `workers/daily/models/__init__.py`
- **Tests**: 
  - Test instantiation raises `TypeError`
  - Test all methods are abstract
- **Effort**: XS

#### Task 2: Set Up Test Infrastructure
- **Acceptance**:
  - Test file exists: `workers/daily/tests/test_models.py`
  - Fixtures for synthetic data (60 days of close prices)
  - Pytest runs without errors
- **Files**:
  - Create: `workers/daily/tests/test_models.py`
  - Update: `workers/daily/tests/conftest.py` (if needed for fixtures)
- **Tests**: N/A (this is test infrastructure)
- **Effort**: XS

### Core Implementation (Build Second)

#### Task 3: Implement LinearRegressionModel.__init__
- **Acceptance**:
  - `LinearRegressionModel` class exists in `workers/daily/models/linear.py`
  - Inherits from `BaseModel`
  - Constructor accepts `window_days` parameter (default=30)
  - Initializes sklearn `LinearRegression` instance
  - Sets `_is_trained = False`
- **Files**:
  - Create: `workers/daily/models/linear.py`
  - Update: `workers/daily/models/__init__.py` (export)
- **Tests**:
  - Test instantiation succeeds
  - Test default window_days is 30
  - Test custom window_days is stored
- **Effort**: XS

#### Task 4: Implement train() Method
- **Acceptance**:
  - `train(X, y)` method accepts numpy arrays
  - X shape: `(n_samples, window_days)`
  - y shape: `(n_samples,)`
  - Trains sklearn model with `model.fit(X, y)`
  - Sets `_is_trained = True` after successful training
  - Type hints present
- **Files**:
  - Update: `workers/daily/models/linear.py`
- **Tests**:
  - Train with 60 days data (30 samples)
  - Verify `is_trained` becomes True
  - Train with minimum data (1 sample)
  - Train with large data (365 days)
- **Effort**: S

#### Task 5: Implement predict() Method
- **Acceptance**:
  - `predict(X)` method accepts numpy array
  - X shape: `(1, window_days)` for single prediction
  - Returns float (predicted close price)
  - Raises error if model not trained
  - Type hints present
- **Files**:
  - Update: `workers/daily/models/linear.py`
- **Tests**:
  - Predict with trained model returns float
  - Predict value is > 0
  - Predict with untrained model raises `ValueError`
  - Predict with wrong shape raises error
- **Effort**: S

#### Task 6: Implement serialize() Method
- **Acceptance**:
  - `serialize()` returns bytes
  - Uses `pickle.dumps()` to serialize sklearn model + metadata
  - Serialized size < 1MB
  - Works with both trained and untrained models
  - Type hints present
- **Files**:
  - Update: `workers/daily/models/linear.py`
- **Tests**:
  - Serialize trained model → verify bytes type
  - Verify size < 1MB
  - Serialize untrained model → works
- **Effort**: S

#### Task 7: Implement deserialize() Class Method
- **Acceptance**:
  - `deserialize(data: bytes)` is a class method
  - Uses `pickle.loads()` to restore model
  - Returns `LinearRegressionModel` instance
  - Preserves `is_trained` state
  - Raises error for corrupted bytes
  - Type hints present
- **Files**:
  - Update: `workers/daily/models/linear.py`
- **Tests**:
  - Deserialize bytes → verify model works
  - Verify predictions match original model
  - Verify `is_trained` preserved
  - Deserialize corrupted bytes → raises `pickle.UnpicklingError`
- **Effort**: S

### Testing & Polish (Build Third)

#### Task 8: Complete Gherkin Test Coverage
- **Acceptance**:
  - All 5 Gherkin scenarios have passing tests:
    1. BaseModel cannot be instantiated
    2. Train LinearRegressionModel with valid data
    3. Predict next price
    4. Serialize model to bytes
    5. Deserialize model from bytes
  - Coverage report shows 100% for `models/` directory
- **Files**:
  - Update: `workers/daily/tests/test_models.py`
- **Tests**: This IS the test task
- **Effort**: M

#### Task 9: Add Edge Case Tests (ZOMBIES)
- **Acceptance**:
  - **Z**ero: Train with 0 samples → error
  - **O**ne: Train with 1 sample → success
  - **M**any: Train with 365 samples → success
  - **B**oundaries: Window size edge cases (1 day, 365 days)
  - **I**nterfaces: Type hints validated
  - **E**xceptions: All error paths tested
  - **S**imple: Basic happy path covered
- **Files**:
  - Update: `workers/daily/tests/test_models.py`
- **Tests**: This IS the test task
- **Effort**: S

#### Task 10: Add Documentation & Type Hints
- **Acceptance**:
  - All public methods have docstrings with:
    - Purpose
    - Parameters (type, description)
    - Returns (type, description)
    - Raises (exceptions)
    - Usage example
  - Type hints on all method signatures
  - Module-level docstring in `__init__.py`
- **Files**:
  - Update: `workers/daily/models/base.py`
  - Update: `workers/daily/models/linear.py`
  - Update: `workers/daily/models/__init__.py`
- **Tests**: N/A (documentation task)
- **Effort**: S

#### Task 11: Code Quality Checks
- **Acceptance**:
  - `ruff check` passes with no errors
  - `ruff format` applied
  - `mypy` passes (if configured)
  - Test coverage ≥ 100%
- **Files**: All `workers/daily/models/` files
- **Tests**: N/A (quality check task)
- **Effort**: XS

### Integration (Build Fourth)

#### Task 12: Update Dependencies
- **Acceptance**:
  - `scikit-learn = "^1.5.0"` added to `workers/pyproject.toml`
  - `numpy = "^2.0.0"` added (if not already present)
  - `poetry lock` executed
  - Docker image rebuilds successfully
- **Files**:
  - Update: `workers/pyproject.toml`
  - Update: `poetry.lock`
- **Tests**: Docker build succeeds
- **Effort**: XS

#### Task 13: Verify Container Integration
- **Acceptance**:
  - Tests run successfully inside Docker container: `docker compose exec api pytest workers/daily/tests/test_models.py`
  - All 5+ Gherkin scenarios pass
  - No import errors
- **Files**: N/A (integration verification)
- **Tests**: Container test execution
- **Effort**: XS

## Effort Estimate

**Total Estimated Time**: 1.5 - 2 days

| Phase | Tasks | Effort |
|-------|-------|--------|
| Foundation | T1-T2 | 2 hours |
| Core Implementation | T3-T7 | 8-10 hours |
| Testing & Polish | T8-T11 | 6-8 hours |
| Integration | T12-T13 | 1 hour |
| **Total** | **13 tasks** | **17-21 hours** |

## Implementation Order

```
1. T1: BaseModel abstract class
2. T2: Test infrastructure
3. T3: LinearRegressionModel.__init__
4. T4: train() method
5. T5: predict() method
6. T6: serialize() method
7. T7: deserialize() method
8. T8: Gherkin test coverage
9. T9: ZOMBIES edge cases
10. T10: Documentation
11. T11: Code quality
12. T12: Dependencies
13. T13: Container verification
```

## Success Verification

Before marking US-006 as complete, verify:

✅ All 13 tasks completed  
✅ All 5 Gherkin scenarios pass  
✅ Test coverage = 100%  
✅ Lint checks pass  
✅ Type hints validated  
✅ Container tests run successfully  
✅ GitHub Issue #7 updated with progress  
✅ Ready for US-007 (daily job integration)
