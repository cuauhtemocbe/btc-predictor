"""
Pytest configuration and fixtures for API service tests.
"""

import pickle
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from api.main import app
from shared.db.database import get_db
from shared.db.models import BtcPrice, Model, Prediction

# Note: db_engine_session is provided by root conftest.py (session-scoped)
# Note: Database schema is created by autouse fixture in root conftest.py


@pytest.fixture
async def client():
    """
    Async HTTP client for testing FastAPI endpoints.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture(scope="function")
def db_session(db_session):
    """
    Extends the root conftest.py db_session fixture (SAVEPOINT-based
    isolation, with pre-test table cleanup) by also overriding FastAPI's
    get_db dependency so API requests made through `client` are routed
    through this same test session/transaction.
    """

    def override_get_db():
        try:
            yield db_session
        finally:
            pass  # Don't close here, the root fixture's teardown handles it

    app.dependency_overrides[get_db] = override_get_db

    yield db_session

    app.dependency_overrides.clear()


@pytest.fixture
def sample_prices(db_session):
    """
    Factory fixture for creating multiple sample BtcPrice records.
    Automatically cleans up after test (via db_session rollback).

    Usage:
        sample_prices(10)  # Creates 10 records with default values
        sample_prices(5, base_price=40000)  # Creates 5 records with custom base price
    """

    def _create_prices(
        count: int = 10,
        base_price: float = 42000.0,
        base_time: datetime = None,
        source: str = "test",
    ) -> list[BtcPrice]:
        if base_time is None:
            base_time = datetime.now(UTC)

        prices = []
        for i in range(count):
            price = BtcPrice(
                timestamp=base_time - timedelta(hours=i),
                open=Decimal(str(base_price + i * 100)),
                high=Decimal(str(base_price + i * 100 + 200)),
                low=Decimal(str(base_price + i * 100 - 200)),
                close=Decimal(str(base_price + i * 100 + 50)),
                volume=Decimal("1250.50"),
                source=source,
            )
            db_session.add(price)
            prices.append(price)

        db_session.commit()
        for price in prices:
            db_session.refresh(price)

        return prices

    return _create_prices


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
                tzinfo=UTC,
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
                    predicted_for, datetime.min.time(), tzinfo=UTC
                ).replace(hour=7, minute=1)  # 7:01am on prediction day
                prediction.error_abs = abs(actual_price - predicted_price)
                prediction.error_pct = (
                    abs(actual_price - predicted_price) / actual_price * 100
                )
                prediction.direction_correct = (
                    (
                        predicted_price > price_at_prediction
                        and actual_price > price_at_prediction
                    )
                    or (
                        predicted_price < price_at_prediction
                        and actual_price < price_at_prediction
                    )
                    or (
                        predicted_price == price_at_prediction
                        and actual_price == price_at_prediction
                    )
                )
                # Simple PnL: if predicted up, gain = actual - price_at_prediction
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
