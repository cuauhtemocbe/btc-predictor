"""
Pytest configuration and fixtures for shared package tests.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.config import settings
from shared.db.models import BtcPrice, Model, Prediction


@pytest.fixture
def clean_env(monkeypatch):
    """
    Fixture that ensures DATABASE_URL is not set in environment.
    Useful for testing validation errors.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture
def mock_database_url(monkeypatch):
    """
    Fixture that sets a valid DATABASE_URL for testing.
    """
    test_url = "postgresql://testuser:testpass@localhost:5432/testdb"
    monkeypatch.setenv("DATABASE_URL", test_url)
    return test_url


# Note: db_engine_session is provided by root conftest.py
# Note: db_session is provided by root conftest.py
# Note: Database schema is created by session-scoped fixture in root conftest.py


@pytest.fixture(scope="function")
async def async_db_session():
    """
    Create an async database session with automatic rollback after test.
    This ensures test isolation - changes are not persisted.
    Depends on apply_migrations to ensure table exists.
    """
    # Convert sync database URL to async
    async_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")
    async_engine = create_async_engine(async_url, echo=False)

    async with async_engine.begin() as connection:
        # Create async session bound to transaction
        AsyncSessionLocal = async_sessionmaker(
            bind=connection, class_=AsyncSession, expire_on_commit=False
        )

        session = AsyncSessionLocal()

        # Override commit to do nothing (let fixture handle rollback)
        async def _do_not_commit(*args, **kwargs):
            pass

        session.commit = _do_not_commit

        yield session

        await session.close()
        # Rollback happens automatically when exiting connection context

    await async_engine.dispose()


# Compatibility fixtures for tests that still reference old fixture names
@pytest.fixture
def db_engine(db_engine_session):
    """Compatibility: points to root db_engine_session"""
    return db_engine_session


@pytest.fixture
def apply_migrations():
    """
    Compatibility: no-op fixture.
    Schema is now created by autouse fixture in root conftest.py.
    """
    yield


@pytest.fixture
def sample_btc_price(db_session):
    """
    Factory fixture for creating sample BtcPrice records.
    Automatically cleans up after test (via db_session rollback).
    """

    def _create_price(
        timestamp: datetime | None = None,
        open: Decimal = Decimal("50000.0"),
        high: Decimal = Decimal("51000.0"),
        low: Decimal = Decimal("49000.0"),
        close: Decimal = Decimal("50500.0"),
        volume: Decimal = Decimal("123.45"),
        source: str = "binance",
    ) -> BtcPrice:
        if timestamp is None:
            timestamp = datetime.now(UTC)

        price = BtcPrice(
            timestamp=timestamp,
            open=open,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source=source,
        )
        db_session.add(price)
        db_session.commit()
        db_session.refresh(price)
        return price

    return _create_price


@pytest.fixture
def sample_model(db_session):
    """
    Factory fixture for creating sample Model records.
    Automatically cleans up after test (via db_session rollback).
    """

    def _create_model(
        name: str = "test_model",
        version: str = "1.0.0",
        params: dict[str, Any] | None = None,
        artifact: bytes = b"fake_pickle_data",
        trained_at: datetime | None = None,
        train_from: date | None = None,
        train_to: date | None = None,
        is_active: bool = False,
    ) -> Model:
        if params is None:
            params = {"window_days": 30}
        if trained_at is None:
            trained_at = datetime.now(UTC)
        if train_from is None:
            train_from = date.today() - timedelta(days=30)
        if train_to is None:
            train_to = date.today()

        model = Model(
            name=name,
            version=version,
            params=params,
            artifact=artifact,
            trained_at=trained_at,
            train_from=train_from,
            train_to=train_to,
            is_active=is_active,
        )
        db_session.add(model)
        db_session.commit()
        db_session.refresh(model)
        return model

    return _create_model


@pytest.fixture
def sample_prediction(db_session, sample_model):
    """
    Factory fixture for creating sample Prediction records.

    Phase 1 - before evaluation.
    Evaluation fields (actual_price, errors, pnl) are NULL.
    Automatically cleans up after test (via db_session rollback).
    """

    def _create_prediction(
        model_id: int | None = None,
        predicted_for: date | None = None,
        predicted_at: datetime | None = None,
        price_at_prediction: Decimal = Decimal("67000.00"),
        predicted_price: Decimal = Decimal("68000.00"),
    ) -> Prediction:
        if model_id is None:
            # Create a default model if not provided
            model = sample_model()
            model_id = model.id
        if predicted_for is None:
            predicted_for = date.today() + timedelta(days=1)
        if predicted_at is None:
            predicted_at = datetime.now(UTC)

        prediction = Prediction(
            model_id=model_id,
            predicted_for=predicted_for,
            predicted_at=predicted_at,
            price_at_prediction=price_at_prediction,
            predicted_price=predicted_price,
            # Phase 1: evaluation fields NULL
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

    return _create_prediction


@pytest.fixture
def evaluated_prediction(db_session, sample_model):
    """
    Factory fixture for creating evaluated Prediction records.

    Phase 2 - after evaluation.
    All evaluation fields are filled.
    Automatically cleans up after test (via db_session rollback).
    """

    def _create_evaluated_prediction(
        model_id: int | None = None,
        predicted_for: date | None = None,
        predicted_at: datetime | None = None,
        price_at_prediction: Decimal = Decimal("67000.00"),
        predicted_price: Decimal = Decimal("68000.00"),
        actual_price: Decimal = Decimal("67500.00"),
        evaluated_at: datetime | None = None,
        error_abs: Decimal = Decimal("500.00"),
        error_pct: Decimal = Decimal("0.74"),
        direction_correct: bool = True,
        pnl_simulated: Decimal = Decimal("500.00"),
        timeframe: str = "1d",
    ) -> Prediction:
        if model_id is None:
            # Create a default model if not provided
            model = sample_model()
            model_id = model.id
        if predicted_for is None:
            predicted_for = date.today()
        if predicted_at is None:
            predicted_at = datetime.now(UTC) - timedelta(days=1)
        if evaluated_at is None:
            evaluated_at = datetime.now(UTC)

        prediction = Prediction(
            model_id=model_id,
            predicted_for=predicted_for,
            predicted_at=predicted_at,
            price_at_prediction=price_at_prediction,
            predicted_price=predicted_price,
            # Phase 2: evaluation fields filled
            actual_price=actual_price,
            evaluated_at=evaluated_at,
            error_abs=error_abs,
            error_pct=error_pct,
            direction_correct=direction_correct,
            pnl_simulated=pnl_simulated,
            timeframe=timeframe,
        )
        db_session.add(prediction)
        db_session.commit()
        db_session.refresh(prediction)
        return prediction

    return _create_evaluated_prediction
