"""
Pytest configuration and fixtures for backtest script tests.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from shared.db.models import BtcPrice


# Note: db_session is provided by root conftest.py
# Note: Database schema is created by autouse fixture in root conftest.py


@pytest.fixture
def sample_btc_prices(db_session):
    """Create sample BTC price data for testing (60 days, 4-hour granularity)."""
    start_date = date(2024, 5, 1)
    prices = []

    for day in range(60):
        current_date = start_date + timedelta(days=day)
        base_price = Decimal("66000.00") + Decimal(day * 100)

        # Create 6 records per day at 4-hour intervals (0h, 4h, 8h, 12h, 16h, 20h)
        for interval in range(6):
            hour = interval * 4
            timestamp = datetime.combine(current_date, time(hour, 0)).replace(
                tzinfo=timezone.utc
            )
            price = BtcPrice(
                timestamp=timestamp,
                open=base_price + Decimal(interval * 10),
                high=base_price + Decimal(interval * 10) + Decimal("100.00"),
                low=base_price + Decimal(interval * 10) - Decimal("100.00"),
                close=base_price + Decimal(interval * 10) + Decimal("50.00"),
                volume=Decimal("1000.50"),
                source="test",
            )
            prices.append(price)

    db_session.add_all(prices)
    db_session.commit()
    return prices


@pytest.fixture
def historical_data_60_days(db_session):
    """Create 60 days of BTC price data for integration tests (4-hour granularity)."""
    start_date = date(2024, 4, 1)
    prices = []

    for day in range(60):
        current_date = start_date + timedelta(days=day)
        base_price = Decimal("66000.00") + Decimal(day * 50)

        # Create 6 records per day at 4-hour intervals (0h, 4h, 8h, 12h, 16h, 20h)
        for interval in range(6):
            hour = interval * 4
            timestamp = datetime.combine(current_date, time(hour, 0)).replace(
                tzinfo=timezone.utc
            )
            price = BtcPrice(
                timestamp=timestamp,
                open=base_price + Decimal(interval * 5),
                high=base_price + Decimal(interval * 5) + Decimal("200"),
                low=base_price + Decimal(interval * 5) - Decimal("200"),
                close=base_price + Decimal(interval * 5) + Decimal("100"),
                volume=Decimal("1000.50"),
                source="test",
            )
            prices.append(price)

    db_session.add_all(prices)
    db_session.commit()
    return prices


@pytest.fixture
def historical_90_days(db_session):
    """Create 90 days of BTC price data for Gherkin tests (4-hour granularity)."""
    start_date = date(2024, 3, 1)
    prices = []

    for day in range(90):
        current_date = start_date + timedelta(days=day)
        base_price = Decimal("66000.00") + Decimal(day * 30)

        # Create 6 records per day at 4-hour intervals (0h, 4h, 8h, 12h, 16h, 20h)
        for interval in range(6):
            hour = interval * 4
            timestamp = datetime.combine(current_date, time(hour, 0)).replace(
                tzinfo=timezone.utc
            )
            price = BtcPrice(
                timestamp=timestamp,
                open=base_price + Decimal(interval * 5),
                high=base_price + Decimal(interval * 5) + Decimal("100.00"),
                low=base_price + Decimal(interval * 5) - Decimal("100.00"),
                close=base_price + Decimal(interval * 5) + Decimal("50.00"),
                volume=Decimal("1000.50"),
                source="test",
            )
            prices.append(price)

    db_session.add_all(prices)
    db_session.commit()
    return prices
