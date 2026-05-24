"""
Pytest configuration and fixtures for backtest script tests.
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

from shared.db.models import BtcPrice

# Note: db_session is provided by root conftest.py
# Note: Database schema is created by autouse fixture in root conftest.py


# ============================================================================
# Module-scoped cached price data (pre-calculated values)
# ============================================================================


@pytest.fixture(scope="module")
def cached_sample_price_data():
    """Module-scoped cached price data (60 days, 360 records)."""
    start_date = date(2024, 5, 1)
    data = []

    for day in range(60):
        current_date = start_date + timedelta(days=day)
        base_price = 66000.00 + (day * 100)

        for interval in range(6):
            hour = interval * 4
            timestamp = datetime.combine(current_date, time(hour, 0)).replace(
                tzinfo=UTC
            )
            price_val = base_price + (interval * 10)

            data.append(
                (
                    timestamp,
                    Decimal(str(price_val)),  # open
                    Decimal(str(price_val + 100.00)),  # high
                    Decimal(str(price_val - 100.00)),  # low
                    Decimal(str(price_val + 50.00)),  # close
                    Decimal("1000.50"),  # volume
                )
            )

    return data


@pytest.fixture
def sample_btc_prices(db_session, cached_sample_price_data):
    """Create sample BTC price data using cached values (60 days, 360 records)."""
    prices = []

    for timestamp, open_p, high, low, close, volume in cached_sample_price_data:
        price = BtcPrice(
            timestamp=timestamp,
            open=open_p,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source="test",
        )
        prices.append(price)

    db_session.add_all(prices)
    db_session.commit()
    return prices


@pytest.fixture(scope="module")
def cached_historical_60_days():
    """Module-scoped cached historical data (60 days, 360 records)."""
    start_date = date(2024, 4, 1)
    data = []

    for day in range(60):
        current_date = start_date + timedelta(days=day)
        base_price = 66000.00 + (day * 50)

        for interval in range(6):
            hour = interval * 4
            timestamp = datetime.combine(current_date, time(hour, 0)).replace(
                tzinfo=UTC
            )
            price_val = base_price + (interval * 5)

            data.append(
                (
                    timestamp,
                    Decimal(str(price_val)),  # open
                    Decimal(str(price_val + 200)),  # high
                    Decimal(str(price_val - 200)),  # low
                    Decimal(str(price_val + 100)),  # close
                    Decimal("1000.50"),  # volume
                )
            )

    return data


@pytest.fixture
def historical_data_60_days(db_session, cached_historical_60_days):
    """Create 60 days of BTC price data using cached values (360 records)."""
    prices = []

    for timestamp, open_p, high, low, close, volume in cached_historical_60_days:
        price = BtcPrice(
            timestamp=timestamp,
            open=open_p,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source="test",
        )
        prices.append(price)

    db_session.add_all(prices)
    db_session.commit()
    return prices


@pytest.fixture(scope="module")
def cached_historical_90_days():
    """Module-scoped cached historical data (90 days, 540 records)."""
    start_date = date(2024, 3, 1)
    data = []

    for day in range(90):
        current_date = start_date + timedelta(days=day)
        base_price = 66000.00 + (day * 30)

        for interval in range(6):
            hour = interval * 4
            timestamp = datetime.combine(current_date, time(hour, 0)).replace(
                tzinfo=UTC
            )
            price_val = base_price + (interval * 5)

            data.append(
                (
                    timestamp,
                    Decimal(str(price_val)),  # open
                    Decimal(str(price_val + 100.00)),  # high
                    Decimal(str(price_val - 100.00)),  # low
                    Decimal(str(price_val + 50.00)),  # close
                    Decimal("1000.50"),  # volume
                )
            )

    return data


@pytest.fixture
def historical_90_days(db_session, cached_historical_90_days):
    """Create 90 days of BTC price data using cached values (540 records)."""
    prices = []

    for timestamp, open_p, high, low, close, volume in cached_historical_90_days:
        price = BtcPrice(
            timestamp=timestamp,
            open=open_p,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source="test",
        )
        prices.append(price)

    db_session.add_all(prices)
    db_session.commit()
    return prices
