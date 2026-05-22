"""
Pytest configuration and fixtures for backtest script tests.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.config import settings
from shared.db.models import Base, BtcPrice


@pytest.fixture(scope="function")
def db_session():
    """
    Create test database session using PostgreSQL test database.
    Uses the same database as other tests but with transaction rollback.
    """
    engine = create_engine(settings.database_url, echo=False)

    # Create all tables
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    # Rollback and close
    session.rollback()
    session.close()

    # Drop all tables to clean up
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def sample_btc_prices(db_session):
    """Create sample BTC price data for testing (60 days)."""
    start_date = date(2024, 5, 1)
    prices = []

    for day in range(60):
        current_date = start_date + timedelta(days=day)
        base_price = Decimal("66000.00") + Decimal(day * 100)

        for hour in range(24):
            timestamp = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=hour
            )
            price = BtcPrice(
                timestamp=timestamp,
                open=base_price,
                high=base_price + Decimal("100.00"),
                low=base_price - Decimal("100.00"),
                close=base_price + Decimal(hour * 10),
                volume=Decimal("1000.50"),
                source="test",
            )
            prices.append(price)

    db_session.add_all(prices)
    db_session.commit()
    return prices


@pytest.fixture
def historical_data_60_days(db_session):
    """Create 60 days of hourly BTC price data for integration tests."""
    start_date = date(2024, 4, 1)
    prices = []

    for day in range(60):
        current_date = start_date + timedelta(days=day)
        base_price = Decimal("66000.00") + Decimal(day * 50)

        for hour in range(24):
            timestamp = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=hour
            )
            price_variation = Decimal(hour * 10) - Decimal("120")
            price = BtcPrice(
                timestamp=timestamp,
                open=base_price + price_variation,
                high=base_price + price_variation + Decimal("200"),
                low=base_price + price_variation - Decimal("200"),
                close=base_price + price_variation + Decimal("100"),
                volume=Decimal("1000.50"),
                source="test",
            )
            prices.append(price)

    db_session.add_all(prices)
    db_session.commit()
    return prices


@pytest.fixture
def historical_90_days(db_session):
    """Create 90 days of hourly BTC price data for Gherkin tests."""
    start_date = date(2024, 3, 1)
    prices = []

    for day in range(90):
        current_date = start_date + timedelta(days=day)
        base_price = Decimal("66000.00") + Decimal(day * 30)

        for hour in range(24):
            timestamp = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=hour
            )
            price = BtcPrice(
                timestamp=timestamp,
                open=base_price,
                high=base_price + Decimal("100.00"),
                low=base_price - Decimal("100.00"),
                close=base_price + Decimal(hour * 5),
                volume=Decimal("1000.50"),
                source="test",
            )
            prices.append(price)

    db_session.add_all(prices)
    db_session.commit()
    return prices
