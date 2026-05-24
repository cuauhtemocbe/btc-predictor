"""
Shared test fixtures for workers.weekly tests.
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import numpy as np
import pytest
from shared.db.models import BtcPrice, Model, Prediction
from sqlalchemy.orm import Session

from workers.weekly.models import LinearRegressionModel

# Note: db_session is provided by root conftest.py
# Note: Database schema is created by autouse fixture in root conftest.py


@pytest.fixture
def synthetic_prices_60_days() -> np.ndarray:
    """
    Generate 60 days of synthetic BTC close prices.

    Returns a linear trend with small random noise to simulate
    realistic price movement for testing purposes.

    Returns:
        numpy array of shape (60,) with float64 values representing
        BTC close prices in USD.
    """
    # Start at $50,000, end around $51,500 (upward trend)
    base_prices = np.linspace(50000, 51500, 60)
    # Add random noise (+/- $500)
    np.random.seed(42)  # For reproducibility in tests
    noise = np.random.uniform(-500, 500, 60)
    prices = base_prices + noise
    return prices


@pytest.fixture
def sliding_window_data(
    synthetic_prices_60_days: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Generate sliding window features and labels from 60 days of prices.

    Uses a 30-day window to predict the next day's price.
    With 60 days of data, this creates 30 training samples.

    Args:
        synthetic_prices_60_days: 60 days of close prices

    Returns:
        Tuple (X, y) where:
        - X: Feature matrix of shape (30, 30) - 30 samples, 30 features each
        - y: Target vector of shape (30,) - next day's price for each sample
    """
    window_days = 30
    prices = synthetic_prices_60_days

    n_samples = len(prices) - window_days
    X = np.zeros((n_samples, window_days))
    y = np.zeros(n_samples)

    for i in range(n_samples):
        X[i] = prices[i : i + window_days]
        y[i] = prices[i + window_days]

    return X, y


@pytest.fixture
def sample_trained_model(
    db_session: Session, sliding_window_data: tuple[np.ndarray, np.ndarray]
) -> Model:
    """
    Create a trained LinearRegressionModel and save it to the database.

    Returns:
        Model record with is_active=True
    """
    X, y = sliding_window_data

    # Train model
    lr_model = LinearRegressionModel(window_days=30)
    lr_model.train(X, y)

    # Serialize and save to database
    model_record = Model(
        name="linear_v1",
        version="1.0.0",
        params={"window_days": 30},
        artifact=lr_model.serialize(),
        trained_at=datetime.now(UTC),
        train_from=date.today() - timedelta(days=60),
        train_to=date.today() - timedelta(days=1),
        is_active=True,
    )

    db_session.add(model_record)
    db_session.commit()
    db_session.refresh(model_record)

    return model_record


@pytest.fixture(scope="module")
def cached_daily_price_data_30_days():
    """Module-scoped cached hourly price data (30 days, 720 records)."""
    data = []
    base_time = datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=30)

    for day in range(30):
        close_price = 50000 + (day * 50)
        for hour in range(24):
            timestamp = base_time + timedelta(days=day, hours=hour)

            data.append(
                (
                    timestamp,
                    Decimal(str(close_price - 100)),  # open
                    Decimal(str(close_price + 200)),  # high
                    Decimal(str(close_price - 150)),  # low
                    Decimal(str(close_price)),  # close
                    Decimal("1000.5"),  # volume
                )
            )

    return data


@pytest.fixture
def sample_daily_close_prices_30_days(
    db_session: Session, cached_daily_price_data_30_days
) -> list[BtcPrice]:
    """
    Create 30 days of hourly prices using cached data.

    Returns:
        List of 720 BtcPrice records (30 days * 24 hours)
    """
    prices = []

    for timestamp, open_p, high, low, close, volume in cached_daily_price_data_30_days:
        price_record = BtcPrice(
            timestamp=timestamp,
            open=open_p,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source="test",
        )
        db_session.add(price_record)
        prices.append(price_record)

    db_session.commit()
    return prices


