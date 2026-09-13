# Implementation Plan: US-026 Model Comparison Dashboard

**Spec**: [specs/us-026-model-comparison-dashboard.md](./us-026-model-comparison-dashboard.md)  
**Created**: 2026-05-19  
**Status**: approved  
**Estimated Effort**: M (2-3 days)

---

## Components

### 1. Metrics Calculation Module
**Purpose**: Core business logic for calculating model performance metrics  
**Location**: `shared/btc_shared/utils/metrics.py`  
**Effort**: M (1 day)

**Functions to implement**:
- `calculate_accuracy(model_id, start_date, end_date) -> float`
- `calculate_mape(model_id, start_date, end_date) -> float`
- `calculate_total_pnl(model_id, start_date, end_date) -> float`
- `calculate_win_rate(model_id, start_date, end_date) -> float`
- `calculate_sharpe_ratio(model_id, start_date, end_date) -> float`
- `calculate_max_drawdown(model_id, start_date, end_date) -> float`
- `get_cumulative_pnl(model_id, start_date, end_date) -> List[Dict]`
- `get_all_models_metrics(start_date, end_date) -> List[Dict]`

**Why**: Centralize metrics logic in shared package so it can be reused by API, CLI, future analytics

### 2. API Router
**Purpose**: HTTP endpoints for model comparison  
**Location**: `api-service/api/routers/models.py`  
**Effort**: S (0.5 day)

**Routes**:
- `GET /models` → Render HTML template with metrics
- `GET /api/models/metrics` → JSON API for metrics (AJAX or mobile apps)

**Why**: Separate router for model-related endpoints, follows REST conventions

### 3. HTML Template + Frontend
**Purpose**: User interface for model comparison  
**Location**: `api-service/api/templates/models.html`  
**Effort**: M (1 day)

**Components**:
- Comparison table with 8 metrics columns
- Chart.js cumulative PnL line chart
- Date range filter form
- Navigation breadcrumb
- Responsive CSS

**Why**: Jinja2 template for server-side rendering, Chart.js for visualization (already used in US-021)

### 4. Tests
**Purpose**: Ensure metrics accuracy and API correctness  
**Location**: 
- `shared/tests/test_metrics.py` (unit tests)
- `api-service/tests/test_models_api.py` (integration tests)  
**Effort**: S (0.5 day)

**Test Coverage**:
- Unit tests for each metric function
- Integration tests for API routes
- Edge cases: empty states, single model, filtering

**Why**: Non-negotiable per project standards, every Gherkin scenario must have a test

---

## Dependencies

### Build Order

1. **Foundation** (build first):
   - `shared/btc_shared/utils/metrics.py` — metrics calculation functions
   - Unit tests for metrics

2. **Backend** (depends on foundation):
   - `api-service/api/routers/models.py` — API routes
   - Integration tests for API

3. **Frontend** (depends on backend):
   - `api-service/api/templates/models.html` — HTML template
   - Chart.js integration
   - CSS styling

4. **Integration** (depends on all):
   - Wire up router in `api-service/api/main.py`
   - Add navigation link from main dashboard
   - Manual testing

5. **Deployment**:
   - Deploy to Railway (existing `api` service, no new service needed)
   - Verify in production

### External Dependencies

- **Chart.js** (v4.x): Already included via CDN in US-021, reuse same setup
- **SQLAlchemy**: Already in use, need aggregation queries
- **FastAPI**: Already in use
- **Jinja2**: Already in use

No new package installations required.

---

## Risks & Assumptions

### Risks

1. **Performance Risk**: Calculating metrics for 4 models with 90 days of predictions could be slow
   - **Mitigation**: Use SQLAlchemy aggregations (single query), add indexes if needed
   - **Validation**: Test with 4 models x 90 predictions = 360 rows

2. **Sharpe Ratio Complexity**: Sharpe ratio requires statistical calculations (mean, stdev)
   - **Mitigation**: Use simple formula with daily returns, or defer to V2 if too complex
   - **Validation**: Compare with manual calculation in test

3. **Empty State Handling**: Models with no predictions should not break the dashboard
   - **Mitigation**: Check for empty result sets, show "N/A" instead of crashing
   - **Validation**: Test with models that have 0 predictions

### Assumptions

1. **Prediction Data Exists**: Assumes US-025 is already deployed and generating multi-model predictions
   - **Validation**: Check `predictions` table has multiple `model_id` values

