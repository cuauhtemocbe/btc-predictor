"""
Shared test fixtures for workers.daily tests.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
from sqlalchemy.orm import Session

from shared.db.models import BtcPrice, Model, Prediction
from workers.daily.models import LinearRegressionModel, LSTMModel, XGBoostModel


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
# Note: db_session is provided by root conftest.py
# Note: Database schema is created by autouse fixture in root conftest.py

# ============================================================================
# Module-scoped CACHED artifacts (trained once, reused across tests)
# ============================================================================
# These fixtures cache the TRAINED MODEL ARTIFACTS (serialized bytes) in memory.
# Training happens ONCE per module, but each test gets a fresh DB record.


@pytest.fixture(scope="module")
def cached_linear_artifact() -> bytes:
    """
    Module-scoped cached LinearRegression model artifact.

    Trains the model ONCE and caches the serialized bytes.
    Tests use this to create fresh DB records without re-training.
    """
    # Generate training data (same as sliding_window_data fixture)
    base_prices = np.linspace(50000, 51500, 60)
    noise = np.random.uniform(-500, 500, 60)
    prices = base_prices + noise

    window_days = 30
    n_samples = len(prices) - window_days
    X = np.zeros((n_samples, window_days))
    y = np.zeros(n_samples)

    for i in range(n_samples):
        X[i] = prices[i : i + window_days]
        y[i] = prices[i + window_days]

    # Train model ONCE
    lr_model = LinearRegressionModel(window_days=30)
    lr_model.train(X, y)

    # Return serialized bytes (cached for all tests in this module)
    return lr_model.serialize()


@pytest.fixture(scope="module")
def cached_xgboost_artifact() -> bytes:
    """
    Module-scoped cached XGBoost model artifact.

    Trains the model ONCE and caches the serialized bytes.
    Tests use this to create fresh DB records without re-training.
    """
    # Generate training data (same as sliding_window_data fixture)
    base_prices = np.linspace(50000, 51500, 60)
    noise = np.random.uniform(-500, 500, 60)
    prices = base_prices + noise

    window_days = 30
    n_samples = len(prices) - window_days
    X = np.zeros((n_samples, window_days))
    y = np.zeros(n_samples)

    for i in range(n_samples):
        X[i] = prices[i : i + window_days]
        y[i] = prices[i + window_days]

    # Train model ONCE
    xgb_model = XGBoostModel(window_days=30)
    xgb_model.train(X, y)

    # Return serialized bytes (cached for all tests in this module)
    return xgb_model.serialize()


@pytest.fixture(scope="module")
def cached_lstm_artifact() -> bytes:
    """
    Module-scoped cached LSTM model artifact.

    Trains the model ONCE and caches the serialized bytes.
    Tests use this to create fresh DB records without re-training.
    """
    # Generate training data (same as sliding_window_data fixture)
    base_prices = np.linspace(50000, 51500, 60)
    noise = np.random.uniform(-500, 500, 60)
    prices = base_prices + noise

    window_days = 30
    n_samples = len(prices) - window_days
    X = np.zeros((n_samples, window_days))
    y = np.zeros(n_samples)

    for i in range(n_samples):
        X[i] = prices[i : i + window_days]
        y[i] = prices[i + window_days]

    # Train model ONCE
    lstm_model = LSTMModel(window_days=30, epochs=10)
    lstm_model.train(X, y)

    # Return serialized bytes (cached for all tests in this module)
    return lstm_model.serialize()


# ============================================================================
# Function-scoped model fixtures (use cached artifacts)
# ============================================================================


@pytest.fixture
def sample_trained_model(db_session: Session, cached_linear_artifact: bytes) -> Model:
    """
    Function-scoped LinearRegressionModel using cached artifact.

    Uses pre-trained model artifact (cached at module scope) to avoid
    redundant training. Each test gets a fresh DB record.

    Returns:
        Model record with is_active=True
    """
    # Use cached artifact (NO re-training!)
    model_record = Model(
        name="linear_v1",
        version="1.0.0",
        params={"window_days": 30},
        artifact=cached_linear_artifact,  # Use cached bytes
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
def sample_xgboost_model(db_session: Session, cached_xgboost_artifact: bytes) -> Model:
    """
    Function-scoped XGBoostModel using cached artifact.

    Uses pre-trained model artifact (cached at module scope) to avoid
    redundant training. Each test gets a fresh DB record.

    Returns:
        Model record with is_active=False (default for multi-model tests)
    """
    # Use cached artifact (NO re-training!)
    model_record = Model(
        name="xgboost_v1",
        version="1.0.0",
        params={"window_days": 30, "n_estimators": 100, "learning_rate": 0.1},
        artifact=cached_xgboost_artifact,  # Use cached bytes
        trained_at=datetime.now(UTC),
        train_from=date.today() - timedelta(days=60),
        train_to=date.today() - timedelta(days=1),
        is_active=False,  # Inactive by default (tests will activate as needed)
    )

    db_session.add(model_record)
    db_session.commit()
    db_session.refresh(model_record)

    return model_record


@pytest.fixture(scope="module")
def cached_price_data_30_days():
    """
    Module-scoped cached price data (pre-calculated values).

    Returns list of tuples: (timestamp, open, high, low, close, volume)
    Generated ONCE per module, reused by all tests.
    """
    data = []
    today = datetime.now(UTC).date()
    base_date = today - timedelta(days=30)

    for i in range(30):
        current_date = base_date + timedelta(days=i)
        base_close = 50000 + (i * 50)

        for interval in range(6):
            timestamp = datetime.combine(current_date, datetime.min.time()).replace(
                tzinfo=UTC
            ) + timedelta(hours=interval * 4)
            close_price = base_close + (interval * 10)

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
def sample_btc_prices_30_days(
    db_session: Session, cached_price_data_30_days
) -> list[BtcPrice]:
    """
    Create 30 days of BTC price records using cached data.

    Uses pre-calculated price data to avoid redundant computations.

    Returns:
        List of 180 BtcPrice records (6 per day at 4-hour intervals)
    """
    prices = []

    for timestamp, open_price, high, low, close, volume in cached_price_data_30_days:
        price_record = BtcPrice(
            timestamp=timestamp,
            open=open_price,
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
def cached_price_data_10_days():
    """
    Module-scoped cached price data for 10 days.

    Returns list of tuples: (timestamp, open, high, low, close, volume)
    Generated ONCE per module, reused by all tests.
    """
    data = []
    today = datetime.now(UTC).date()
    base_date = today - timedelta(days=10)

    for i in range(10):
        current_date = base_date + timedelta(days=i)
        base_close = 50000 + (i * 50)

        for interval in range(6):
            timestamp = datetime.combine(current_date, datetime.min.time()).replace(
                tzinfo=UTC
            ) + timedelta(hours=interval * 4)
            close_price = base_close + (interval * 10)

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
def sample_btc_prices_10_days(
    db_session: Session, cached_price_data_10_days
) -> list[BtcPrice]:
    """
    Create 10 days of BTC price records using cached data.
    Insufficient for 30-day window.

    Returns:
        List of 60 BtcPrice records (6 per day at 4-hour intervals)
    """
    prices = []

    for timestamp, open_price, high, low, close, volume in cached_price_data_10_days:
        price_record = BtcPrice(
            timestamp=timestamp,
            open=open_price,
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
    timestamp_7am = datetime.combine(
        today, datetime.min.time().replace(hour=7), tzinfo=UTC
    )

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
