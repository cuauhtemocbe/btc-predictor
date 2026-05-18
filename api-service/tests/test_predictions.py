"""
Integration tests for predictions API endpoints.

Tests the /api/predictions/history endpoint with various scenarios:
- Fetching all evaluated predictions
- Empty result when no evaluated predictions
- Date range filtering
"""

import pickle
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from shared.db.models import Model, Prediction


@pytest.fixture
def sample_model(db_session: Session) -> Model:
    """
    Create a sample ML model for testing predictions.
    Automatically cleaned up via db_session rollback.
    """
    # Create a dummy model artifact (minimal sklearn LinearRegression)
    from sklearn.linear_model import LinearRegression
    import numpy as np

    dummy_model = LinearRegression()
    dummy_model.fit(np.array([[1], [2], [3]]), np.array([1, 2, 3]))
    artifact = pickle.dumps(dummy_model)

    model = Model(
        name="linear_v1",
        version="1.0.0",
        params={"window_days": 30},
        artifact=artifact,
        trained_at=datetime.now(timezone.utc),
        train_from=date.today() - timedelta(days=30),
        train_to=date.today() - timedelta(days=1),
        is_active=True,
    )
    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)
    return model


@pytest.fixture
def sample_predictions_factory(db_session: Session, sample_model: Model):
    """
    Factory fixture for creating prediction records.

    Usage:
        sample_predictions_factory(count=10, evaluated=True)
    """
    def _create_predictions(count: int = 10, evaluated: bool = True):
        predictions = []
        base_date = date.today()

        for i in range(count):
            predicted_for = base_date - timedelta(days=i)
            predicted_at = datetime.combine(
                predicted_for - timedelta(days=1),
                datetime.min.time(),
                tzinfo=timezone.utc
            ).replace(hour=19)  # 7pm day before

            price_at_prediction = Decimal("67000.0") + Decimal(i * 100)
            predicted_price = Decimal("67500.0") + Decimal(i * 100)

            prediction = Prediction(
                model_id=sample_model.id,
                predicted_for=predicted_for,
                predicted_at=predicted_at,
                price_at_prediction=price_at_prediction,
                predicted_price=predicted_price,
            )

            # Add evaluation fields if evaluated=True
            if evaluated:
                actual_price = Decimal("67800.0") + Decimal(i * 100)
                prediction.actual_price = actual_price
                prediction.evaluated_at = datetime.combine(
                    predicted_for,
                    datetime.min.time(),
                    tzinfo=timezone.utc
                ).replace(hour=7, minute=1)  # 7:01am on prediction day
                prediction.error_abs = abs(actual_price - predicted_price)
                prediction.error_pct = (
                    abs(actual_price - predicted_price) / actual_price * 100
                )
                prediction.direction_correct = (
                    (predicted_price > price_at_prediction and actual_price > price_at_prediction)
                    or (predicted_price < price_at_prediction and actual_price < price_at_prediction)
                    or (predicted_price == price_at_prediction and actual_price == price_at_prediction)
                )
                # Simple PnL: if predicted up, gain = actual - price_at_prediction, else 0
                if predicted_price > price_at_prediction:
                    prediction.pnl_simulated = actual_price - price_at_prediction
                else:
                    prediction.pnl_simulated = Decimal("0.0")

            db_session.add(prediction)
            predictions.append(prediction)

        db_session.commit()
        for p in predictions:
            db_session.refresh(p)

        return predictions

    return _create_predictions