2. **Evaluated Predictions**: Assumes evaluator has run and populated `actual_price`, `error_pct`, `pnl_simulated`
   - **Validation**: Filter queries to `WHERE actual_price IS NOT NULL`

3. **No Schema Changes**: Assumes existing tables (`models`, `predictions`) have all needed columns
   - **Validation**: Review schema before starting

4. **Chart.js Available**: Assumes Chart.js CDN is accessible from production (Railway)
   - **Validation**: Check existing dashboard chart in production

---

## Milestones

- [x] **M1: Spec + Plan Approved** (Phase 1 & 2 complete)
- [ ] **M2: Metrics Module Complete** (all functions + tests passing)
- [ ] **M3: API Routes Working** (endpoints return correct data)
- [ ] **M4: Dashboard Renders** (HTML template displays table + chart)
- [ ] **M5: All Tests Passing** (100% Gherkin coverage)
- [ ] **M6: Deployed to Railway** (production verification)

---

## Tasks

### Phase 1: Foundation (Metrics Module)

- [ ] **Task 1.1**: Create `shared/btc_shared/utils/metrics.py`
  - **Acceptance**: File exists, imports work, has docstrings
  - **Files**: `shared/btc_shared/utils/metrics.py`
  - **Tests**: None yet (just scaffolding)
  - **Effort**: XS

- [ ] **Task 1.2**: Implement `calculate_accuracy()`
  - **Acceptance**: Returns % of predictions with `direction_correct = true`
  - **Formula**: `COUNT(*) WHERE direction_correct = true / COUNT(*)`
  - **Files**: `shared/btc_shared/utils/metrics.py`
  - **Tests**: `shared/tests/test_metrics.py::test_calculate_accuracy`
  - **Effort**: S

- [ ] **Task 1.3**: Implement `calculate_mape()`
  - **Acceptance**: Returns mean absolute percentage error
  - **Formula**: `AVG(ABS(predicted - actual) / actual) * 100`
  - **Files**: `shared/btc_shared/utils/metrics.py`
  - **Tests**: `shared/tests/test_metrics.py::test_calculate_mape`
  - **Effort**: S

- [ ] **Task 1.4**: Implement `calculate_total_pnl()`
  - **Acceptance**: Returns sum of `pnl_simulated` for model
  - **Formula**: `SUM(pnl_simulated)`
  - **Files**: `shared/btc_shared/utils/metrics.py`
  - **Tests**: `shared/tests/test_metrics.py::test_calculate_total_pnl`
  - **Effort**: XS

- [ ] **Task 1.5**: Implement `calculate_win_rate()`
  - **Acceptance**: Returns % of predictions with positive PnL
  - **Formula**: `COUNT(*) WHERE pnl_simulated > 0 / COUNT(*)`
  - **Files**: `shared/btc_shared/utils/metrics.py`
  - **Tests**: `shared/tests/test_metrics.py::test_calculate_win_rate`
  - **Effort**: S

- [ ] **Task 1.6**: Implement `calculate_sharpe_ratio()`
  - **Acceptance**: Returns annualized Sharpe ratio
  - **Formula**: `MEAN(daily_returns) / STDEV(daily_returns) * sqrt(365)`
  - **Files**: `shared/btc_shared/utils/metrics.py`
  - **Tests**: `shared/tests/test_metrics.py::test_calculate_sharpe_ratio`
  - **Effort**: M (statistical calculation)

- [ ] **Task 1.7**: Implement `calculate_max_drawdown()`
  - **Acceptance**: Returns largest cumulative loss
  - **Formula**: `MIN(cumulative_pnl - running_max)`
  - **Files**: `shared/btc_shared/utils/metrics.py`
  - **Tests**: `shared/tests/test_metrics.py::test_calculate_max_drawdown`
  - **Effort**: M (cumulative calculation)

- [ ] **Task 1.8**: Implement `get_cumulative_pnl()`
  - **Acceptance**: Returns list of daily cumulative PnL for chart
  - **Returns**: `[{"date": "2024-05-01", "cumulative_pnl": 100}, ...]`
  - **Files**: `shared/btc_shared/utils/metrics.py`
  - **Tests**: `shared/tests/test_metrics.py::test_get_cumulative_pnl`
  - **Effort**: S

