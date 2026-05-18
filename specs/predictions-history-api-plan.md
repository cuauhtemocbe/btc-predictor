# Implementation Plan: Predictions History API Endpoint

**Spec**: [predictions-history-api.md](./predictions-history-api.md)  
**Created**: 2026-05-17  
**Status**: approved

## Components

### 1. Pydantic Response Schema
- **Purpose**: Define response model for OpenAPI docs and validation
- **Files**: `api-service/api/schemas/predictions.py` (new)
- **Effort**: XS

### 2. Database Query Function
- **Purpose**: Query evaluated predictions with model JOIN
- **Files**: `shared/shared/db/crud.py` (add function)
- **Effort**: S

### 3. FastAPI Router
- **Purpose**: Handle GET /api/predictions/history endpoint
- **Files**: `api-service/api/routers/predictions.py` (new)
- **Effort**: S

### 4. Mount Router in Main App
- **Purpose**: Register predictions router in FastAPI app
- **Files**: `api-service/api/main.py` (update)
- **Effort**: XS

### 5. Integration Tests
- **Purpose**: Test all Gherkin scenarios
- **Files**: `api-service/tests/test_predictions.py` (new)
- **Effort**: M

## Dependencies

### Build Order
1. **Pydantic schema** (foundation - defines data contract)
2. **CRUD function** (data layer - queries DB)
3. **FastAPI router** (API layer - depends on schema + CRUD)
4. **Mount router** (integration - depends on router)
5. **Tests** (verification - depends on all above)

### External Dependencies
- None (all dependencies already in project)

## Risks & Assumptions

### Risks
- **Query performance on large datasets**: Mitigate with index on predictions.predicted_for and predictions.actual_price
- **Date parsing edge cases**: Mitigate with Pydantic date validation

### Assumptions
- Predictions table already has evaluated records (from US-010)
- Models table has is_active = true records
- Database connection is healthy

## Milestones

- [ ] **Milestone 1**: Schema and CRUD function complete, unit tests passing
- [ ] **Milestone 2**: Router integrated, manual curl test returns JSON
- [ ] **Milestone 3**: All Gherkin scenarios have passing tests

## Tasks

### Foundation (Build First)

- [ ] **Task 1: Create Pydantic response schema**
  - **Acceptance**: PredictionHistoryResponse model defined with all fields from spec
  - **Files**: `api-service/api/schemas/__init__.py`, `api-service/api/schemas/predictions.py`
  - **Tests**: Pydantic validation tests (optional for XS task)
  - **Effort**: XS (15 min)

- [ ] **Task 2: Add CRUD function for evaluated predictions**
  - **Acceptance**: `get_evaluated_predictions(from_date, to_date)` returns list of predictions with model info
  - **Files**: `shared/shared/db/crud.py`
  - **Tests**: Unit test with test DB, verify JOIN, verify filtering
  - **Effort**: S (1 hour)

### Features (Build Second)

- [ ] **Task 3: Create predictions router**
  - **Acceptance**: GET /api/predictions/history endpoint returns 200 with JSON array
  - **Files**: `api-service/api/routers/predictions.py`
  - **Tests**: Integration test with httpx.AsyncClient
  - **Effort**: S (1 hour)

### Integration (Build Third)

- [ ] **Task 4: Mount router in main app**
  - **Acceptance**: App includes predictions router at /api/predictions prefix
  - **Files**: `api-service/api/main.py`
  - **Tests**: Test via full app client (in test_predictions.py)
  - **Effort**: XS (10 min)

- [ ] **Task 5: Write comprehensive integration tests**
  - **Acceptance**: All 3 Gherkin scenarios pass
  - **Files**: `api-service/tests/test_predictions.py`
  - **Tests**: 
    - Test 1: 30 evaluated + 5 unevaluated → returns 30
    - Test 2: All unevaluated → returns empty array
    - Test 3: Date range filtering
  - **Effort**: M (2 hours)

## Effort Estimate

**Total Estimated Time**: 4-5 hours (half day)

| Phase | Effort |
|-------|--------|
| Schema | 15 min |
| CRUD function | 1 hour |
| Router | 1 hour |
| Integration | 10 min |
| Tests | 2 hours |

## Verification Steps

After implementation:
1. Run tests: `docker compose exec api pytest api-service/tests/test_predictions.py -v`
2. Manual test: `curl http://localhost:8000/api/predictions/history`
3. Check OpenAPI docs: `http://localhost:8000/docs`
4. Verify date filtering: `curl http://localhost:8000/api/predictions/history?from=2026-05-01&to=2026-05-15`
5. Run lint: `docker compose exec api ruff check api-service/`
