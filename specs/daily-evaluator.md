---
title: Daily Prediction Evaluator Job
status: completed
created: 2026-05-17
updated: 2026-05-17
issue: #11
iteration: 5
---

# Daily Prediction Evaluator Job

## Objective

Create a daily cron job that evaluates yesterday's BTC price prediction by comparing it against the actual price from today's 7am close, calculating accuracy metrics (absolute error, percentage error, directional correctness), and updating the predictions table with evaluation results.

## Context

The predictor job (US-009) creates predictions for tomorrow's BTC price and stores them with `actual_price=NULL`. The evaluator job runs the next day to:
1. Fetch the actual BTC price from today's 7am close
2. Calculate error metrics and directional accuracy
3. Update the prediction record with evaluation results

This enables the data science team to track model accuracy over time and measure prediction quality.

**Business Value**: Without evaluation, we can't measure if our models are improving or which models perform best. This is the foundation for model comparison and selection.

## Requirements

### Functional Requirements

- [ ] Find all predictions where `predicted_for = today` AND `actual_price IS NULL`
- [ ] Fetch today's 7am close price from `btc_prices` table
- [ ] Calculate `error_abs = |actual_price - predicted_price|`
- [ ] Calculate `error_pct = (error_abs / actual_price) * 100`
- [ ] Determine `direction_correct`:
  - If `predicted_price > price_at_prediction` (predicted UP):
    - `direction_correct = (actual_price >= price_at_prediction)`
  - If `predicted_price <= price_at_prediction` (predicted DOWN or flat):
    - `direction_correct = (actual_price < price_at_prediction)`
- [ ] Calculate `pnl_simulated` using existing `calculate_pnl()` utility
- [ ] Update prediction record with all evaluation fields
- [ ] Set `evaluated_at = current timestamp`
- [ ] Handle case where no predictions need evaluation (log and exit 0)
- [ ] Handle case where actual price not available yet (log and exit 0, retry tomorrow)
- [ ] Log evaluation results (prediction ID, errors, direction)

### Non-Functional Requirements

- [ ] **Idempotency**: Safe to run multiple times (only updates records with `actual_price=NULL`)
- [ ] **Performance**: Complete in < 5 seconds (single DB query + single update)
- [ ] **Error Handling**: Graceful handling of missing data (don't crash)
- [ ] **Logging**: Clear logs for debugging and monitoring
- [ ] **Exit Codes**: 0 for success (including no-op cases), non-zero only for errors

## Architecture

### Components

```
workers/daily/
├── evaluator.py       # Main evaluation logic (NEW)
├── predictor.py       # Existing predictor from US-009
└── __main__.py        # Entry point (will be updated to call evaluator first)
```

### Data Flow

```
1. evaluator.py runs
   ↓
2. Query predictions table (predicted_for=today, actual_price=NULL)
   ↓
3. Query btc_prices table (timestamp=today 7am)
   ↓
4. Calculate metrics (error_abs, error_pct, direction_correct, pnl_simulated)
   ↓
5. Update prediction record
   ↓
6. Log results
```

### Database Schema

Uses existing `predictions` table from US-008:
- **Read**: `id, predicted_for, predicted_price, price_at_prediction`
- **Write**: `actual_price, error_abs, error_pct, direction_correct, pnl_simulated, evaluated_at`

Uses existing `btc_prices` table from US-002:
- **Read**: `close` WHERE `timestamp = today 7am`

### External Dependencies

- `shared.db.models`: Prediction, BtcPrice SQLAlchemy models
- `shared.db.database`: Database session
- `shared.utils`: `calculate_pnl()` function
- `datetime`: Date manipulation
- `logging`: Structured logging

## User Stories

**User Story**: US-010 (GitHub Issue #11)

**As** a data scientist  
**I want** a job that evaluates yesterday's prediction  
**In order to** measure model accuracy

## Testing Strategy

### Unit Tests

**File**: `workers/daily/tests/test_evaluator.py`

**Test Cases** (mapped to Gherkin scenarios):

1. **Evaluate yesterday's prediction** (happy path)
   - Given: prediction with predicted_for=today, actual_price=NULL
   - And: btc_prices has today 7am close price
   - When: run evaluator
   - Then: prediction updated with actual_price, errors, direction, pnl

2. **No unevaluated predictions** (no-op case)
   - Given: all predictions have actual_price != NULL
   - When: run evaluator
   - Then: log "No predictions to evaluate", exit 0

3. **Missing actual price** (retry case)
   - Given: prediction exists but btc_prices missing today 7am
   - When: run evaluator
   - Then: log "Actual price not available", exit 0

4. **Direction logic - predicted UP, actual UP** (correct)
   - Given: predicted_price=67000, price_at_prediction=66000, actual=67500
   - Then: direction_correct=True

5. **Direction logic - predicted UP, actual DOWN** (incorrect)
   - Given: predicted_price=67000, price_at_prediction=66000, actual=65000
   - Then: direction_correct=False

6. **Direction logic - predicted DOWN, actual DOWN** (correct)
   - Given: predicted_price=65000, price_at_prediction=66000, actual=64000
   - Then: direction_correct=True

7. **Direction logic - predicted DOWN, actual UP** (incorrect)
   - Given: predicted_price=65000, price_at_prediction=66000, actual=67000
   - Then: direction_correct=False

8. **Error calculation accuracy**
   - Given: predicted=67000, actual=67500
   - Then: error_abs=500, error_pct≈0.74

9. **PnL simulation integration**
   - Given: predicted UP, actual UP
   - Then: pnl > 0
   - Given: predicted UP, actual DOWN
   - Then: pnl < 0

### Integration Tests

- Test with real PostgreSQL database (in Docker)
- Verify evaluation updates correct prediction record
- Verify idempotency (running twice doesn't change results)

### Coverage Target

**Minimum: 95% coverage** (critical business logic)

## Boundaries & Constraints

### In Scope

- Evaluate predictions for `predicted_for = today`
- Update single prediction per run (one prediction per day)
- Calculate standard error metrics (abs, pct, direction)
- Integrate with existing PnL calculation utility

### Out of Scope

- Batch evaluation of historical predictions (future enhancement)
- Model retraining based on evaluation results (separate job)
- Alerting on poor model performance (future enhancement)
- Evaluation of multiple models (only evaluates active model's predictions)
- Evaluation API endpoint (read-only queries handled by US-005 endpoint)

### Technical Constraints

- Must run inside Docker container (Railway deployment)
- Must use existing `shared` package (no code duplication)
- Must maintain idempotency (predictions table constraint)
- Must complete in < 5 seconds (single prediction evaluation)
- Must handle timezone correctly (America/Mexico_City)

## Success Criteria

- [x] All 3 Gherkin scenarios have passing automated tests
- [x] Evaluator can be run manually: `docker compose exec api python -m workers.daily.evaluator`
- [x] Code coverage >= 95% for evaluator.py (achieved 96%)
- [x] Lint check passes (ruff)
- [x] Integration with predictor via __main__.py orchestrator
- [ ] Deployed to Railway as part of daily cron service (requires Railway setup)
- [ ] GitHub Issue #11 closed with demo/verification

## Implementation Plan

See: `specs/daily-evaluator-plan.md`