- [ ] **Task 1.9**: Implement `get_all_models_metrics()`
  - **Acceptance**: Returns metrics dict for all models in one call
  - **Returns**: `[{"model_id": 1, "name": "linear", "accuracy": 0.65, ...}, ...]`
  - **Files**: `shared/btc_shared/utils/metrics.py`
  - **Tests**: `shared/tests/test_metrics.py::test_get_all_models_metrics`
  - **Effort**: M (orchestration function)

### Phase 2: Backend (API Router)

- [ ] **Task 2.1**: Create `api-service/api/routers/models.py`
  - **Acceptance**: File exists, imports FastAPI, APIRouter
  - **Files**: `api-service/api/routers/models.py`
  - **Tests**: None yet (scaffolding)
  - **Effort**: XS

- [ ] **Task 2.2**: Implement `GET /api/models/metrics`
  - **Acceptance**: Returns JSON with model metrics
  - **Query Params**: `start` (optional), `end` (optional)
  - **Response**: `{"models": [...], "daily_pnl": [...]}`
  - **Files**: `api-service/api/routers/models.py`
  - **Tests**: `api-service/tests/test_models_api.py::test_get_models_metrics_json`
  - **Effort**: S

- [ ] **Task 2.3**: Implement `GET /models` (HTML template)
  - **Acceptance**: Renders `models.html` with metrics data
  - **Query Params**: `start` (optional), `end` (optional)
  - **Files**: `api-service/api/routers/models.py`
  - **Tests**: `api-service/tests/test_models_api.py::test_get_models_dashboard_renders`
  - **Effort**: S

- [ ] **Task 2.4**: Handle date range filtering
  - **Acceptance**: If `?start=2024-05-01&end=2024-05-31`, filter metrics
  - **Validation**: Parse dates, handle invalid formats
  - **Files**: `api-service/api/routers/models.py`
  - **Tests**: `api-service/tests/test_models_api.py::test_models_metrics_with_date_filter`
  - **Effort**: S

- [ ] **Task 2.5**: Wire router into main app
  - **Acceptance**: `app.include_router(models_router)` in `main.py`
  - **Files**: `api-service/api/main.py`
  - **Tests**: None (tested via integration tests)
  - **Effort**: XS

### Phase 3: Frontend (HTML Template)

- [ ] **Task 3.1**: Create `api-service/api/templates/models.html`
  - **Acceptance**: HTML file extends base template, renders
  - **Files**: `api-service/api/templates/models.html`
  - **Tests**: Manual (visual inspection)
  - **Effort**: XS

- [ ] **Task 3.2**: Build comparison table
  - **Acceptance**: Table with 8 columns (model, predictions, accuracy, error%, PnL, win rate, Sharpe, max DD)
  - **Rows**: One per model, data from backend
  - **Files**: `api-service/api/templates/models.html`
  - **Tests**: Manual (visual inspection)
  - **Effort**: S

- [ ] **Task 3.3**: Highlight best performing model
  - **Acceptance**: Row with highest Total PnL has green background + 🏆 badge
  - **Logic**: Backend passes `is_best` flag, template applies CSS
  - **Files**: `api-service/api/templates/models.html`, `models.py` (backend)
  - **Tests**: `api-service/tests/test_models_api.py::test_models_dashboard_highlights_best_model`
  - **Effort**: S

- [ ] **Task 3.4**: Implement date range filter form
  - **Acceptance**: Form with start date, end date inputs, "Apply" button
  - **Behavior**: Submits GET request with `?start=...&end=...`
  - **Files**: `api-service/api/templates/models.html`
  - **Tests**: Manual (functional test)
  - **Effort**: S

- [ ] **Task 3.5**: Add cumulative PnL chart (Chart.js)
  - **Acceptance**: Line chart with one line per model, responsive
  - **Data**: Backend provides `daily_pnl` JSON
  - **Files**: `api-service/api/templates/models.html` (script section)
  - **Tests**: Manual (visual inspection)
  - **Effort**: M (Chart.js configuration)

- [ ] **Task 3.6**: Style with responsive CSS
  - **Acceptance**: Dashboard works on mobile (320px) and desktop (1920px)
  - **Approach**: Use flexbox, media queries
  - **Files**: `api-service/api/templates/models.html` (inline CSS or external)
  - **Tests**: Manual (test on different screen sizes)
  - **Effort**: S

