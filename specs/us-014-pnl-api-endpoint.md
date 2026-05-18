---
title: US-014 PnL API Endpoint
status: completed
created: 2026-05-17
updated: 2026-05-17
issue: #15
---

# US-014: PnL API Endpoint

## Objective

Implement a REST API endpoint that returns the accumulated profit/loss (PnL) across all evaluated predictions, allowing business users to quickly assess overall model profitability.

## Context

After implementing PnL calculation for individual predictions (US-013), we need a way to view the cumulative performance. This endpoint provides a summary metric that answers: "If I had followed this model's predictions, what would be my total profit/loss?"

This metric is critical for:
- Business stakeholders evaluating model ROI
- Data scientists comparing model versions
- Dashboard visualization of profitability

## Requirements

### Functional Requirements

- [ ] Create `GET /api/predictions/pnl` endpoint
- [ ] Query database for total sum of `pnl_simulated` where NOT NULL
- [ ] Return JSON response with `total_pnl` and `evaluated_predictions` count
- [ ] Handle case where no predictions have been evaluated yet (return 0, 0)
- [ ] Return 200 OK status for successful requests

### Non-Functional Requirements

- [ ] Performance: Response time < 100ms (simple aggregation query)
- [ ] Reliability: Handle empty database gracefully
- [ ] API Design: Follow existing response schema conventions (snake_case, flat structure)
- [ ] Documentation: OpenAPI/Swagger auto-documentation via FastAPI

## Architecture

### Components

1. **PnL router** (new route in existing file)
   - Location: `api-service/api/routers/predictions.py`
   - Method: GET
   - Path: `/api/predictions/pnl`
   - Handler: `async def get_total_pnl()`

2. **Database query**
   - Use SQLAlchemy to aggregate: `SELECT SUM(pnl_simulated), COUNT(*) FROM predictions WHERE pnl_simulated IS NOT NULL`
   - Return tuple: (total_pnl, count)

3. **Response model** (new)
   - Pydantic model for type-safe response
   - Fields: `total_pnl: float`, `evaluated_predictions: int`

### Data Model

No schema changes needed. Query existing `predictions` table.

### API Response Schema

```json
{
  "total_pnl": 12345.67,
  "evaluated_predictions": 30
}
```

### External Dependencies

- FastAPI (existing)
- SQLAlchemy (existing)
- Pydantic (existing)

## User Stories

Reference: GitHub Issue #15

**As** a business user  
**I want** an API endpoint that returns total accumulated PnL  
**In order to** see if the model is profitable overall

## Testing Strategy

### API Tests

- Test response with multiple evaluated predictions (positive PnL)
- Test response with no evaluated predictions (NULL values)
- Test response schema validation
- Test performance with large dataset (mock 1000+ predictions)

Coverage target: 100% for new route

### Integration Tests

- Test end-to-end: create predictions → evaluate → query PnL endpoint
- Test with mixed data: some predictions evaluated, some pending

## Boundaries & Constraints

### In Scope

- Simple aggregation query (SUM, COUNT)
- Return total PnL across all predictions
- JSON response format

### Out of Scope

- Filtering by date range or model version
- Historical PnL tracking over time
- Detailed breakdown by prediction
- PnL chart data (separate endpoint if needed)
- Authentication/authorization

### Technical Constraints

- Must use existing database session management
- Must follow FastAPI async/await pattern
- Must return proper HTTP status codes

## Success Criteria

- [ ] All Gherkin scenarios have passing automated tests
- [ ] Endpoint returns correct PnL aggregation
- [ ] Endpoint handles edge cases (empty DB, all NULL values)
- [ ] Response time < 100ms
- [ ] OpenAPI documentation auto-generated
- [ ] Code coverage ≥ 95% for new route
- [ ] Lint checks pass (ruff)

## Implementation Plan

See: `specs/us-014-pnl-api-endpoint-plan.md`
