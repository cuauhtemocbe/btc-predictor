"""
Pytest configuration and fixtures for shared package tests.
"""

import pytest
import os
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from alembic import command
from alembic.config import Config

from shared.config import settings
from shared.db.models import Base, BtcPrice


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


@pytest.fixture(scope="session")
def db_engine_session():
    """
    Create a session-scoped SQLAlchemy engine for migrations.
    """
    engine = create_engine(settings.database_url, echo=False)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db_engine():
    """
    Create a function-scoped SQLAlchemy engine for tests.
    """
    engine = create_engine(settings.database_url, echo=False)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine, apply_migrations):
    """
    Create a database session with automatic rollback after test.
    This ensures test isolation - changes are not persisted.
    Depends on apply_migrations to ensure table exists.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection)
    session = SessionLocal()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="session")
def apply_migrations(db_engine_session):
    """
    Ensures Alembic migrations are applied for integration tests.

    NOTE: This fixture assumes migrations have been applied externally
    via `alembic upgrade head` before running tests. It does not
    automatically apply migrations to avoid conflicts and slowness.

    To prepare test database:
        docker compose exec api sh -c "cd shared && alembic upgrade head"
    """
    # Just verify that the table exists
    from sqlalchemy import inspect
    inspector = inspect(db_engine_session)
    if "btc_prices" not in inspector.get_table_names():
        pytest.skip("btc_prices table not found. Run 'alembic upgrade head' before tests.")

    yield

    # No cleanup - migrations persist between test runs


@pytest.fixture
def sample_btc_price(db_session):
    """
    Factory fixture for creating sample BtcPrice records.
    Automatically cleans up after test (via db_session rollback).
    """
    def _create_price(
        timestamp: datetime = None,
        open: Decimal = Decimal("50000.0"),
        high: Decimal = Decimal("51000.0"),
        low: Decimal = Decimal("49000.0"),
        close: Decimal = Decimal("50500.0"),
        volume: Decimal = Decimal("123.45"),
        source: str = "binance",
    ) -> BtcPrice:
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

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
