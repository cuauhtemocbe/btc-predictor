"""
Pytest configuration and fixtures for API service tests.
"""

import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from api.main import app
from shared.config import settings
from shared.db.models import BtcPrice
from shared.db.database import get_db


@pytest.fixture
async def client():
    """
    Async HTTP client for testing FastAPI endpoints.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(scope="function")
def db_engine():
    """
    Create a function-scoped SQLAlchemy engine for tests.
    """
    engine = create_engine(settings.database_url, echo=False)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    """
    Create a database session with automatic rollback after test.
    This ensures test isolation - changes are not persisted.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection)
    session = SessionLocal()

    # Override the get_db dependency to use this test session
    def override_get_db():
        try:
            yield session
        finally:
            pass  # Don't close here, let the fixture handle it

    app.dependency_overrides[get_db] = override_get_db

    yield session

    # Cleanup
    session.close()
    transaction.rollback()
    connection.close()
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
            base_time = datetime.now(timezone.utc)

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
