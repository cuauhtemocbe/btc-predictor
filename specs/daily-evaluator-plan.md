# Implementation Plan: Daily Prediction Evaluator Job

**Spec**: `specs/daily-evaluator.md`  
**Created**: 2026-05-17  
**Status**: approved

## Components

### 1. Evaluator Core Logic
- **Purpose**: Main evaluation function that fetches prediction, fetches actual price, calculates metrics, updates DB
- **Files**: `workers/daily/evaluator.py`
- **Effort**: M (core business logic)

### 2. Direction Logic Helper
- **Purpose**: Determine if predicted direction matches actual direction
- **Files**: `workers/daily/evaluator.py` (helper function)
- **Effort**: S (pure function, well-defined logic)

### 3. Test Suite
- **Purpose**: Comprehensive tests covering all Gherkin scenarios and edge cases
- **Files**: `workers/daily/tests/test_evaluator.py`
- **Effort**: M (9 test cases + fixtures)

### 4. Daily Job Orchestration
- **Purpose**: Update `__main__.py` to call evaluator before predictor
- **Files**: `workers/daily/__main__.py`
- **Effort**: XS (simple sequencing)

## Dependencies

### Build Order
1. **Evaluator core logic** (foundation)
   - Query logic
   - Metric calculation
   - DB update logic
2. **Direction logic helper** (used by core)
3. **Test suite** (verify correctness)
4. **Job orchestration** (integration)

### External Dependencies
- `shared.db.models.Prediction` — existing model from US-008
- `shared.db.models.BtcPrice` — existing model from US-002
- `shared.db.database.SessionLocal` — existing DB session
- `shared.utils.calculate_pnl` — existing utility
- `datetime`, `logging` — standard library

## Risks & Assumptions

### Risks

- **Risk 1**: Timezone mismatch between prediction timestamp and btc_prices timestamp
  - **Mitigation**: Use `datetime.date.today()` and construct 7am timestamp with correct timezone

- **Risk 2**: Multiple predictions for same date (edge case not yet handled)
  - **Mitigation**: Query should return single prediction. If multiple exist, evaluate most recent by `predicted_at`

- **Risk 3**: Division by zero in error_pct if actual_price = 0
  - **Mitigation**: BTC price will never be 0, but add defensive check for safety

### Assumptions

- `btc_prices` table has hourly data including 7am each day (validated by US-004)
- Only one prediction per day exists (enforced by predictor logic in US-009)
- `price_at_prediction` field is always populated by predictor (non-null)
- `calculate_pnl()` utility is correct (tested in shared tests)

## Milestones

- [x] **Milestone 1**: Spec and plan approved
- [ ] **Milestone 2**: Evaluator core logic implemented (can run standalone)
- [ ] **Milestone 3**: All tests passing (>=95% coverage)
- [ ] **Milestone 4**: Integrated with daily job orchestration
- [ ] **Milestone 5**: Deployed to Railway, verified in production

## Tasks

### Foundation (Build First)

- [ ] **Task 1**: Create `workers/daily/evaluator.py` skeleton
  - **Acceptance**: File exists with main() function, imports, logging setup
  - **Files**: `workers/daily/evaluator.py`
  - **Tests**: None yet (just structure)
  - **Effort**: XS

- [ ] **Task 2**: Implement query logic for unevaluated predictions
  - **Acceptance**: Function returns prediction WHERE predicted_for=today AND actual_price=NULL
  - **Files**: `workers/daily/evaluator.py` (`find_unevaluated_prediction()`)
  - **Tests**: Unit test with mocked DB session
  - **Effort**: S

- [ ] **Task 3**: Implement query logic for actual price
  - **Acceptance**: Function returns btc_prices.close WHERE timestamp=today 7am
  - **Files**: `workers/daily/evaluator.py` (`fetch_actual_price()`)
  - **Tests**: Unit test with mocked DB session
  - **Effort**: S

- [ ] **Task 4**: Implement direction correctness logic
  - **Acceptance**: Pure function that takes (predicted, price_at_pred, actual) and returns bool
  - **Files**: `workers/daily/evaluator.py` (`calculate_direction_correct()`)
  - **Tests**: 4 unit tests (UP/UP, UP/DOWN, DOWN/DOWN, DOWN/UP)
  - **Effort**: S

### Features (Build Second)

- [ ] **Task 5**: Implement metric calculation logic
  - **Acceptance**: Function calculates error_abs, error_pct, direction_correct, pnl_simulated
  - **Files**: `workers/daily/evaluator.py` (`calculate_metrics()`)
  - **Tests**: Unit test with sample values
  - **Effort**: M

- [ ] **Task 6**: Implement DB update logic
  - **Acceptance**: Function updates prediction record with all evaluation fields
  - **Files**: `workers/daily/evaluator.py` (`update_prediction()`)
  - **Tests**: Integration test with test DB
  - **Effort**: S

