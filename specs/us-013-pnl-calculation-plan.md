# Implementation Plan: US-013 PnL Calculation Logic

**Spec**: `specs/us-013-pnl-calculation.md`  
**Created**: 2026-05-17  
**Status**: completed

## Components

### 1. PnL Calculation Function
- **Purpose**: Pure function implementing long-only trading strategy PnL calculation
- **Files**: `shared/btc_shared/utils.py` (modify existing)
- **Effort**: S (2 hours)

### 2. Unit Tests
- **Purpose**: Test all Gherkin scenarios and edge cases
- **Files**: `shared/tests/test_utils.py` (modify existing)
- **Effort**: S (2 hours)

### 3. Evaluator Integration
- **Purpose**: Call `calculate_pnl()` in evaluator worker and save to DB
- **Files**: `workers/daily/evaluator.py` (modify existing)
- **Effort**: XS (1 hour)

### 4. Integration Tests
- **Purpose**: Test evaluator end-to-end with PnL calculation
- **Files**: `workers/daily/tests/test_evaluator.py` (modify existing)
- **Effort**: S (1.5 hours)

## Dependencies

### Build Order
1. `calculate_pnl()` function (foundation)
2. Unit tests for `calculate_pnl()` (verify logic)
3. Evaluator integration (use the function)
4. Integration tests (verify end-to-end)

### External Dependencies
None. Uses Python standard library only.

## Risks & Assumptions

### Risks
- **Risk 1**: Floating-point precision issues with currency calculations
  - **Mitigation**: Use `Decimal` type or round to 2 decimal places
  
- **Risk 2**: Evaluator might fail if PnL calculation raises exception
  - **Mitigation**: Add try/except in evaluator, log errors, set PnL to NULL on failure

### Assumptions
- `predictions.pnl_simulated` column already exists (from US-008) ✅
- Evaluator worker already updates prediction records ✅
- Database session management is already implemented ✅

## Milestones

- [ ] Milestone 1: `calculate_pnl()` function with 100% unit test coverage
- [ ] Milestone 2: Evaluator successfully calculates and stores PnL
- [ ] Milestone 3: All Gherkin scenarios have passing tests

## Tasks

### Foundation (Build First)
- [ ] **Task 1**: Implement `calculate_pnl()` function
  - **Acceptance**: Function accepts 3 float params, returns float
  - **Files**: `shared/btc_shared/utils.py`
  - **Tests**: Not yet (next task)
  - **Effort**: XS
  - **Details**:
    - Add function signature with type hints
    - Implement logic: if predicted > before → return actual - before, else → return 0
    - Add comprehensive docstring with strategy explanation and examples

- [ ] **Task 2**: Write unit tests for `calculate_pnl()`
  - **Acceptance**: All 4 Gherkin example scenarios pass + edge cases
  - **Files**: `shared/tests/test_utils.py`
  - **Tests**: This IS the tests
  - **Effort**: S
  - **Details**:
    - Test scenario: predicted up, actual up (profit)
    - Test scenario: predicted up, actual down (loss)
    - Test scenario: predicted down, actual down (no trade, 0 PnL)
    - Test scenario: predicted down, actual up (no trade, 0 PnL)
    - Test edge case: all prices equal
    - Test edge case: zero prices
    - Test edge case: large price differences

### Integration (Build Second)
- [ ] **Task 3**: Integrate `calculate_pnl()` in evaluator
  - **Acceptance**: Evaluator calculates PnL and saves to database
  - **Files**: `workers/daily/evaluator.py`
  - **Tests**: Integration test (next task)
  - **Effort**: XS
  - **Details**:
    - Import `calculate_pnl` from `btc_shared.utils`
    - After fetching `actual_price`, call `calculate_pnl(predicted_price, price_at_prediction, actual_price)`
    - Save result to `prediction.pnl_simulated`
    - Add error handling: if calculation fails, log error and set PnL to NULL

- [ ] **Task 4**: Update evaluator integration tests
  - **Acceptance**: Test verifies PnL is correctly calculated and stored
  - **Files**: `workers/daily/tests/test_evaluator.py`
  - **Tests**: This IS the tests
  - **Effort**: S
  - **Details**:
    - Test Gherkin scenario: "PnL is stored in predictions table"
    - Create prediction with predicted_for=today
    - Run evaluator
    - Assert `pnl_simulated` is updated with correct value
    - Test both profit and loss scenarios

## Effort Estimate

**Total Estimated Time**: 1 day (6.5 hours)

| Phase | Effort |
|-------|--------|
| Foundation (calculate_pnl + unit tests) | 4 hours |
| Integration (evaluator + tests) | 2.5 hours |
| Total | 6.5 hours |
