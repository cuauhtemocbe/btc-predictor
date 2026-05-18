# Implementation Plan: US-014 PnL API Endpoint

**Spec**: `specs/us-014-pnl-api-endpoint.md`  
**Created**: 2026-05-17  
**Status**: completed

## Components

### 1. Pydantic Response Model
- **Purpose**: Type-safe response schema for PnL endpoint
- **Files**: `api-service/api/schemas.py` (create if doesn't exist) or inline in router
- **Effort**: XS (15 minutes)

### 2. PnL API Route
- **Purpose**: GET endpoint that aggregates PnL from database
- **Files**: `api-service/api/routers/predictions.py` (modify existing)
- **Effort**: S (1 hour)

### 3. API Tests
- **Purpose**: Test endpoint with various scenarios
- **Files**: `api-service/tests/test_predictions.py` (modify existing or create)
- **Effort**: S (2 hours)

## Dependencies

### Build Order
1. Response model (if separate file)
2. API route implementation
3. API tests

### External Dependencies
- FastAPI (already installed) ✅
- SQLAlchemy (already installed) ✅
- pytest-asyncio (already installed) ✅
- httpx (already installed for API tests) ✅

## Risks & Assumptions

### Risks
- **Risk 1**: Query performance degradation with large dataset
  - **Mitigation**: Add index on `pnl_simulated` if needed (check with EXPLAIN)
  - **Note**: Current dataset small (< 100 predictions), no immediate concern

### Assumptions
- `predictions` router already exists (from US-011/US-012) ✅
- Database session dependency already configured ✅
- Test fixtures for database and HTTP client already exist ✅

## Milestones

- [ ] Milestone 1: Route returns correct aggregation for sample data
- [ ] Milestone 2: All Gherkin scenarios have passing tests
- [ ] Milestone 3: OpenAPI docs generated correctly

## Tasks

### Foundation (Build First)
- [ ] **Task 1**: Create Pydantic response model
  - **Acceptance**: Model validates response structure
  - **Files**: `api-service/api/routers/predictions.py` (inline)
  - **Tests**: Schema validation in API tests
  - **Effort**: XS
  - **Details**:
    - Create `PnlResponse` class inheriting from `BaseModel`
    - Fields: `total_pnl: float`, `evaluated_predictions: int`
    - Add field descriptions for OpenAPI docs

- [ ] **Task 2**: Implement GET /api/predictions/pnl route
  - **Acceptance**: Route returns correct JSON response
  - **Files**: `api-service/api/routers/predictions.py`
  - **Tests**: API tests (next task)
  - **Effort**: S
  - **Details**:
    - Add async route handler `get_total_pnl(db: Session = Depends(get_db))`
    - Query: `db.query(func.sum(Prediction.pnl_simulated), func.count(Prediction.id)).filter(Prediction.pnl_simulated.isnot(None)).first()`
    - Handle NULL result (no evaluated predictions): return (0.0, 0)
    - Return `PnlResponse` model
    - Add docstring for OpenAPI description

### Testing (Build Second)
- [ ] **Task 3**: Write API tests
  - **Acceptance**: All 2 Gherkin scenarios pass
  - **Files**: `api-service/tests/test_predictions.py` (create if needed)
  - **Tests**: This IS the tests
  - **Effort**: S
  - **Details**:
    - Test scenario: "Calculate total PnL" with 30 evaluated predictions
    - Test scenario: "No evaluated predictions yet" with all NULL values
    - Test response status code (200)
    - Test response schema (matches Pydantic model)
    - Test edge case: mix of evaluated and unevaluated predictions
    - Use async test client and database fixtures

## Effort Estimate

**Total Estimated Time**: 0.5 day (3.25 hours)

| Phase | Effort |
|-------|--------|
| Foundation (model + route) | 1.25 hours |
| Testing (API tests) | 2 hours |
| Total | 3.25 hours |