# Gherkin Scenario 1: Fetch all evaluated predictions
@pytest.mark.asyncio
async def test_fetch_all_evaluated_predictions(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_factory,
):
    """
    Given the predictions table has 30 evaluated records (actual_price != NULL)
    And 5 unevaluated records (actual_price = NULL)
    When I send GET /api/predictions/history
    Then the response status is 200 OK
    And the response body is a JSON array with 30 items (only evaluated)
    And each item has keys: predicted_for, predicted_price, actual_price,
                           error_abs, error_pct, direction_correct, model_name
    And items are ordered by predicted_for DESC
    """
    # Arrange: Create 30 evaluated + 5 unevaluated predictions
    sample_predictions_factory(count=30, evaluated=True)
    sample_predictions_factory(count=5, evaluated=False)

    # Act: Fetch predictions history
    response = await client.get("/api/predictions/history")

    # Assert
    assert response.status_code == 200
    data = response.json()

    # Should return only evaluated predictions
    assert len(data) == 30

    # Verify structure of first item
    first = data[0]
    assert "predicted_for" in first
    assert "predicted_price" in first
    assert "actual_price" in first
    assert "error_abs" in first
    assert "error_pct" in first
    assert "direction_correct" in first
    assert "model_name" in first
    assert "model_version" in first

    # Verify model info
    assert first["model_name"] == "linear_v1"
    assert first["model_version"] == "1.0.0"

    # Verify ordering (DESC by predicted_for)
    dates = [item["predicted_for"] for item in data]
    assert dates == sorted(dates, reverse=True)


# Gherkin Scenario 2: No evaluated predictions yet
@pytest.mark.asyncio
async def test_no_evaluated_predictions(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_factory,
):
    """
    Given all predictions have actual_price = NULL
    When I send GET /api/predictions/history
    Then the response status is 200 OK
    And the response body is an empty JSON array []
    """
    # Arrange: Create only unevaluated predictions
    sample_predictions_factory(count=5, evaluated=False)

    # Act
    response = await client.get("/api/predictions/history")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data == []
    assert len(data) == 0


# Gherkin Scenario 3: Filter by date range
@pytest.mark.asyncio
async def test_filter_by_date_range(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_factory,
):
    """
    Given I send GET /api/predictions/history?from=2026-05-01&to=2026-05-15
    Then the response contains only predictions where predicted_for is between those dates
    """
    # Arrange: Create predictions spanning 30 days
    sample_predictions_factory(count=30, evaluated=True)

    # Act: Filter by specific date range (last 15 days)
    from_date = date.today() - timedelta(days=14)
    to_date = date.today()

    response = await client.get(
        f"/api/predictions/history?from={from_date.isoformat()}&to={to_date.isoformat()}"
    )

    # Assert
    assert response.status_code == 200
    data = response.json()

    # Should return predictions within date range
    # With 30 predictions spanning 30 days, filtering to 15 days should return ~15
    assert len(data) > 0
    assert len(data) <= 15

    # Verify all dates are within range
    for item in data:
        prediction_date = date.fromisoformat(item["predicted_for"])
        assert from_date <= prediction_date <= to_date


# Edge case: Filter by from_date only
@pytest.mark.asyncio
async def test_filter_from_date_only(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_factory,
):
    """
    Test filtering with only from_date parameter.
    Should return all predictions from that date forward.
    """
    # Arrange
    sample_predictions_factory(count=20, evaluated=True)

    # Act: Filter by from_date only
    from_date = date.today() - timedelta(days=9)
    response = await client.get(f"/api/predictions/history?from={from_date.isoformat()}")

    # Assert
    assert response.status_code == 200
    data = response.json()

    # Should return predictions from last 10 days (0-9 days ago)
    assert len(data) == 10

    # Verify all dates are >= from_date
    for item in data:
        prediction_date = date.fromisoformat(item["predicted_for"])
        assert prediction_date >= from_date


# Edge case: Filter by to_date only
@pytest.mark.asyncio
async def test_filter_to_date_only(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_factory,
):
    """
    Test filtering with only to_date parameter.
    Should return all predictions up to that date.
    """
    # Arrange
    sample_predictions_factory(count=20, evaluated=True)

    # Act: Filter by to_date only (10 days ago)
    to_date = date.today() - timedelta(days=10)
    response = await client.get(f"/api/predictions/history?to={to_date.isoformat()}")

    # Assert
    assert response.status_code == 200
    data = response.json()

    # Should return predictions older than 10 days
    assert len(data) == 10

    # Verify all dates are <= to_date
    for item in data:
        prediction_date = date.fromisoformat(item["predicted_for"])
        assert prediction_date <= to_date
