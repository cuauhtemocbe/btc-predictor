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
        sample_predictions_factory(count=5, evaluated=False, start_days_ago=30)
    """

    def _create_predictions(
        count: int = 10, evaluated: bool = True, start_days_ago: int = 0
    ):
        predictions = []
        base_date = date.today() - timedelta(days=start_days_ago)

        for i in range(count):
            predicted_for = base_date - timedelta(days=i)
            predicted_at = datetime.combine(
                predicted_for - timedelta(days=1), datetime.min.time(), tzinfo=UTC
            ).replace(hour=19)  # 7pm day before

            price_at_prediction = Decimal("67000.0") + Decimal(i * 100)
            predicted_price = Decimal("67500.0") + Decimal(i * 100)

            prediction = Prediction(
                model_id=sample_model.id,
                predicted_for=predicted_for,
                timeframe="1d",  # US-022: All predictions need timeframe
                predicted_at=predicted_at,
                price_at_prediction=price_at_prediction,
                predicted_price=predicted_price,
            )

            # Add evaluation fields if evaluated=True
            if evaluated:
                actual_price = Decimal("67800.0") + Decimal(i * 100)
                prediction.actual_price = actual_price
                prediction.evaluated_at = datetime.combine(
                    predicted_for, datetime.min.time(), tzinfo=UTC
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
    # Use different date ranges to avoid unique constraint violations
    sample_predictions_factory(count=30, evaluated=True)
    # Start unevaluated predictions 30 days earlier to avoid date collision
    sample_predictions_factory(count=5, evaluated=False, start_days_ago=30)

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
    # Use different date ranges to avoid unique constraint violations
    evaluated = sample_predictions_factory(count=20, evaluated=True)
    sample_predictions_factory(count=10, evaluated=False, start_days_ago=20)

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
            predicted_for - timedelta(days=1), datetime.min.time(), tzinfo=UTC
        ).replace(hour=19)

        price_at_prediction = Decimal("67000.0")
        predicted_price = Decimal("68000.0")  # Predicted UP
        actual_price = Decimal("66000.0")  # Actual DOWN → loss

        prediction = Prediction(
            model_id=sample_model.id,
            predicted_for=predicted_for,
            timeframe="1d",
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


# ============================================================================
# Tests for GET /api/predictions/strategies endpoint (US-018)
# ============================================================================


@pytest.fixture
def sample_predictions_with_pnl(db_session: Session, sample_model: Model):
    """Create sample predictions with all 4 PnL strategy values."""
    predictions = [
        Prediction(
            model_id=sample_model.id,
            predicted_for=date(2026, 5, 1),
            timeframe="1d",
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("50000"),
            predicted_price=Decimal("50000"),
            actual_price=Decimal("51000"),
            pnl_simulated=Decimal("100"),
            pnl_long_short=Decimal("100"),
            pnl_threshold=Decimal("100"),
            pnl_realistic=Decimal("95"),
        ),
        Prediction(
            model_id=sample_model.id,
            predicted_for=date(2026, 5, 2),
            timeframe="1d",
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("51000"),
            predicted_price=Decimal("51000"),
            actual_price=Decimal("50500"),
            pnl_simulated=Decimal("-50"),
            pnl_long_short=Decimal("-50"),
            pnl_threshold=Decimal("0"),  # Below threshold
            pnl_realistic=Decimal("-52.5"),
        ),
        Prediction(
            model_id=sample_model.id,
            predicted_for=date(2026, 5, 3),
            timeframe="1d",
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("50500"),
            predicted_price=Decimal("50500"),
            actual_price=Decimal("52000"),
            pnl_simulated=Decimal("200"),
            pnl_long_short=Decimal("200"),
            pnl_threshold=Decimal("200"),
            pnl_realistic=Decimal("190"),
        ),
        Prediction(
            model_id=sample_model.id,
            predicted_for=date(2026, 5, 4),
            timeframe="1d",
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("52000"),
            predicted_price=Decimal("52000"),
            actual_price=Decimal("51700"),
            pnl_simulated=Decimal("-30"),
            pnl_long_short=Decimal("-30"),
            pnl_threshold=Decimal("0"),  # Below threshold
            pnl_realistic=Decimal("-31.5"),
        ),
        Prediction(
            model_id=sample_model.id,
            predicted_for=date(2026, 5, 5),
            timeframe="1d",
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("51700"),
            predicted_price=Decimal("51700"),
            actual_price=Decimal("53000"),
            pnl_simulated=Decimal("150"),
            pnl_long_short=Decimal("150"),
            pnl_threshold=Decimal("150"),
            pnl_realistic=Decimal("142.5"),
        ),
    ]
    db_session.add_all(predictions)
    db_session.commit()
    for pred in predictions:
        db_session.refresh(pred)
    return predictions


# Gherkin Scenario 1: API endpoint returns strategy metrics as JSON
@pytest.mark.asyncio
async def test_get_strategies_endpoint(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_with_pnl,
):
    """
    Given the predictions table has 5 evaluated predictions with PnL values
    When I send GET /api/predictions/strategies
    Then the response status is 200 OK
    And the response has structure {"strategies": [...]}
    And each strategy has keys: name, display_name, color, total_pnl, win_rate,
                                max_drawdown, avg_win, avg_loss, sharpe_ratio,
                                trade_count, cumulative_pnl
    """
    # Act
    response = await client.get("/api/predictions/strategies")

    # Assert
    assert response.status_code == 200
    data = response.json()

    # Verify top-level structure
    assert "strategies" in data
    assert isinstance(data["strategies"], list)
    assert len(data["strategies"]) == 4  # 4 strategies

    # Verify each strategy has required fields
    for strategy in data["strategies"]:
        assert "name" in strategy
        assert "display_name" in strategy
        assert "color" in strategy
        assert "total_pnl" in strategy
        assert "win_rate" in strategy
        assert "max_drawdown" in strategy
        assert "avg_win" in strategy
        assert "avg_loss" in strategy
        assert "sharpe_ratio" in strategy
        assert "trade_count" in strategy
        assert "cumulative_pnl" in strategy
        assert isinstance(strategy["cumulative_pnl"], list)


# Gherkin Scenario 2: Calculate aggregate metrics for each strategy
@pytest.mark.asyncio
async def test_strategies_metrics_calculation(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_with_pnl,
):
    """
    Given predictions with pnl_long_short values: [100, -50, 200, -30, 150]
    When the backend calculates metrics for "Long/Short" strategy
    Then Total PnL = 370
    And Win Rate = 60% (3 wins out of 5 trades)
    And Max Drawdown = -50 (worst single loss)
    And Avg Win = 150 (mean of 100, 200, 150)
    And Avg Loss = -40 (mean of -50, -30)
    """
    # Act
    response = await client.get("/api/predictions/strategies")
    data = response.json()

    # Find Long/Short strategy
    long_short = next(s for s in data["strategies"] if s["name"] == "long_short")

    # Assert metrics
    assert long_short["total_pnl"] == 370.0
    assert long_short["win_rate"] == 0.6  # 60%
    assert long_short["max_drawdown"] == -50.0
    assert long_short["avg_win"] == 150.0  # (100 + 200 + 150) / 3
    assert long_short["avg_loss"] == -40.0  # (-50 + -30) / 2
    assert long_short["trade_count"] == 5
    assert long_short["sharpe_ratio"] != 0.0


# Gherkin Scenario 3: Cumulative PnL time series
@pytest.mark.asyncio
async def test_cumulative_pnl_chart_data(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_with_pnl,
):
    """
    When I fetch strategies endpoint
    Then cumulative_pnl is a list of objects with date and cumulative_pnl
    And values accumulate over time
    """
    # Act
    response = await client.get("/api/predictions/strategies")
    data = response.json()

    # Find Simple strategy
    simple = next(s for s in data["strategies"] if s["name"] == "simple")
    cumulative = simple["cumulative_pnl"]

    # Assert structure
    assert len(cumulative) == 5
    assert all("date" in point for point in cumulative)
    assert all("cumulative_pnl" in point for point in cumulative)

    # Assert accumulation (Simple: 100, -50, 200, -30, 150)
    assert cumulative[0]["cumulative_pnl"] == 100.0
    assert cumulative[1]["cumulative_pnl"] == 50.0  # 100 - 50
    assert cumulative[2]["cumulative_pnl"] == 250.0  # 50 + 200
    assert cumulative[3]["cumulative_pnl"] == 220.0  # 250 - 30
    assert cumulative[4]["cumulative_pnl"] == 370.0  # 220 + 150


# Gherkin Scenario 4: Handle strategies with zero trades (threshold with no signals)
@pytest.mark.asyncio
async def test_strategies_with_zero_trades(
    client: AsyncClient,
    db_session: Session,
):
    """
    Given there are no evaluated predictions
    When I fetch strategies endpoint
    Then all strategies return zero metrics
    And trade_count = 0
    """
    # Act (no predictions in database)
    response = await client.get("/api/predictions/strategies")
    data = response.json()

    # Assert
    assert len(data["strategies"]) == 4
    for strategy in data["strategies"]:
        assert strategy["total_pnl"] == 0.0
        assert strategy["win_rate"] == 0.0
        assert strategy["max_drawdown"] == 0.0
        assert strategy["avg_win"] == 0.0
        assert strategy["avg_loss"] == 0.0
        assert strategy["sharpe_ratio"] == 0.0
        assert strategy["trade_count"] == 0
        assert len(strategy["cumulative_pnl"]) == 0


# Gherkin Scenario 5: Verify all 4 strategies are returned
@pytest.mark.asyncio
async def test_all_four_strategies_returned(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_with_pnl,
):
    """
    When I fetch strategies endpoint
    Then I receive 4 strategies: Simple, Long/Short, Threshold, Realistic
    With correct color coding
    """
    # Act
    response = await client.get("/api/predictions/strategies")
    data = response.json()

    strategies = {s["name"]: s for s in data["strategies"]}

    # Assert all 4 strategies present
    assert "simple" in strategies
    assert "long_short" in strategies
    assert "threshold" in strategies
    assert "realistic" in strategies

    # Assert color coding
    assert strategies["simple"]["color"] == "blue"
    assert strategies["long_short"]["color"] == "green"
    assert strategies["threshold"]["color"] == "orange"
    assert strategies["realistic"]["color"] == "purple"

    # Assert display names
    assert strategies["simple"]["display_name"] == "Simple"
    assert strategies["long_short"]["display_name"] == "Long Short"
    assert strategies["threshold"]["display_name"] == "Threshold"
    assert strategies["realistic"]["display_name"] == "Realistic"


# ============================================================================
# US-022: Timeframe Filtering Tests
# ============================================================================


@pytest.fixture
def sample_predictions_with_timeframes(db_session: Session, sample_model: Model):
    """
    Create predictions with different timeframes (daily and weekly).

    Returns:
        Tuple of (daily_predictions, weekly_predictions)
    """
    daily_predictions = []
    weekly_predictions = []

    # Create 5 daily predictions
    for i in range(5):
        predicted_for = date.today() - timedelta(days=i)
        prediction = Prediction(
            model_id=sample_model.id,
            predicted_for=predicted_for,
            timeframe="1d",  # Daily
            predicted_at=datetime.now(UTC) - timedelta(days=i + 1),
            price_at_prediction=Decimal("67000") + Decimal(i * 100),
            predicted_price=Decimal("67500") + Decimal(i * 100),
            actual_price=Decimal("67800") + Decimal(i * 100),
            evaluated_at=datetime.now(UTC) - timedelta(days=i),
            error_abs=Decimal("300"),
            error_pct=Decimal("0.44"),
            direction_correct=True,
            pnl_simulated=Decimal("1200"),
            pnl_long_short=Decimal("1200"),
            pnl_threshold=Decimal("1200"),
            pnl_realistic=Decimal("1140"),
        )
        db_session.add(prediction)
        daily_predictions.append(prediction)

    # Create 3 weekly predictions
    for i in range(3):
        predicted_for = date.today() - timedelta(days=i * 7)
        prediction = Prediction(
            model_id=sample_model.id,
            predicted_for=predicted_for,
            timeframe="1w",  # Weekly
            predicted_at=datetime.now(UTC) - timedelta(days=i * 7 + 7),
            price_at_prediction=Decimal("65000") + Decimal(i * 200),
            predicted_price=Decimal("66000") + Decimal(i * 200),
            actual_price=Decimal("66500") + Decimal(i * 200),
            evaluated_at=datetime.now(UTC) - timedelta(days=i * 7),
            error_abs=Decimal("500"),
            error_pct=Decimal("0.75"),
            direction_correct=True,
            pnl_simulated=Decimal("2000"),
            pnl_long_short=Decimal("2000"),
            pnl_threshold=Decimal("2000"),
            pnl_realistic=Decimal("1900"),
        )
        db_session.add(prediction)
        weekly_predictions.append(prediction)

    db_session.commit()
    for pred in daily_predictions + weekly_predictions:
        db_session.refresh(pred)

    return daily_predictions, weekly_predictions


# Gherkin Scenario: API endpoint filters predictions by timeframe
@pytest.mark.asyncio
async def test_filter_predictions_by_timeframe_1w(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_with_timeframes,
):
    """
    Gherkin: Filter predictions by timeframe=1w.

    Given the predictions table has 5 daily and 3 weekly predictions
    When I send GET /api/predictions/history?timeframe=1w
    Then I receive only weekly predictions (3 records)
    And all returned predictions have timeframe = '1w'
    """
    daily_preds, weekly_preds = sample_predictions_with_timeframes

    # Act
    response = await client.get("/api/predictions/history?timeframe=1w")

    # Assert
    assert response.status_code == 200
    predictions = response.json()
    assert isinstance(predictions, list)
    assert len(predictions) == 3  # Only weekly predictions

    # Verify all are weekly
    for pred in predictions:
        assert pred["timeframe"] == "1w"


# Gherkin Scenario: API endpoint filters predictions by timeframe
@pytest.mark.asyncio
async def test_filter_predictions_by_timeframe_1d(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_with_timeframes,
):
    """
    Gherkin: Filter predictions by timeframe=1d.

    Given the predictions table has 5 daily and 3 weekly predictions
    When I send GET /api/predictions/history?timeframe=1d
    Then I receive only daily predictions (5 records)
    And all returned predictions have timeframe = '1d'
    """
    daily_preds, weekly_preds = sample_predictions_with_timeframes

    # Act
    response = await client.get("/api/predictions/history?timeframe=1d")

    # Assert
    assert response.status_code == 200
    predictions = response.json()
    assert isinstance(predictions, list)
    assert len(predictions) == 5  # Only daily predictions

    # Verify all are daily
    for pred in predictions:
        assert pred["timeframe"] == "1d"


# Gherkin Scenario: API endpoint returns all predictions when no timeframe filter
@pytest.mark.asyncio
async def test_no_timeframe_filter_returns_all(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_with_timeframes,
):
    """
    Gherkin: No timeframe filter returns all predictions.

    Given the predictions table has 5 daily and 3 weekly predictions
    When I send GET /api/predictions/history (no timeframe param)
    Then I receive all 8 predictions
    And they include both daily and weekly timeframes
    """
    daily_preds, weekly_preds = sample_predictions_with_timeframes

    # Act
    response = await client.get("/api/predictions/history")

    # Assert
    assert response.status_code == 200
    predictions = response.json()
    assert isinstance(predictions, list)
    assert len(predictions) == 8  # All predictions (5 + 3)

    # Verify both timeframes present
    timeframes = {pred["timeframe"] for pred in predictions}
    assert "1d" in timeframes
    assert "1w" in timeframes


# Gherkin Scenario: Combine timeframe filter with date range
@pytest.mark.asyncio
async def test_timeframe_filter_with_date_range(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_with_timeframes,
):
    """
    Gherkin: Combine timeframe filter with date range.

    Given the predictions table has multiple daily and weekly predictions
    When I send GET /api/predictions/history?timeframe=1w&from=<date>&to=<date>
    Then I receive only weekly predictions within the date range
    """
    daily_preds, weekly_preds = sample_predictions_with_timeframes

    # Get the middle weekly prediction's date
    middle_pred = weekly_preds[1]
    from_date = (middle_pred.predicted_for - timedelta(days=1)).isoformat()
    to_date = (middle_pred.predicted_for + timedelta(days=1)).isoformat()

    # Act
    response = await client.get(
        f"/api/predictions/history?timeframe=1w&from={from_date}&to={to_date}"
    )

    # Assert
    assert response.status_code == 200
    predictions = response.json()
    assert isinstance(predictions, list)

    # Should return at least the middle prediction
    assert len(predictions) >= 1

    # Verify all are weekly and within date range
    for pred in predictions:
        assert pred["timeframe"] == "1w"
        pred_date = date.fromisoformat(pred["predicted_for"])
        assert date.fromisoformat(from_date) <= pred_date <= date.fromisoformat(to_date)


# ============================================================================
# Gherkin scenarios: /pnl and /strategies respect timeframe (issue #67)
# ============================================================================


@pytest.mark.asyncio
async def test_total_pnl_does_not_mix_timeframes(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_with_timeframes,
):
    """
    Scenario: Total PnL does not mix timeframes

    Given a model has daily and weekly PnL records
    When total PnL is requested for one timeframe
    Then the returned value contains only records from that timeframe
    """
    # 5 daily predictions x $1200 = $6000
    response_daily = await client.get("/api/predictions/pnl?timeframe=1d")
    assert response_daily.status_code == 200
    assert response_daily.json()["total_pnl"] == 6000.0
    assert response_daily.json()["evaluated_predictions"] == 5

    # 3 weekly predictions x $2000 = $6000
    response_weekly = await client.get("/api/predictions/pnl?timeframe=1w")
    assert response_weekly.status_code == 200
    assert response_weekly.json()["total_pnl"] == 6000.0
    assert response_weekly.json()["evaluated_predictions"] == 3


@pytest.mark.asyncio
async def test_total_pnl_missing_timeframe_applies_default(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_with_timeframes,
):
    """
    Scenario: Missing timeframe applies the documented default

    Given a metrics request does not specify a timeframe
    When the request is processed
    Then the API applies DEFAULT_TIMEFRAME ("1d")
    And it does not silently combine daily and weekly predictions
    """
    response = await client.get("/api/predictions/pnl")

    assert response.status_code == 200
    # Same result as explicitly requesting timeframe=1d, NOT 6000+6000=12000
    assert response.json()["total_pnl"] == 6000.0
    assert response.json()["evaluated_predictions"] == 5


@pytest.mark.asyncio
async def test_total_pnl_invalid_timeframe_is_rejected(client: AsyncClient) -> None:
    """
    Scenario: Invalid timeframe is rejected

    Given a client requests /pnl with an unsupported timeframe value
    When the endpoint processes the request
    Then it returns a validation error
    """
    response = await client.get("/api/predictions/pnl?timeframe=1y")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_strategies_does_not_mix_timeframes(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_with_timeframes,
):
    """
    Given a model has daily and weekly PnL records
    When strategy metrics are requested for one timeframe
    Then trade_count reflects only that timeframe
    """
    response_daily = await client.get("/api/predictions/strategies?timeframe=1d")
    assert response_daily.status_code == 200
    simple_daily = next(
        s for s in response_daily.json()["strategies"] if s["name"] == "simple"
    )
    assert simple_daily["trade_count"] == 5

    response_weekly = await client.get("/api/predictions/strategies?timeframe=1w")
    assert response_weekly.status_code == 200
    simple_weekly = next(
        s for s in response_weekly.json()["strategies"] if s["name"] == "simple"
    )
    assert simple_weekly["trade_count"] == 3


@pytest.mark.asyncio
async def test_strategies_invalid_timeframe_is_rejected(client: AsyncClient) -> None:
    """Scenario: Invalid timeframe is rejected, for /strategies too."""
    response = await client.get("/api/predictions/strategies?timeframe=bogus")

    assert response.status_code == 422
