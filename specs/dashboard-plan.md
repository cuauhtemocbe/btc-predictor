# Implementation Plan: Web Dashboard for Predictions

**Spec**: [dashboard.md](./dashboard.md)  
**Created**: 2026-05-17  
**Status**: approved

## Components

### 1. Jinja2 Template
- **Purpose**: HTML template for dashboard table
- **Files**: `api-service/api/templates/dashboard.html` (new)
- **Effort**: M

### 2. Dashboard Route
- **Purpose**: Fetch data and render template
- **Files**: `api-service/api/main.py` (update existing GET / route)
- **Effort**: S

### 3. Internal API Client
- **Purpose**: Fetch predictions from /api/predictions/history
- **Files**: Inline in route (or `api-service/api/utils.py` if reusable)
- **Effort**: XS

### 4. Integration Tests
- **Purpose**: Test all Gherkin scenarios with HTML parsing
- **Files**: `api-service/tests/test_dashboard.py` (new)
- **Effort**: M

## Dependencies

### Build Order
1. **Dashboard route skeleton** (foundation - basic structure)
2. **Jinja2 template** (UI layer - depends on route contract)
3. **Internal API client** (data fetching - depends on US-011 API)
4. **Wire everything together** (integration)
5. **Tests** (verification - depends on all above)

### External Dependencies
- **Dependency on US-011**: Requires /api/predictions/history endpoint to be functional
- **BeautifulSoup4**: Add to dev dependencies for HTML parsing in tests

## Risks & Assumptions

### Risks
- **US-011 API not ready**: Mitigate by implementing US-011 first (in order)
- **Template complexity**: Mitigate by keeping design minimal, no fancy CSS

### Assumptions
- US-011 (/api/predictions/history) is already implemented
- Predictions table has some evaluated records for testing
- FastAPI template support (Jinja2) is already configured

## Milestones

- [ ] **Milestone 1**: Template created, renders with mock data
- [ ] **Milestone 2**: Route fetches real data from API and renders
- [ ] **Milestone 3**: All Gherkin scenarios have passing tests

## Tasks

### Foundation (Build First)

- [ ] **Task 1: Create dashboard template**
  - **Acceptance**: dashboard.html renders table with sample data
  - **Files**: `api-service/api/templates/dashboard.html`
  - **Tests**: Manual browser check
  - **Effort**: M (1.5 hours)
  - **Details**:
    - HTML structure: head, body, table
    - Jinja2 loops: `{% for p in predictions %}`
    - Conditional: `{% if predictions %}` / `{% else %}`
    - CSS: Inline styles or separate file
    - Color classes: `.correct` (green), `.incorrect` (red)

### Features (Build Second)

- [ ] **Task 2: Update GET / route to fetch and render**
  - **Acceptance**: Route fetches from /api/predictions/history and passes to template
  - **Files**: `api-service/api/main.py`
  - **Tests**: Integration test
  - **Effort**: S (1 hour)
  - **Details**:
    - Import httpx or use direct CRUD call
    - Fetch predictions (internal call or DB query)
    - Render template with predictions context
    - Handle empty predictions list

### Integration (Build Third)

- [ ] **Task 3: Add BeautifulSoup to dev dependencies**
  - **Acceptance**: pytest can import BeautifulSoup
  - **Files**: `pyproject.toml` (api-service)
  - **Tests**: Import test
  - **Effort**: XS (5 min)

- [ ] **Task 4: Write integration tests with HTML parsing**
  - **Acceptance**: All 3 Gherkin scenarios pass
  - **Files**: `api-service/tests/test_dashboard.py`
  - **Tests**:
    - Test 1: Dashboard with 10 predictions → 10 table rows
    - Test 2: Dashboard with no data → "No predictions yet" message
    - Test 3: Dashboard shows model name in table
  - **Effort**: M (1.5 hours)

## Effort Estimate

**Total Estimated Time**: 4 hours (half day)

| Phase | Effort |
|-------|--------|
| Template | 1.5 hours |
| Route update | 1 hour |
| Test setup (BeautifulSoup) | 5 min |
| Tests | 1.5 hours |

## Verification Steps

After implementation:
1. Run tests: `docker compose exec api pytest api-service/tests/test_dashboard.py -v`
2. Manual browser test: Open `http://localhost:8000/` in browser
3. Verify table renders with real data
4. Verify "No predictions yet" message when DB is empty
5. Check responsive design on mobile (dev tools)
6. Verify HTML validity (W3C validator or browser inspector)
7. Run lint: `docker compose exec api ruff check api-service/`

## Design Notes

### CSS Styling Strategy
Keep it minimal and inline for now:
```css
body { font-family: sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
th { background-color: #f5f5f5; font-weight: bold; }
.correct { color: #22c55e; font-weight: bold; }
.incorrect { color: #ef4444; font-weight: bold; }
```

### Template Variable Contract
```python
# Route passes to template:
{
  "predictions": [
    {
      "predicted_for": date,
      "price_at_prediction": float,
      "predicted_price": float,
      "actual_price": float,
      "error_pct": float,
      "direction_correct": bool,
      "model_name": str,
      "model_version": str
    }
  ]
}
```
