"""
Integration tests for model comparison API (US-026).

Tests for:
- GET /models - HTML dashboard rendering
- GET /models/metrics - JSON API endpoint
- Date range filtering
- Empty states handling
- Best model highlighting
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from httpx import AsyncClient
from sqlalchemy.orm import Session

from shared.db.models import Model, Prediction

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_models_with_predictions(db_session: Session):
    """
    Create sample models with evaluated predictions for testing.

    Creates 3 models with different performance characteristics:
    - linear_v1: 2 predictions, 100% accuracy, $150 total PnL
    - lstm_v1: 3 predictions, 66.7% accuracy, $220 total PnL (best)
    - xgboost_v1: 1 prediction, 0% accuracy, -$30 total PnL
    """
    # Create models
    linear = Model(
        name="linear_v1",
        version="1.0.0",
        params={"window_days": 30},
        artifact=b"fake_pickle",
        trained_at=datetime.now(UTC),
        train_from=date.today() - timedelta(days=30),
        train_to=date.today(),
        is_active=True,
    )
    lstm = Model(
        name="lstm_v1",
        version="1.0.0",
        params={"window_days": 60},
        artifact=b"fake_pickle",
        trained_at=datetime.now(UTC),
        train_from=date.today() - timedelta(days=60),
        train_to=date.today(),
        is_active=False,
    )
    xgboost = Model(
        name="xgboost_v1",
        version="1.0.0",
        params={"window_days": 30},
        artifact=b"fake_pickle",
        trained_at=datetime.now(UTC),
        train_from=date.today() - timedelta(days=30),
        train_to=date.today(),
        is_active=False,
    )

    db_session.add_all([linear, lstm, xgboost])
    db_session.commit()
    db_session.refresh(linear)
    db_session.refresh(lstm)
    db_session.refresh(xgboost)

    # Linear model: 2 predictions, 100% accuracy, $150 PnL
    db_session.add_all(
        [
            Prediction(
                model_id=linear.id,
                predicted_for=date(2024, 5, 1),
                predicted_at=datetime(2024, 4, 30, 10, 0, tzinfo=UTC),
                price_at_prediction=Decimal("67000.00"),
                predicted_price=Decimal("68000.00"),
                actual_price=Decimal("67500.00"),
                evaluated_at=datetime(2024, 5, 1, 10, 0, tzinfo=UTC),
                error_abs=Decimal("500.00"),
                error_pct=Decimal("0.74"),
                direction_correct=True,
                pnl_simulated=Decimal("100.00"),
            ),
            Prediction(
                model_id=linear.id,
                predicted_for=date(2024, 5, 2),
                predicted_at=datetime(2024, 5, 1, 10, 0, tzinfo=UTC),
                price_at_prediction=Decimal("67500.00"),
                predicted_price=Decimal("68000.00"),
                actual_price=Decimal("67550.00"),
                evaluated_at=datetime(2024, 5, 2, 10, 0, tzinfo=UTC),
                error_abs=Decimal("450.00"),
                error_pct=Decimal("0.67"),
                direction_correct=True,
                pnl_simulated=Decimal("50.00"),
            ),
        ]
    )

    # LSTM model: 3 predictions, 66.7% accuracy, $220 PnL
    db_session.add_all(
        [
            Prediction(
                model_id=lstm.id,
                predicted_for=date(2024, 5, 1),
                predicted_at=datetime(2024, 4, 30, 10, 0, tzinfo=UTC),
                price_at_prediction=Decimal("67000.00"),
                predicted_price=Decimal("68000.00"),
                actual_price=Decimal("67200.00"),
                evaluated_at=datetime(2024, 5, 1, 10, 0, tzinfo=UTC),
                error_abs=Decimal("800.00"),
                error_pct=Decimal("1.19"),
                direction_correct=True,
                pnl_simulated=Decimal("200.00"),
            ),
            Prediction(
                model_id=lstm.id,
                predicted_for=date(2024, 5, 2),
                predicted_at=datetime(2024, 5, 1, 10, 0, tzinfo=UTC),
                price_at_prediction=Decimal("67200.00"),
                predicted_price=Decimal("68000.00"),
                actual_price=Decimal("66800.00"),
                evaluated_at=datetime(2024, 5, 2, 10, 0, tzinfo=UTC),
                error_abs=Decimal("1200.00"),
                error_pct=Decimal("1.80"),
                direction_correct=False,
                pnl_simulated=Decimal("-400.00"),
            ),
            Prediction(
                model_id=lstm.id,
                predicted_for=date(2024, 5, 3),
                predicted_at=datetime(2024, 5, 2, 10, 0, tzinfo=UTC),
                price_at_prediction=Decimal("66800.00"),
                predicted_price=Decimal("68000.00"),
                actual_price=Decimal("67220.00"),
                evaluated_at=datetime(2024, 5, 3, 10, 0, tzinfo=UTC),
                error_abs=Decimal("780.00"),
                error_pct=Decimal("1.16"),
                direction_correct=True,
                pnl_simulated=Decimal("420.00"),
            ),
        ]
    )

    # XGBoost model: 1 prediction, 0% accuracy, -$30 PnL
    db_session.add(
        Prediction(
            model_id=xgboost.id,
            predicted_for=date(2024, 5, 1),
            predicted_at=datetime(2024, 4, 30, 10, 0, tzinfo=UTC),
            price_at_prediction=Decimal("67000.00"),
            predicted_price=Decimal("68000.00"),
            actual_price=Decimal("66970.00"),
            evaluated_at=datetime(2024, 5, 1, 10, 0, tzinfo=UTC),
            error_abs=Decimal("1030.00"),
            error_pct=Decimal("1.54"),
            direction_correct=False,
            pnl_simulated=Decimal("-30.00"),
        )
    )

    db_session.commit()

    return {"linear": linear, "lstm": lstm, "xgboost": xgboost}


# ============================================================================
# Test Cases
# ============================================================================


@pytest.mark.asyncio
async def test_models_dashboard_renders_with_models(
    client: AsyncClient, db_session: Session, sample_models_with_predictions
):
    """
    Scenario: Access model comparison dashboard

    Given there are 3 models with evaluated predictions
    When I navigate to GET /models
    Then I see a page titled "Model Performance Comparison"
    And I see a comparison table with all models
    And I see a link back to the main dashboard
    """
    # Act
    response = await client.get("/models/")

    # Assert
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    # Parse HTML
    soup = BeautifulSoup(response.text, "html.parser")

    # Verify title
    h1 = soup.find("h1")
    assert h1 is not None
    assert "Model Performance Comparison" in h1.text

    # Verify table exists
    table = soup.find("table")
    assert table is not None, "Dashboard should contain a comparison table"

    # Verify table has 3 rows (one per model)
    tbody = table.find("tbody")
    rows = tbody.find_all("tr")
    assert len(rows) == 3, f"Expected 3 model rows, got {len(rows)}"

    # Verify navigation link back to dashboard
    nav_link = soup.find("a", class_="nav-link")
    assert nav_link is not None
    assert nav_link["href"] == "/"


@pytest.mark.asyncio
async def test_models_dashboard_shows_all_metrics(
    client: AsyncClient, db_session: Session, sample_models_with_predictions
):
    """
    Scenario: Model comparison table shows key metrics

    Given there are 3 models with different performance
    When I view the model comparison table
    Then I see columns: Model, Predictions, Accuracy, Avg Error %, Total PnL, Win Rate, Sharpe, Max DD
    And I see metrics for all 3 models
    """
    # Act
    response = await client.get("/models/")

    # Assert
    soup = BeautifulSoup(response.text, "html.parser")

    # Verify table headers
    thead = soup.find("thead")
    headers = [th.text.strip() for th in thead.find_all("th")]
    expected_headers = [
        "Model",
        "Predictions",
        "Accuracy",
        "Avg Error %",
        "Total PnL",
        "Win Rate",
        "Sharpe",
        "Max DD",
    ]
    assert headers == expected_headers

    # Verify each model has data in all columns
    tbody = soup.find("tbody")
    rows = tbody.find_all("tr")

    for row in rows:
        cells = row.find_all("td")
        assert len(cells) == 8, "Each row should have 8 cells"

        # Verify no empty cells (except N/A for metrics)
        for cell in cells:
            assert cell.text.strip() != "", "Cell should not be empty"


@pytest.mark.asyncio
async def test_models_dashboard_highlights_best_model(
    client: AsyncClient, db_session: Session, sample_models_with_predictions
):
    """
    Scenario: Highlight best performing model

    Given the models have different Total PnL
    When I view the comparison table
    Then the lstm_v1 row is highlighted (green background)
    And there is a badge "🏆 Best Return" next to it
    """
    # Act
    response = await client.get("/models/")

    # Assert
    soup = BeautifulSoup(response.text, "html.parser")

    # Find the best model row (should be highlighted)
    best_row = soup.find("tr", class_="best-model")
    assert best_row is not None, "Best model row should have 'best-model' class"

    # Verify the best model is lstm_v1 (highest total PnL: $220)
    model_name_cell = best_row.find("span", class_="model-name")
    assert "lstm_v1" in model_name_cell.text

    # Verify the "🏆 Best Return" badge exists
    badges = best_row.find_all("span", class_="badge")
    badge_texts = [badge.text.strip() for badge in badges]
    assert any("Best Return" in text for text in badge_texts), (
        "Best model badge not found"
    )


@pytest.mark.asyncio
async def test_models_dashboard_empty_state(client: AsyncClient, db_session: Session):
    """
    Scenario: Empty state when no models exist

    Given there are no models in the database
    When I visit /models
    Then I see a message "No models have been trained yet"
    And I see instructions to run train_all_models.py
    """
    # Arrange: No models in database (db_session is clean)

    # Act
    response = await client.get("/models/")

    # Assert
    assert response.status_code == 200

    soup = BeautifulSoup(response.text, "html.parser")

    # Verify empty state
    empty_state = soup.find("div", class_="empty-state")
    assert empty_state is not None, "Should show empty state when no models"

    # Verify message content
    h2 = empty_state.find("h2")
    assert "No Models Found" in h2.text

    # Verify instructions
    code = empty_state.find("code")
    assert code is not None
    assert "train_all_models.py" in code.text


@pytest.mark.asyncio
async def test_models_dashboard_with_date_filter(
    client: AsyncClient, db_session: Session, sample_models_with_predictions
):
    """
    Scenario: Filter model comparison by date range

    Given there are predictions from May 1-3
    When I select start_date = "2024-05-01" and end_date = "2024-05-02"
    Then the metrics are calculated from May 1-2 only
    And the URL includes query params: ?start_date=2024-05-01&end_date=2024-05-02
    """
    # Act
    response = await client.get("/models/?start_date=2024-05-01&end_date=2024-05-02")

    # Assert
    assert response.status_code == 200

    soup = BeautifulSoup(response.text, "html.parser")

    # Verify filter form exists
    filter_form = soup.find("form", class_="filter-form")
    assert filter_form is not None

    # Verify date inputs have correct values
    start_input = soup.find("input", {"name": "start_date"})
    assert start_input["value"] == "2024-05-01"

    end_input = soup.find("input", {"name": "end_date"})
    assert end_input["value"] == "2024-05-02"

    # Verify table still renders (with filtered data)
    table = soup.find("table")
    assert table is not None


@pytest.mark.asyncio
async def test_models_metrics_api_returns_json(
    client: AsyncClient, db_session: Session, sample_models_with_predictions
):
    """
    Scenario: API endpoint returns model metrics as JSON

    When I GET /models/metrics
    Then I receive a 200 response
    And the JSON has structure:
      {
        "models": [...],
        "daily_pnl": {...},
        "filters": {...}
      }
    """
    # Act
    response = await client.get("/models/metrics")

    # Assert
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"

    data = response.json()

    # Verify structure
    assert "models" in data
    assert "daily_pnl" in data
    assert "filters" in data

    # Verify models list
    assert isinstance(data["models"], list)
    assert len(data["models"]) == 3

    # Verify each model has required fields
    for model in data["models"]:
        assert "id" in model
        assert "name" in model
        assert "version" in model
        assert "is_active" in model
        assert "predictions_count" in model
        assert "accuracy" in model
        assert "avg_error_pct" in model
        assert "total_pnl" in model
        assert "win_rate" in model
        assert "sharpe_ratio" in model
        assert "max_drawdown" in model


@pytest.mark.asyncio
async def test_models_metrics_api_with_date_filter(
    client: AsyncClient, db_session: Session, sample_models_with_predictions
):
    """
    Scenario: API endpoint supports date filtering

    When I GET /models/metrics?start_date=2024-05-01&end_date=2024-05-02
    Then the metrics are calculated for May 1-2 only
    And the response includes the applied filters
    """
    # Act
    response = await client.get(
        "/models/metrics?start_date=2024-05-01&end_date=2024-05-02"
    )

    # Assert
    assert response.status_code == 200

    data = response.json()

    # Verify filters are included in response
    assert data["filters"]["start_date"] == "2024-05-01"
    assert data["filters"]["end_date"] == "2024-05-02"

    # Verify models are still returned
    assert len(data["models"]) == 3


@pytest.mark.asyncio
async def test_models_metrics_calculates_correctly(
    client: AsyncClient, db_session: Session, sample_models_with_predictions
):
    """
    Scenario: Verify metrics calculations are correct

    Given lstm_v1 has 3 predictions: 2 correct, 1 incorrect
    And PnL values: 200, -400, 420 (total: 220)
    When I GET /models/metrics
    Then lstm_v1 has:
      - accuracy: 0.6667 (66.7%)
      - total_pnl: 220.00
      - predictions_count: 3
    """
    # Act
    response = await client.get("/models/metrics")

    # Assert
    data = response.json()

    # Find lstm_v1
    lstm = next(m for m in data["models"] if m["name"] == "lstm_v1")

    # Verify metrics
    assert lstm["predictions_count"] == 3
    assert abs(lstm["accuracy"] - 0.6667) < 0.001  # ~66.7%
    assert lstm["total_pnl"] == 220.0

    # Verify win rate (2 wins out of 3)
    assert abs(lstm["win_rate"] - 0.6667) < 0.001


@pytest.mark.asyncio
async def test_models_api_handles_empty_state(client: AsyncClient, db_session: Session):
    """
    Scenario: API returns empty list when no models exist

    Given there are no models in the database
    When I GET /models/metrics
    Then the response has models: []
    And the response has daily_pnl: {}
    """
    # Arrange: No models (clean db_session)

    # Act
    response = await client.get("/models/metrics")

    # Assert
    assert response.status_code == 200

    data = response.json()

    assert data["models"] == []
    assert data["daily_pnl"] == {}