- [ ] **Task 3.7**: Add navigation link from main dashboard
  - **Acceptance**: Button/link on `/` dashboard: "Compare Models"
  - **Files**: `api-service/api/templates/index.html` (main dashboard)
  - **Tests**: Manual (click link, navigates to `/models`)
  - **Effort**: XS

### Phase 4: Testing

- [ ] **Task 4.1**: Write unit tests for metrics functions
  - **Acceptance**: All functions in `metrics.py` have tests, 100% coverage
  - **Files**: `shared/tests/test_metrics.py`
  - **Tests**: 8 test functions (accuracy, mape, pnl, win rate, sharpe, drawdown, cumulative, all models)
  - **Effort**: M

- [ ] **Task 4.2**: Write integration tests for API routes
  - **Acceptance**: All Gherkin scenarios covered
  - **Files**: `api-service/tests/test_models_api.py`
  - **Tests**: 
    - `test_get_models_dashboard_renders()`
    - `test_get_models_metrics_json()`
    - `test_models_metrics_with_date_filter()`
    - `test_models_dashboard_empty_state()`
    - `test_models_dashboard_highlights_best_model()`
  - **Effort**: M

- [ ] **Task 4.3**: Test empty states
  - **Acceptance**: Dashboard handles no models, no predictions gracefully
  - **Files**: `api-service/tests/test_models_api.py`
  - **Tests**: 
    - `test_models_dashboard_no_models()`
    - `test_models_dashboard_no_predictions()`
  - **Effort**: S

- [ ] **Task 4.4**: Run full test suite
  - **Acceptance**: All tests pass, coverage ≥ 90%
  - **Command**: `docker compose exec api pytest --cov`
  - **Effort**: XS

### Phase 5: Quality & Deployment

- [ ] **Task 5.1**: Lint and type-check
  - **Acceptance**: `ruff check` and `ruff format` pass
  - **Command**: `docker compose exec api ruff check shared api-service`
  - **Effort**: XS

- [ ] **Task 5.2**: Manual testing (local)
  - **Acceptance**: Dashboard works end-to-end locally
  - **Checklist**:
    - Navigate to `/models`
    - Verify table renders
    - Verify chart renders
    - Test date filter
    - Test on mobile (Chrome DevTools)
  - **Effort**: S

- [ ] **Task 5.3**: Deploy to Railway
  - **Acceptance**: `api` service redeployed with new routes
  - **Command**: `railway up` or automatic on push to main
  - **Verification**: Visit production `/models` route
  - **Effort**: XS

- [ ] **Task 5.4**: Production verification
  - **Acceptance**: Dashboard works in production with real data
  - **Checklist**:
    - Check production logs for errors
    - Test `/models` and `/api/models/metrics` routes
    - Verify metrics calculation is correct
  - **Effort**: S

- [ ] **Task 5.5**: Update documentation
  - **Acceptance**: README mentions new dashboard, API docs updated
  - **Files**: 
    - `README.md` (add `/models` route)
    - `docs/API.md` (if exists, document `/api/models/metrics`)
  - **Effort**: XS

---

## Effort Estimate

**Total Estimated Time**: 2-3 days

| Phase | Tasks | Effort |
|-------|-------|--------|
| Foundation (Metrics) | 1.1 - 1.9 | 1 day |
| Backend (API) | 2.1 - 2.5 | 0.5 day |
| Frontend (HTML) | 3.1 - 3.7 | 1 day |
| Testing | 4.1 - 4.4 | 0.5 day |
| Quality & Deployment | 5.1 - 5.5 | 0.5 day |

**Total**: ~3.5 days (rounded to 2-3 days accounting for parallelism)

---

## Success Metrics

- [ ] All 26 tasks completed and checked off
- [ ] All Gherkin scenarios from GitHub Issue #28 have passing tests
- [ ] Code coverage ≥ 90%
- [ ] Dashboard renders correctly in production
- [ ] No errors in Railway logs after deployment
- [ ] Manual testing checklist 100% passed

---

## Notes

- **No schema migrations needed**: Existing tables have all required data
- **Reuse Chart.js setup**: From US-021 backtesting dashboard
- **Performance**: Single aggregation query per model, should be fast even with 90 days of data
- **Future enhancements** (out of scope for this US):
  - Model activation button on dashboard
  - Table sorting by columns
  - Export to CSV
  - Advanced filtering (by model type, accuracy threshold)
