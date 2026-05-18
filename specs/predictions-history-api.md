---
title: Predictions History API Endpoint
status: approved
created: 2026-05-17
updated: 2026-05-17
issue: #12
---

# Predictions History API Endpoint

## Objective

Provide a REST API endpoint that returns historical predictions with evaluation metrics (errors, direction correctness) to enable dashboard visualization of model accuracy over time.

## Context

After implementing the daily predictor (US-009) and evaluator (US-010) jobs, we now have predictions being created daily and evaluated the next day. The predictions table contains both unevaluated (actual_price = NULL) and evaluated records. 

Frontend developers need an API to fetch only evaluated predictions with all relevant metrics to build accuracy dashboards, charts, and performance reports.

## Requirements

### Functional Requirements

- [ ] Create GET /api/predictions/history endpoint
- [ ] Return only evaluated predictions (actual_price IS NOT NULL)
- [ ] Include model information via JOIN with models table
- [ ] Support optional date range filtering via query parameters
- [ ] Order results by predicted_for DESC (most recent first)
- [ ] Return empty array when no evaluated predictions exist

### Non-Functional Requirements

- [ ] Performance: Query execution < 100ms for 1000 records
- [ ] Response format: JSON array with consistent schema
- [ ] HTTP status codes: 200 OK (success), 422 Unprocessable Entity (invalid dates)
- [ ] Pagination: Not required for MVP (will add if needed)

## Architecture

### Components

**API Router**: `api-service/api/routers/predictions.py`
- New router for predictions-related endpoints
- Mounted at `/api/predictions` prefix

**Database Query**:
```python
SELECT 
  p.predicted_for,
  p.predicted_at,
  p.price_at_prediction,
  p.predicted_price,
  p.actual_price,
  p.evaluated_at,
  p.error_abs,
  p.error_pct,
  p.direction_correct,
  p.pnl_simulated,
  m.name as model_name,
  m.version as model_version
FROM predictions p
JOIN models m ON p.model_id = m.id
WHERE p.actual_price IS NOT NULL
  AND p.predicted_for >= :from_date (optional)
  AND p.predicted_for <= :to_date (optional)
ORDER BY p.predicted_for DESC
```

### Data Model

**Request Query Parameters**:
```python
from_date: Optional[date] = None
to_date: Optional[date] = None
```

**Response Schema**:
```python
[
  {
    "predicted_for": "2026-05-17",
    "predicted_at": "2026-05-16T19:00:00Z",
    "price_at_prediction": 67000.0,
    "predicted_price": 67500.0,
    "actual_price": 67800.0,
    "evaluated_at": "2026-05-17T07:01:00Z",
    "error_abs": 300.0,
    "error_pct": 0.44,
    "direction_correct": true,
    "pnl_simulated": 800.0,
    "model_name": "linear_v1",
    "model_version": "1.0.0"
  }
]
```

### External Dependencies

- FastAPI (already in project)
- SQLAlchemy 2.0 (already in project)
- Pydantic v2 (response schema validation)

## User Stories

Reference: GitHub Issue #12 (US-011)

### Gherkin Scenarios

```gherkin
Feature: API endpoint for prediction history

  Scenario: Fetch all evaluated predictions
    Given the predictions table has 30 evaluated records (actual_price != NULL)
    And 5 unevaluated records (actual_price = NULL)
    When I send GET /api/predictions/history
    Then the response status is 200 OK
    And the response body is a JSON array with 30 items (only evaluated)
    And each item has keys: predicted_for, predicted_price, actual_price, error_abs, error_pct, direction_correct, model_name
    And items are ordered by predicted_for DESC

  Scenario: No evaluated predictions yet
    Given all predictions have actual_price = NULL
    When I send GET /api/predictions/history
    Then the response status is 200 OK
    And the response body is an empty JSON array []

  Scenario: Filter by date range
    Given I send GET /api/predictions/history?from=2026-05-01&to=2026-05-15
    Then the response contains only predictions where predicted_for is between those dates
```

## Testing Strategy

### Unit Tests
- Pydantic schema validation (response model)
- Date parsing and validation

### Integration Tests
- Query all evaluated predictions (30 records)
- Query returns empty array when no evaluated predictions
- Filter by from_date only
- Filter by to_date only
- Filter by both from_date and to_date
- Verify JOIN with models table (model_name, model_version)
- Verify ORDER BY predicted_for DESC
- Invalid date format returns 422

**Test Location**: `api-service/tests/test_predictions.py`

**Test Framework**: pytest + httpx.AsyncClient + respx (for mocking)

### Coverage Target
- 95%+ coverage on router logic
- All Gherkin scenarios covered

## Boundaries & Constraints

### In Scope
- GET /api/predictions/history endpoint
- Date range filtering
- Only evaluated predictions (actual_price != NULL)

### Out of Scope
- Pagination (will add if performance requires it)
- POST/PUT/DELETE operations on predictions
- Individual prediction detail endpoint (GET /api/predictions/{id})
- Aggregated statistics endpoint (avg error, win rate, etc.)
- WebSocket real-time updates

### Technical Constraints
- Must run inside Docker container
- Database: PostgreSQL via shared package
- No external API calls (data from local DB only)

## Success Criteria

- [ ] All 3 Gherkin scenarios have passing automated tests
- [ ] Endpoint returns only evaluated predictions
- [ ] Response includes model name and version via JOIN
- [ ] Date range filtering works correctly
- [ ] Empty array returned when no data (not 404)
- [ ] Query performance < 100ms for 1000 records
- [ ] Lint checks pass (ruff)
- [ ] Type hints verified (mypy if used)

## Implementation Plan

See: `specs/predictions-history-api-plan.md`
