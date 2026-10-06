"""
Shared test fixtures for workers.weekly tests.
"""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import numpy as np
import pytest
from sqlalchemy.orm import Session

from shared.db.models import Model, Prediction, Price
from shared.features import LOG_RETURN_TARGET, build_training_set, feature_count
from shared.utils import utc_today
from workers.weekly.models import LinearRegressionModel

# One cached bar: (timestamp, open, high, low, close, volume).
type BarRow = tuple[datetime, Decimal, Decimal, Decimal, Decimal, Decimal]

# Note: db_session is provided by root conftest.py
# Note: Database schema is created by autouse fixture in root conftest.py


@pytest.fixture
def sample_trained_model(db_session: Session) -> Model:
    """
    Create a LinearRegressionModel trained on 7-day log returns and save it.

    Returns:
        Model record with is_active=True
    """
    rng = np.random.default_rng(42)
    closes = 50000 * np.exp(np.cumsum(rng.normal(0, 0.02, 120)))
    volumes = 1000 * np.exp(rng.normal(0, 0.1, 120))

    window_days = 30
    training_set = build_training_set(closes, volumes, window_days, horizon_days=7)

    lr_model = LinearRegressionModel(
        window_days=window_days, n_features=feature_count(window_days)
    )
    lr_model.train(training_set.X, training_set.y)

    # Serialize and save to database
    model_record = Model(
        name="linear_weekly_v1",
        version="1.0.0",
        params={
            "window_days": 30,
            "horizon_days": 7,
            "target": LOG_RETURN_TARGET,
        },
        artifact=lr_model.serialize(),
        trained_at=datetime.now(UTC),
        train_from=utc_today() - timedelta(days=60),
        train_to=utc_today() - timedelta(days=1),
        timeframe="1w",
        is_active=True,
    )

    db_session.add(model_record)
    db_session.commit()
    db_session.refresh(model_record)

    return model_record


@pytest.fixture(scope="module")
def cached_daily_price_data_31_days() -> list[BarRow]:
    """Module-scoped cached hourly price data (31 days, 744 records)."""
    data: list[BarRow] = []
    base_time = datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=31)

    for day in range(31):
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
def sample_daily_close_prices_31_days(
    db_session: Session, cached_daily_price_data_31_days: list[BarRow]
) -> list[Price]:
    """
    Create 31 days of hourly prices using cached data.

    31 daily closes give the 30 daily returns a 30-day window needs.

    Returns:
        List of 744 Price records (31 days * 24 hours)
    """
    prices = []

    for timestamp, open_p, high, low, close, volume in cached_daily_price_data_31_days:
        price_record = Price(
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
def cached_daily_price_data_10_days() -> list[BarRow]:
    """Module-scoped cached hourly price data (10 days, 240 records)."""
    data: list[BarRow] = []
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
    db_session: Session, cached_daily_price_data_10_days: list[BarRow]
) -> list[Price]:
    """
    Create 10 days of hourly prices using cached data (insufficient for 30-day window).

    Returns:
        List of 240 Price records (10 days * 24 hours)
    """
    prices = []

    for timestamp, open_p, high, low, close, volume in cached_daily_price_data_10_days:
        price_record = Price(
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
    next_monday = utc_today() + timedelta(days=7)

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
    today = utc_today()

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
def sample_actual_price_for_today(db_session: Session) -> Price:
    """
    Create the daily bar that settles a weekly prediction made for today.

    Daily bars are stored at their 00:00 UTC open, and a prediction for today
    is settled by the bar opened yesterday (it closes at 00:00 UTC today).

    Returns:
        Price record with timestamp=yesterday 00:00 UTC, close=67500.00
    """
    bar_open = datetime.combine(utc_today() - timedelta(days=1), time(0, 0), tzinfo=UTC)

    price_record = Price(
        timestamp=bar_open,
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
