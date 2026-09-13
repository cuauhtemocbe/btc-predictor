---
title: US-026 - Model Comparison Dashboard
status: approved
created: 2026-05-19
updated: 2026-05-19
issue: #28
---

# US-026: Model Comparison Dashboard

## Objective

Build a comprehensive dashboard that enables Bitcoin traders to compare the performance of all ML models (Linear, LSTM, XGBoost, ARIMA) through visual metrics including accuracy, PnL, win rate, Sharpe ratio, and cumulative returns. This allows traders to identify the best performing model at a glance and make informed decisions about which model to activate.

## Context

### Current State
- Dashboard exists at `/` showing predictions from one active model
- No way to visually compare performance across models
- Cannot see historical performance metrics per model
- Traders cannot easily determine which model is most accurate or profitable

### Problem Statement
After implementing US-023 (advanced ML models), US-024 (multi-model training), and US-025 (multi-model predictions), we now have 4 different models generating predictions. Traders need a way to evaluate which model performs best over time, but currently have no dashboard to compare:
- Accuracy (direction correctness)
- Error metrics (MAPE)
- Profitability (Total PnL)
- Risk metrics (Sharpe ratio, max drawdown)

### User Need
**As a Bitcoin trader evaluating ML models**  
**I want to see a dashboard comparing the performance of all models**  
**In order to identify which model generates the best predictions and highest returns**

### Desired State
- New route `/models` with model comparison dashboard
- Comparison table showing key metrics per model
- Cumulative PnL line chart showing all models over time
- Date range filter to analyze specific periods
- Visual highlight of best performing model
- Ability to activate a different model directly from dashboard

## Requirements

### Functional Requirements

- [ ] **FR1**: Display model comparison table with metrics:
  - Model name + version
  - Prediction count (evaluated predictions only)
  - Accuracy (% direction correct)
  - Average Error % (MAPE)
  - Total PnL (sum of pnl_simulated)
  - Win Rate (% of positive PnL predictions)
  - Sharpe Ratio (risk-adjusted returns)
  - Max Drawdown (largest cumulative loss)
  - Trained at timestamp
  - Active status

- [ ] **FR2**: Cumulative PnL chart showing all models
  - Line chart with one line per model
  - X-axis: Date (prediction date)
  - Y-axis: Cumulative PnL in USD
  - Different color per model
  - Responsive and interactive (Chart.js)

- [ ] **FR3**: Date range filter
  - Start date and end date inputs
  - "Apply Filter" button
  - Update both table and chart on filter
  - URL query params: `?start=YYYY-MM-DD&end=YYYY-MM-DD`

- [ ] **FR4**: Highlight best performing model
  - Identify model with highest Total PnL
  - Visual highlight (green background or border)
  - Badge showing "🏆 Best Return"

- [ ] **FR5**: Handle empty states gracefully
  - No models exist → "No models trained yet" message
  - Model has no predictions → Show "N/A" for metrics
  - Model has predictions but not evaluated → Show "X predictions pending evaluation"

- [ ] **FR6**: Navigation link from main dashboard to `/models`

- [ ] **FR7**: API endpoint for metrics
  - Route: `GET /api/models/metrics`
  - Query params: `start` (date), `end` (date)
  - Returns JSON with model metrics and daily PnL breakdown

### Non-Functional Requirements

- [ ] **NFR1**: Performance: Page load < 1 second with 4 models and 90 days of predictions
- [ ] **NFR2**: Query optimization: Use single query with aggregations instead of N+1 queries
- [ ] **NFR3**: Responsive design: Dashboard works on mobile (320px+) and desktop
- [ ] **NFR4**: Accessibility: Table headers, chart alt text, keyboard navigation
- [ ] **NFR5**: Error handling: Handle DB connection errors, missing data gracefully
- [ ] **NFR6**: Logging: Log metrics calculation time, filter usage

## Architecture

### Components

1. **Backend API Router** (`api/routers/models.py`)
   - `GET /models` → Render HTML template
   - `GET /api/models/metrics` → Return JSON metrics
   - Calculate metrics per model using SQLAlchemy aggregations
   - Calculate cumulative PnL from daily predictions

2. **Frontend Template** (`api/templates/models.html`)
   - Jinja2 template extending base layout
   - Comparison table (HTML + CSS)
   - Chart.js integration for cumulative PnL
   - Date range filter form
   - Responsive CSS

3. **Metrics Calculation Logic** (`shared/utils/metrics.py`)
   - `calculate_model_metrics(model_id, start_date, end_date)` → dict
   - `calculate_cumulative_pnl(model_id, start_date, end_date)` → list
   - Sharpe ratio calculation
   - Max drawdown calculation

