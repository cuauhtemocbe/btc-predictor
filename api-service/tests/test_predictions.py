"""
Integration tests for predictions API endpoints.

Tests the /api/predictions/history endpoint with various scenarios:
- Fetching all evaluated predictions
- Empty result when no evaluated predictions
- Date range filtering
"""

import pickle
from datetime import UTC, date, datetime, timedelta
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
    import numpy as np
    from sklearn.linear_model import LinearRegression

    dummy_model = LinearRegression()
    dummy_model.fit(np.array([[1], [2], [3]]), np.array([1, 2, 3]))
    artifact = pickle.dumps(dummy_model)

    model = Model(
        name="linear_v1",
        version="1.0.0",
        params={"window_days": 30},
        artifact=artifact,
        trained_at=datetime.now(UTC),
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
                tzinfo=UTC
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
                    tzinfo=UTC
                ).replace(hour=7, minute=1)  # 7:01am on prediction day
                prediction.error_abs = abs(actual_price - predicted_price)
                prediction.error_pct = (
                    abs(actual_price - predicted_price) / actual_price * 100
                )
                # Direction correctness
                pred_up = predicted_price > price_at_prediction
                pred_down = predicted_price < price_at_prediction
                actual_up = actual_price > price_at_prediction
                actual_down = actual_price < price_at_prediction
                prediction.direction_correct = (
                    (pred_up and actual_up)
                    or (pred_down and actual_down)
                    or (
                        predicted_price == price_at_prediction
                        and actual_price == price_at_prediction
                    )
                )
                # Simple PnL calculation
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
    Test filtering predictions by date range.

    Given predictions spanning multiple days
    When I filter by from and to dates
    Then only predictions within that range are returned
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
    url = f"/api/predictions/history?from={from_date.isoformat()}"
    response = await client.get(url)

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


# ============================================================================
# Tests for GET /api/predictions/pnl endpoint (US-014)
# ============================================================================


# Gherkin Scenario 1: Calculate total PnL
@pytest.mark.asyncio
async def test_get_total_pnl_with_evaluated_predictions(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_factory,
):
    """
    Given the predictions table has 30 evaluated records
    And the sum of pnl_simulated is 12345.67
    When I send GET /api/predictions/pnl
    Then the response status is 200 OK
    And the response body is {"total_pnl": 12345.67, "evaluated_predictions": 30}
    """
    # Arrange: Create 30 evaluated predictions
    predictions = sample_predictions_factory(count=30, evaluated=True)

    # Calculate expected total PnL (predictions have pnl_simulated already set)
    expected_pnl = sum(float(p.pnl_simulated) for p in predictions)
    expected_count = 30

    # Act: Fetch total PnL
    response = await client.get("/api/predictions/pnl")

    # Assert
    assert response.status_code == 200
    data = response.json()

    # Verify response structure
    assert "total_pnl" in data
    assert "evaluated_predictions" in data

    # Verify values
    assert data["evaluated_predictions"] == expected_count
    # Use approximate comparison for floating-point
    assert abs(data["total_pnl"] - expected_pnl) < 0.01


# Gherkin Scenario 2: No evaluated predictions yet
@pytest.mark.asyncio
async def test_get_total_pnl_no_evaluated_predictions(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_factory,
):
    """
    Given all predictions have pnl_simulated = NULL
    When I send GET /api/predictions/pnl
    Then the response body is {"total_pnl": 0, "evaluated_predictions": 0}
    """
    # Arrange: Create only unevaluated predictions (pnl_simulated is NULL)
    sample_predictions_factory(count=5, evaluated=False)

    # Act
    response = await client.get("/api/predictions/pnl")

    # Assert
    assert response.status_code == 200
    data = response.json()

    assert data["total_pnl"] == 0.0
    assert data["evaluated_predictions"] == 0


# Edge case: Mix of evaluated and unevaluated predictions
@pytest.mark.asyncio
async def test_get_total_pnl_mixed_predictions(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_factory,
):
    """
    Test that PnL endpoint only counts evaluated predictions and ignores unevaluated.
    """
    # Arrange: Create 20 evaluated + 10 unevaluated predictions
    evaluated = sample_predictions_factory(count=20, evaluated=True)
    sample_predictions_factory(count=10, evaluated=False)

    # Calculate expected PnL (only from evaluated predictions)
    expected_pnl = sum(float(p.pnl_simulated) for p in evaluated)
    expected_count = 20

    # Act
    response = await client.get("/api/predictions/pnl")

    # Assert
    assert response.status_code == 200
    data = response.json()

    assert data["evaluated_predictions"] == expected_count
    assert abs(data["total_pnl"] - expected_pnl) < 0.01


# Edge case: Negative total PnL (losses)
@pytest.mark.asyncio
async def test_get_total_pnl_with_losses(
    client: AsyncClient,
    db_session: Session,
    sample_model: Model,
):
    """
    Test that PnL endpoint correctly handles negative total PnL.
    """
    # Arrange: Create predictions with negative PnL (predicted up but actual down)
    predictions = []
    for i in range(5):
        predicted_for = date.today() - timedelta(days=i)
        predicted_at = datetime.combine(
            predicted_for - timedelta(days=1),
            datetime.min.time(),
            tzinfo=UTC
        ).replace(hour=19)

        price_at_prediction = Decimal("67000.0")
        predicted_price = Decimal("68000.0")  # Predicted UP
        actual_price = Decimal("66000.0")  # Actual DOWN → loss

        prediction = Prediction(
            model_id=sample_model.id,
            predicted_for=predicted_for,
            predicted_at=predicted_at,
            price_at_prediction=price_at_prediction,
            predicted_price=predicted_price,
            actual_price=actual_price,
            evaluated_at=datetime.now(UTC),
            error_abs=Decimal("2000.0"),
            error_pct=Decimal("3.03"),
            direction_correct=False,
            pnl_simulated=Decimal("-1000.0"),  # Loss: 66000 - 67000 = -1000
        )
        db_session.add(prediction)
        predictions.append(prediction)

    db_session.commit()

    # Expected: 5 predictions × -1000 = -5000 total PnL
    expected_pnl = -5000.0
    expected_count = 5

    # Act
    response = await client.get("/api/predictions/pnl")

    # Assert
    assert response.status_code == 200
    data = response.json()

    assert data["evaluated_predictions"] == expected_count
    assert abs(data["total_pnl"] - expected_pnl) < 0.01
