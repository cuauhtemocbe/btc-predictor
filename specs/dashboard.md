---
title: Web Dashboard for Predictions
status: approved
created: 2026-05-17
updated: 2026-05-17
issue: #13
---

# Web Dashboard for Predictions

## Objective

Create a web-based dashboard that displays prediction history in a user-friendly table format, showing model accuracy, errors, and directional correctness at a glance for business users.

## Context

With the predictions history API (US-011) now available, we need a visual interface for non-technical users to monitor model performance. The dashboard should replace the current "Hello World" homepage and become the primary landing page of the application.

Business users need to quickly answer:
- How accurate are our predictions?
- What's the error rate trend?
- Is the model directionally correct?
- Which model version is performing best?

## Requirements

### Functional Requirements

- [ ] Create GET / route that renders HTML dashboard
- [ ] Fetch data from /api/predictions/history endpoint
- [ ] Display predictions in a table with columns: Date, Predicted, Actual, Error %, Direction, Model
- [ ] Show "No predictions yet" message when table is empty
- [ ] Color-code direction correctness (green = correct, red = incorrect)
- [ ] Format numbers with 2 decimal places
- [ ] Responsive design (works on mobile and desktop)

### Non-Functional Requirements

- [ ] Performance: Page load < 2 seconds
- [ ] Accessibility: Semantic HTML, readable contrast ratios
- [ ] UX: No JavaScript required (server-side rendering only)
- [ ] Design: Clean, professional appearance (avoid generic AI aesthetics)

## Architecture

### Components

**Main Route Update**: `api-service/api/main.py`
- Replace current `/` route
- Fetch data from predictions API
- Render Jinja2 template

**Dashboard Template**: `api-service/api/templates/dashboard.html`
- Extends a base layout
- Receives predictions data as context
- Displays table with Jinja2 loops

**Static Assets**: `api-service/api/static/` (optional)
- CSS for styling (or use inline styles for simplicity)

### Data Flow

```
Browser → GET / → FastAPI
  ↓
FastAPI fetches /api/predictions/history (internal)
  ↓
Render Jinja2 template with data
  ↓
Return HTML → Browser
```

### Template Structure

```html
<!DOCTYPE html>
<html>
<head>
  <title>BTC Predictor - Dashboard</title>
  <style>
    /* Minimal, clean styling */
  </style>
</head>
<body>
  <h1>Bitcoin Price Predictions</h1>
  
  {% if predictions %}
  <table>
    <thead>
      <tr>
        <th>Date</th>
        <th>Price at Prediction</th>
        <th>Predicted</th>
        <th>Actual</th>
        <th>Error %</th>
        <th>Direction</th>
        <th>Model</th>
      </tr>
    </thead>
    <tbody>
      {% for p in predictions %}
      <tr>
        <td>{{ p.predicted_for }}</td>
        <td>${{ "%.2f"|format(p.price_at_prediction) }}</td>
        <td>${{ "%.2f"|format(p.predicted_price) }}</td>
        <td>${{ "%.2f"|format(p.actual_price) }}</td>
        <td>{{ "%.2f"|format(p.error_pct) }}%</td>
        <td class="{{ 'correct' if p.direction_correct else 'incorrect' }}">
          {{ '✓' if p.direction_correct else '✗' }}
        </td>
        <td>{{ p.model_name }} v{{ p.model_version }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p>No predictions yet. Check back tomorrow!</p>
  {% endif %}
</body>
</html>
```

### External Dependencies

- FastAPI (already in project)
- Jinja2 (already installed with FastAPI)
- httpx (for internal API call, or direct DB query)

## User Stories

Reference: GitHub Issue #13 (US-012)

### Gherkin Scenarios

```gherkin
Feature: Web dashboard

  Scenario: Render dashboard with predictions
    Given the predictions table has 10 evaluated records
    When I navigate to GET /
    Then the response status is 200 OK
    And the response content-type is text/html
    And the HTML contains a table with 10 rows (one per prediction)
    And each row shows: predicted_for, predicted_price, actual_price, error_pct, direction_correct

  Scenario: Dashboard with no data
    Given the predictions table is empty
    When I navigate to GET /
    Then the HTML contains a message "No predictions yet"

  Scenario: Dashboard shows model name
    Given a prediction was made by model "linear_v1"
    When I navigate to GET /
    Then the table row shows "linear_v1" in the Model column
```

## Testing Strategy

### Unit Tests
- Template rendering with mock data
- Number formatting (2 decimals)
- Direction color classes applied correctly

### Integration Tests
- GET / returns 200 OK with text/html content-type
- Dashboard with 10 predictions shows 10 table rows
- Dashboard with empty data shows "No predictions yet"
- Table includes model name and version
- Verify HTML structure (table, thead, tbody)
- Verify CSS classes for direction correctness

**Test Location**: `api-service/tests/test_dashboard.py`

**Test Strategy**:
```python
# Parse HTML response with BeautifulSoup
from bs4 import BeautifulSoup

async def test_dashboard_with_data(client, db_session):
    # Create 10 evaluated predictions
    # ...
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    
    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.find("tbody").find_all("tr")
    assert len(rows) == 10
```

### Manual Testing
- Load dashboard in browser
- Verify responsive design on mobile
- Check color contrast for accessibility
- Verify no console errors

### Coverage Target
- 95%+ coverage on route logic
- All 3 Gherkin scenarios covered

## Boundaries & Constraints

### In Scope
- Single-page dashboard showing prediction table
- Server-side rendering (Jinja2)
- Basic styling (clean, professional)

### Out of Scope
- Interactive charts (JS libraries like Chart.js)
- Real-time updates (WebSocket)
- User authentication/login
- Admin panel for manual predictions
- Export to CSV/Excel
- Advanced filtering UI (date pickers, model selector)

### Technical Constraints
- Must run inside Docker container
- No external CSS frameworks (keep it lightweight)
- No JavaScript (progressive enhancement if added later)
- Database: PostgreSQL via shared package

## Success Criteria

- [ ] All 3 Gherkin scenarios have passing automated tests
- [ ] Dashboard replaces "Hello World" at GET /
- [ ] Table displays all evaluated predictions
- [ ] "No predictions yet" message shown when empty
- [ ] Direction correctness color-coded
- [ ] Model name and version displayed
- [ ] Page loads in < 2 seconds
- [ ] Responsive on mobile and desktop
- [ ] HTML validates (no broken tags)
- [ ] Lint checks pass (ruff)

## Implementation Plan

See: `specs/dashboard-plan.md`
