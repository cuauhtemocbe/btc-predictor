"""
Shared test fixtures for workers.daily tests.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
from shared.db.models import Base, BtcPrice, Model, Prediction
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from workers.daily.models import LinearRegressionModel


@pytest.fixture
def synthetic_prices_60_days() -> np.ndarray:
    """
    Generate 60 days of synthetic BTC close prices.

    Returns a linear trend with small random noise to simulate
    realistic price movement for testing purposes.

    Returns:
        numpy array of shape (60,) with float64 values representing
        BTC close prices in USD.

    Example:
        >>> prices = synthetic_prices_60_days()
        >>> assert prices.shape == (60,)
        >>> assert all(price > 0 for price in prices)
    """
    # Start at $50,000, end around $51,500 (upward trend)
    base_prices = np.linspace(50000, 51500, 60)
    # Add random noise (+/- $500)
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
    With 60 days of data, this creates 30 training samples:
    - Sample 1: days 1-30 → predict day 31
    - Sample 2: days 2-31 → predict day 32
    - ...
    - Sample 30: days 30-59 → predict day 60

    Args:
        synthetic_prices_60_days: 60 days of close prices

    Returns:
        Tuple (X, y) where:
        - X: Feature matrix of shape (30, 30) - 30 samples, 30 features each
        - y: Target vector of shape (30,) - next day's price for each sample

    Example:
        >>> X, y = sliding_window_data(synthetic_prices_60_days)
        >>> assert X.shape == (30, 30)
        >>> assert y.shape == (30,)
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
def last_30_days(synthetic_prices_60_days: np.ndarray) -> np.ndarray:
    """
    Get the last 30 days of prices for making a single prediction.

    This fixture is used to test the predict() method.

    Args:
        synthetic_prices_60_days: 60 days of close prices

    Returns:
        numpy array of shape (1, 30) - last 30 close prices

    Example:
        >>> X_new = last_30_days(synthetic_prices_60_days)
        >>> assert X_new.shape == (1, 30)
    """
    return synthetic_prices_60_days[-30:].reshape(1, -1)


# ============================================================================
# Predictor test fixtures
# ============================================================================


@pytest.fixture
def db_session() -> Session:
    """
    Create a test database session with automatic cleanup.

    Uses in-memory SQLite database for fast, isolated tests.
    All changes are rolled back after each test.
    """
    # Create in-memory SQLite database
    engine = create_engine("sqlite:///:memory:")

    # Create all tables
    Base.metadata.create_all(engine)

    # Create session
    TestSessionLocal = sessionmaker(bind=engine)
    session = TestSessionLocal()

    yield session

    # Cleanup
    session.rollback()
    session.close()
    engine.dispose()


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


@pytest.fixture
def sample_btc_prices_30_days(db_session: Session) -> list[BtcPrice]:
    """
    Create 30 days of BTC price records in the database.

    Returns:
        List of 30 BtcPrice records
    """
    prices = []
    base_time = datetime.now(UTC) - timedelta(days=30)

    for i in range(30):
        timestamp = base_time + timedelta(days=i)
        # Prices range from $50,000 to $51,500
        close_price = Decimal("50000") + Decimal(str(i * 50))

        price_record = BtcPrice(
            timestamp=timestamp,
            open=close_price - Decimal("100"),
            high=close_price + Decimal("200"),
            low=close_price - Decimal("150"),
            close=close_price,
            volume=Decimal("1000.5"),
            source="test",
        )

        db_session.add(price_record)
        prices.append(price_record)

    db_session.commit()

    return prices


@pytest.fixture
def sample_btc_prices_10_days(db_session: Session) -> list[BtcPrice]:
    """
    Create only 10 days of BTC price records (insufficient for 30-day window).

    Returns:
        List of 10 BtcPrice records
    """
    prices = []
    base_time = datetime.now(UTC) - timedelta(days=10)

    for i in range(10):
        timestamp = base_time + timedelta(days=i)
        close_price = Decimal("50000") + Decimal(str(i * 50))

        price_record = BtcPrice(
            timestamp=timestamp,
            open=close_price - Decimal("100"),
            high=close_price + Decimal("200"),
            low=close_price - Decimal("150"),
            close=close_price,
            volume=Decimal("1000.5"),
            source="test",
        )

        db_session.add(price_record)
        prices.append(price_record)

    db_session.commit()

    return prices


@pytest.fixture
def sample_prediction_for_tomorrow(
    db_session: Session, sample_trained_model: Model
) -> Prediction:
    """
    Create a prediction record for tomorrow (to test idempotency).

    Returns:
        Prediction record with predicted_for=tomorrow
    """
    tomorrow = date.today() + timedelta(days=1)

    prediction = Prediction(
        model_id=sample_trained_model.id,
        predicted_for=tomorrow,
        predicted_at=datetime.now(UTC),
        price_at_prediction=Decimal("51000.00"),
        predicted_price=Decimal("51500.00"),
        actual_price=None,
        evaluated_at=None,
        error_abs=None,
        error_pct=None,
        direction_correct=None,
        pnl_simulated=None,
    )

    db_session.add(prediction)
    db_session.commit()
    db_session.refresh(prediction)

    return prediction


# ============================================================================
# Evaluator test fixtures
# ============================================================================


@pytest.fixture
def sample_unevaluated_prediction_for_today(
    db_session: Session, sample_trained_model: Model
) -> Prediction:
    """
    Create an unevaluated prediction record for today.

    Returns:
        Prediction record with predicted_for=today, actual_price=NULL
    """
    today = date.today()

    prediction = Prediction(
        model_id=sample_trained_model.id,
        predicted_for=today,
        predicted_at=datetime.now(UTC) - timedelta(days=1),  # Made yesterday
        price_at_prediction=Decimal("66000.00"),
        predicted_price=Decimal("67000.00"),
        actual_price=None,
        evaluated_at=None,
        error_abs=None,
        error_pct=None,
        direction_correct=None,
        pnl_simulated=None,
    )

    db_session.add(prediction)
    db_session.commit()
    db_session.refresh(prediction)

    return prediction


@pytest.fixture
def sample_actual_price_for_today(db_session: Session) -> BtcPrice:
    """
    Create today's 7am BTC price record.

    Returns:
        BtcPrice record with timestamp=today 7am
    """
    today = date.today()
    timestamp_7am = datetime.combine(today, datetime.min.time().replace(hour=7), tzinfo=UTC)

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


@pytest.fixture
def sample_evaluated_prediction_for_today(
    db_session: Session, sample_trained_model: Model
) -> Prediction:
    """
    Create an already-evaluated prediction record for today.

    Returns:
        Prediction record with actual_price != NULL (already evaluated)
    """
    today = date.today()

    prediction = Prediction(
        model_id=sample_trained_model.id,
        predicted_for=today,
        predicted_at=datetime.now(UTC) - timedelta(days=1),
        price_at_prediction=Decimal("66000.00"),
        predicted_price=Decimal("67000.00"),
        actual_price=Decimal("67500.00"),
        evaluated_at=datetime.now(UTC),
        error_abs=Decimal("500.00"),
        error_pct=Decimal("0.74"),
        direction_correct=True,
        pnl_simulated=Decimal("1500.00"),
    )

    db_session.add(prediction)
    db_session.commit()
    db_session.refresh(prediction)

    return prediction
