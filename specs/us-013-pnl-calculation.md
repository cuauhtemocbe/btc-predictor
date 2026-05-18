---
title: US-013 PnL Calculation Logic
status: completed
created: 2026-05-17
updated: 2026-05-17
issue: #14
---

# US-013: PnL Calculation Logic

## Objective

Implement a simulated profit/loss (PnL) calculation function that evaluates whether the prediction model would be profitable if used for trading Bitcoin. The function uses a simple long-only strategy: buy 1 BTC if the model predicts price will go up, otherwise stay in cash.

## Context

We have a prediction system that forecasts tomorrow's Bitcoin price. To measure business value, we need to know if following these predictions would be profitable. This requires calculating simulated PnL for each prediction based on a defined trading strategy.

**Trading Strategy**:
- If `predicted_price > price_at_prediction`: Go long (buy 1 BTC at `price_at_prediction`)
  - PnL = `actual_price - price_at_prediction` (can be positive or negative)
- Else: Stay in cash (no trade)
  - PnL = 0

This strategy tests if the model has directional predictive power.

## Requirements

### Functional Requirements

- [ ] Create `calculate_pnl()` function in `shared/btc_shared/utils.py`
- [ ] Function accepts three parameters: `predicted_price`, `price_at_prediction`, `actual_price`
- [ ] Function returns a float representing simulated PnL in USD
- [ ] Logic implements the long-only strategy described above
- [ ] Evaluator worker calls this function and saves result to `predictions.pnl_simulated` column
- [ ] Handle edge cases: NULL values, negative prices, price equality

### Non-Functional Requirements

- [ ] Performance: Function executes in < 1ms (pure calculation, no I/O)
- [ ] Reliability: 100% test coverage for all edge cases
- [ ] Maintainability: Well-documented strategy logic in docstring
- [ ] Type safety: Use type hints for all parameters and return value

## Architecture

### Components

1. **`calculate_pnl()` utility function** (new)
   - Location: `shared/btc_shared/utils.py`
   - Pure function (no side effects, no DB access)
   - Type signature: `calculate_pnl(predicted_price: float, price_at_prediction: float, actual_price: float) -> float`

2. **Evaluator worker update** (modify existing)
   - Location: `workers/daily/evaluator.py`
   - Call `calculate_pnl()` after fetching actual price
   - Update prediction record with PnL value

### Data Model

No schema changes needed. The `predictions.pnl_simulated` column already exists (added in US-008).

```python
# predictions table (existing)
pnl_simulated = Column(Numeric(10, 2), nullable=True)
```

### External Dependencies

None. Pure Python logic using standard library only.

## User Stories

Reference: GitHub Issue #14

**As** a data scientist  
**I want** to calculate simulated PnL for each prediction  
**In order to** measure if the model would be profitable

## Testing Strategy

### Unit Tests

- Test all scenarios from Gherkin examples table
- Test edge cases: equal prices, zero values, large differences
- Test type validation and error handling

Coverage target: 100% (pure function, easily testable)

### Integration Tests

- Test evaluator worker end-to-end with PnL calculation
- Verify PnL is correctly stored in database
- Test with real historical prediction data

## Boundaries & Constraints

### In Scope

- Simple long-only strategy (buy if predicted up, else cash)
- Calculation for 1 BTC fixed position size
- Storage of PnL in existing `pnl_simulated` column

### Out of Scope

- Short positions or more complex strategies
- Transaction costs, slippage, fees
- Variable position sizing or risk management
- Cumulative PnL calculation (covered in US-014)
- Leverage or margin trading

### Technical Constraints

- Must use existing `predictions` table schema
- Must be called from evaluator worker (daily cron)
- Must handle NULL values gracefully (predictions not yet evaluated)

## Success Criteria

- [ ] All Gherkin scenarios have passing automated tests
- [ ] `calculate_pnl()` function handles all edge cases correctly
- [ ] Evaluator worker successfully calculates and stores PnL for daily predictions
- [ ] Code coverage ≥ 95% for new code
- [ ] Lint checks pass (ruff)
- [ ] Manual verification: Run evaluator and confirm PnL values are logical

## Implementation Plan

See: `specs/us-013-pnl-calculation-plan.md`
