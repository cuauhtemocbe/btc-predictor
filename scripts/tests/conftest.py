"""
Pytest configuration and fixtures for backtest script tests.
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from scripts.tests.helpers import DailyRows, PriceRows
from shared.db.models import Price

# Note: db_session is provided by root conftest.py
# Note: Database schema is created by autouse fixture in root conftest.py


# ============================================================================
# Module-scoped cached price data (pre-calculated values)
# ============================================================================


@pytest.fixture(scope="module")
def cached_sample_price_data() -> PriceRows:
    """Module-scoped cached price data (60 days, 360 records)."""
    start_date = date(2024, 5, 1)
    data: PriceRows = []

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
def sample_btc_prices(
    db_session: Session, cached_sample_price_data: PriceRows
) -> list[Price]:
    """Create sample BTC price data using cached values (60 days, 360 records)."""
    prices: list[Price] = []

    for timestamp, open_p, high, low, close, volume in cached_sample_price_data:
        price = Price(
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
def cached_historical_60_days() -> PriceRows:
    """Module-scoped cached historical data (60 days, 360 records)."""
    start_date = date(2024, 4, 1)
    data: PriceRows = []

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
def historical_data_60_days(
    db_session: Session, cached_historical_60_days: PriceRows
) -> list[Price]:
    """Create 60 days of BTC price data using cached values (360 records)."""
    prices: list[Price] = []

    for timestamp, open_p, high, low, close, volume in cached_historical_60_days:
        price = Price(
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
def cached_historical_90_days() -> PriceRows:
    """Module-scoped cached historical data (90 days, 540 records)."""
    start_date = date(2024, 3, 1)
    data: PriceRows = []

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
def historical_90_days(
    db_session: Session, cached_historical_90_days: PriceRows
) -> list[Price]:
    """Create 90 days of BTC price data using cached values (540 records)."""
    prices: list[Price] = []

    for timestamp, open_p, high, low, close, volume in cached_historical_90_days:
        price = Price(
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


# ============================================================================
# Deterministic daily series for the walk-forward engine (#106)
# ============================================================================

SYNTHETIC_FIRST_DAY = date(2023, 1, 1)
SYNTHETIC_DAYS = 800  # through 2025-03-11


@pytest.fixture(scope="module")
def synthetic_daily_rows() -> DailyRows:
    """Module-scoped (day, close, volume) rows of a seeded random walk, one per day.

    Every close and volume is distinct, so a test can tell which day's data
    reached a function by looking at its values.
    """
    import numpy as np

    rng = np.random.default_rng(20240610)
    closes = 30000 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, SYNTHETIC_DAYS)))
    volumes = 1000 * np.exp(rng.normal(0, 0.3, SYNTHETIC_DAYS))
    return [
        (
            SYNTHETIC_FIRST_DAY + timedelta(days=i),
            Decimal(f"{closes[i]:.2f}"),
            Decimal(f"{volumes[i]:.8f}"),
        )
        for i in range(SYNTHETIC_DAYS)
    ]


@pytest.fixture
def seeded_prices(db_session: Session, synthetic_daily_rows: DailyRows) -> DailyRows:
    """Insert the synthetic series as BTCUSDT daily bars (00:00 UTC) and return it."""
    db_session.add_all(
        Price(
            timestamp=datetime.combine(day, time(0, 0)).replace(tzinfo=UTC),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=volume,
            source="test",
        )
        for day, close, volume in synthetic_daily_rows
    )
    db_session.commit()
    return synthetic_daily_rows