@pytest.fixture(scope="module")
def cached_daily_price_data_10_days():
    """Module-scoped cached hourly price data (10 days, 240 records)."""
    data = []
    base_time = datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=10)

    for day in range(10):
        close_price = 50000 + (day * 50)
        for hour in range(24):
            timestamp = base_time + timedelta(days=day, hours=hour)

            data.append(
                (
                    timestamp,
                    Decimal(str(close_price - 100)),
                    Decimal(str(close_price + 200)),
                    Decimal(str(close_price - 150)),
                    Decimal(str(close_price)),
                    Decimal("1000.5"),
                )
            )

    return data


@pytest.fixture
def sample_daily_close_prices_10_days(
    db_session: Session, cached_daily_price_data_10_days
) -> list[BtcPrice]:
    """
    Create 10 days of hourly prices using cached data (insufficient for 30-day window).

    Returns:
        List of 240 BtcPrice records (10 days * 24 hours)
    """
    prices = []

    for timestamp, open_p, high, low, close, volume in cached_daily_price_data_10_days:
        price_record = BtcPrice(
            timestamp=timestamp,
            open=open_p,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source="test",
        )
        db_session.add(price_record)
        prices.append(price_record)

    db_session.commit()
    return prices


@pytest.fixture
def sample_weekly_prediction_for_next_monday(
    db_session: Session, sample_trained_model: Model
) -> Prediction:
    """
    Create a weekly prediction record for next Monday (7 days ahead).

    Returns:
        Prediction record with timeframe='1w', predicted_for=7 days ahead
    """
    next_monday = date.today() + timedelta(days=7)

    prediction = Prediction(
        model_id=sample_trained_model.id,
        predicted_for=next_monday,
        timeframe="1w",
        predicted_at=datetime.now(UTC),
        price_at_prediction=Decimal("51000.00"),
        predicted_price=Decimal("51500.00"),
        actual_price=None,
        evaluated_at=None,
        error_abs=None,
        error_pct=None,
        direction_correct=None,
        pnl_simulated=None,
        pnl_long_short=None,
        pnl_threshold=None,
        pnl_realistic=None,
    )

    db_session.add(prediction)
    db_session.commit()
    db_session.refresh(prediction)

    return prediction


@pytest.fixture
def sample_unevaluated_weekly_prediction_for_today(
    db_session: Session, sample_trained_model: Model
) -> Prediction:
    """
    Create an unevaluated weekly prediction record for today.

    Returns:
        Prediction record with timeframe='1w', predicted_for=today, actual_price=NULL
    """
    today = date.today()

    prediction = Prediction(
        model_id=sample_trained_model.id,
        predicted_for=today,
        timeframe="1w",
        predicted_at=datetime.now(UTC) - timedelta(days=7),  # Made 7 days ago
        price_at_prediction=Decimal("66000.00"),
        predicted_price=Decimal("67000.00"),
        actual_price=None,
        evaluated_at=None,
        error_abs=None,
        error_pct=None,
        direction_correct=None,
        pnl_simulated=None,
        pnl_long_short=None,
        pnl_threshold=None,
        pnl_realistic=None,
    )

    db_session.add(prediction)
    db_session.commit()
    db_session.refresh(prediction)

    return prediction


@pytest.fixture
def sample_actual_price_for_today_7am(db_session: Session) -> BtcPrice:
    """
    Create today's 7am BTC price record.

    Returns:
        BtcPrice record with timestamp=today 7am
    """
    today = date.today()
    timestamp_7am = datetime.combine(today, time(7, 0), tzinfo=UTC)

    price_record = BtcPrice(
        timestamp=timestamp_7am,
        open=Decimal("67000.00"),
        high=Decimal("67800.00"),
        low=Decimal("66800.00"),
        close=Decimal("67500.00"),
        volume=Decimal("1500.0"),
        source="test",
    )

    db_session.add(price_record)
    db_session.commit()
    db_session.refresh(price_record)

    return price_record