- [ ] **Task 7**: Implement main orchestration logic
  - **Acceptance**: main() ties together find → fetch → calculate → update
  - **Files**: `workers/daily/evaluator.py` (`main()`)
  - **Tests**: Integration test (end-to-end scenario)
  - **Effort**: M

### Edge Cases & Error Handling (Build Third)

- [ ] **Task 8**: Handle "no unevaluated predictions" case
  - **Acceptance**: Log message, exit 0
  - **Files**: `workers/daily/evaluator.py` (in main())
  - **Tests**: Gherkin scenario 2
  - **Effort**: XS

- [ ] **Task 9**: Handle "missing actual price" case
  - **Acceptance**: Log message, exit 0 (retry tomorrow)
  - **Files**: `workers/daily/evaluator.py` (in main())
  - **Tests**: Gherkin scenario 3
  - **Effort**: XS

- [ ] **Task 10**: Add defensive checks (division by zero, null checks)
  - **Acceptance**: Doesn't crash on edge cases
  - **Files**: `workers/daily/evaluator.py`
  - **Tests**: Edge case tests
  - **Effort**: S

### Testing & Integration (Build Fourth)

- [ ] **Task 11**: Write comprehensive test suite
  - **Acceptance**: All 9 test cases passing, coverage >= 95%
  - **Files**: `workers/daily/tests/test_evaluator.py`
  - **Tests**: This is the test task
  - **Effort**: M

- [ ] **Task 12**: Update daily job orchestration
  - **Acceptance**: `__main__.py` calls evaluator.main() before predictor
  - **Files**: `workers/daily/__main__.py`
  - **Tests**: Integration test or manual verification
  - **Effort**: XS

- [ ] **Task 13**: Manual integration test (predictor → evaluator)
  - **Acceptance**: Run predictor, wait 1 day, run evaluator, verify DB updated
  - **Files**: None (testing)
  - **Tests**: Manual verification
  - **Effort**: S

### Polish & Deploy (Build Fifth)

- [ ] **Task 14**: Add logging for monitoring
  - **Acceptance**: Clear logs at INFO level for normal operation, ERROR for failures
  - **Files**: `workers/daily/evaluator.py`
  - **Tests**: Log output verification
  - **Effort**: XS

- [ ] **Task 15**: Run linter and fix issues
  - **Acceptance**: `ruff check` passes
  - **Files**: All modified files
  - **Tests**: Lint check
  - **Effort**: XS

- [ ] **Task 16**: Deploy to Railway
  - **Acceptance**: Daily cron runs evaluator successfully in production
  - **Files**: None (deployment)
  - **Tests**: Railway logs verification
  - **Effort**: S

- [ ] **Task 17**: Close GitHub Issue #11
  - **Acceptance**: Issue closed with demo/verification comment
  - **Files**: None (GitHub)
  - **Tests**: None
  - **Effort**: XS

## Effort Estimate

**Total Estimated Time**: 1.5-2 days

| Phase | Effort | Hours |
|-------|--------|-------|
| Foundation (Tasks 1-4) | 2S + 2XS | 4h |
| Features (Tasks 5-7) | 2M + 1S | 6h |
| Edge Cases (Tasks 8-10) | 1S + 2XS | 2h |
| Testing (Task 11) | M | 3h |
| Integration (Tasks 12-13) | XS + S | 2h |
| Polish & Deploy (Tasks 14-17) | 3XS + S | 2h |
| **Total** | | **19h** |

**Note**: Estimate assumes familiarity with codebase from US-008 and US-009. Includes test writing time (critical for this US).

## Implementation Order

```
1. evaluator.py skeleton (structure)
   ↓
2. Query functions (find_unevaluated_prediction, fetch_actual_price)
   ↓
3. Direction logic helper (pure function, easy to test)
   ↓
4. Metric calculation (integrates direction logic + PnL utility)
   ↓
5. DB update logic (writes to predictions table)
   ↓
6. Main orchestration (ties everything together)
   ↓
7. Edge case handling (no predictions, missing price)
   ↓
8. Comprehensive tests (TDD approach - write tests as you go)
   ↓
9. Job orchestration update (__main__.py)
   ↓
10. Lint, deploy, close issue
```

## Testing Strategy

**Approach**: Test-Driven Development (TDD)

1. Write test for each function BEFORE implementing
2. Run test (should fail)
3. Implement function
4. Run test (should pass)
5. Refactor if needed

**Key Tests**:
- Direction logic: 4 cases (all combinations of UP/DOWN)
- Error calculation: precision validation
- PnL integration: verify correct usage of calculate_pnl()
- DB operations: integration tests with test DB
- Edge cases: no predictions, missing price
- Idempotency: run twice, same result

## Success Metrics

- [ ] All 3 Gherkin scenarios automated
- [ ] Code coverage >= 95%
- [ ] Lint check green
- [ ] Manual integration test verified
- [ ] Deployed to Railway
- [ ] GitHub Issue #11 closed