### Data Model

Existing tables (no schema changes needed):
- `models` — model metadata (id, name, is_active, trained_at)
- `predictions` — predictions with model_id FK
- `prices` — historical BTC prices

Key relationships:
- `predictions.model_id` → `models.id`
- `predictions.actual_price` → only count evaluated predictions (actual_price IS NOT NULL)

### Metrics Calculations

```python
# Accuracy (direction correctness)
Accuracy = COUNT(*) WHERE direction_correct = true / COUNT(*)

# MAPE (Mean Absolute Percentage Error)
MAPE = AVG(ABS(predicted_price - actual_price) / actual_price) * 100

# Total PnL
Total PnL = SUM(pnl_simulated)

# Win Rate
Win Rate = COUNT(*) WHERE pnl_simulated > 0 / COUNT(*)

# Sharpe Ratio (simplified, annualized)
Daily Returns = pnl_simulated / price_at_prediction
Sharpe = MEAN(Daily Returns) / STDEV(Daily Returns) * sqrt(365)

# Max Drawdown
Cumulative PnL = [cum_sum of pnl_simulated]
Running Max = [running max of Cumulative PnL]
Drawdown = Cumulative PnL - Running Max
Max Drawdown = MIN(Drawdown)
```

### External Dependencies

- **Chart.js**: For cumulative PnL visualization (already used in US-021)
- **SQLAlchemy**: Aggregation queries with `func.sum()`, `func.avg()`, `func.count()`
- **Pandas** (optional): For Sharpe ratio / max drawdown if complex

## User Stories

See GitHub Issue #28 for complete Gherkin scenarios.

Key scenarios:
- Access model comparison dashboard
- View comparison table with all metrics
- Calculate accuracy, MAPE, Total PnL correctly
- Highlight best performing model
- Display cumulative PnL chart
- Filter by date range
- Handle empty states (no models, no predictions)
- API endpoint returns JSON metrics

## Testing Strategy

### Unit Tests
- `shared/tests/test_metrics.py` — metrics calculation functions
  - `test_calculate_accuracy()`
  - `test_calculate_mape()`
  - `test_calculate_total_pnl()`
  - `test_calculate_win_rate()`
  - `test_calculate_sharpe_ratio()`
  - `test_calculate_max_drawdown()`

### Integration Tests
- `api-service/tests/test_models_api.py` — API routes
  - `test_get_models_dashboard_renders()`
  - `test_get_models_metrics_json()`
  - `test_models_metrics_with_date_filter()`
  - `test_models_dashboard_empty_state()`
  - `test_models_dashboard_highlights_best_model()`

### Visual Tests
- Manual: Verify chart renders correctly
- Manual: Verify responsive design on mobile
- Manual: Verify table sorting works

### Coverage Target
- Unit tests: 100% for metrics functions
- Integration tests: All Gherkin scenarios covered
- Overall: >90% coverage maintained

## Boundaries & Constraints

### In Scope
- Model comparison dashboard at `/models`
- Metrics table with key performance indicators
- Cumulative PnL chart
- Date range filter
- Best model highlight
- API endpoint for metrics

### Out of Scope
- Model activation from dashboard (can be added later, for now manual via CLI)
- Table sorting (can be added later)
- Export to CSV (can be added later)
- Advanced filtering (by model type, accuracy threshold)
- Real-time updates (dashboard is static, requires refresh)

### Technical Constraints
- **Tech Stack**: FastAPI + Jinja2 + Chart.js (no React/Vue)
- **Database**: PostgreSQL (use SQLAlchemy aggregations, not raw SQL)
- **Design**: Follow existing dashboard style (bootstrap/simple CSS)
- **Performance**: Single query per metric calculation (no N+1)

## Success Criteria

- [ ] Dashboard renders at `GET /models` with status 200
- [ ] Comparison table displays all models with 8 metrics
- [ ] Metrics calculations are accurate (verified by tests)
- [ ] Best performing model is visually highlighted
- [ ] Cumulative PnL chart displays correctly with Chart.js
- [ ] Date range filter updates metrics and chart
- [ ] Empty states handled gracefully (no crashes)
- [ ] API endpoint returns correct JSON structure
- [ ] All Gherkin scenarios have passing tests
- [ ] Code coverage ≥ 90%
- [ ] Lint (ruff) and type-check pass
- [ ] Manual testing on mobile and desktop successful
- [ ] Documentation updated (README, API docs)
- [ ] Deployed to Railway successfully

## Implementation Plan

See `specs/us-026-model-comparison-dashboard-plan.md`
