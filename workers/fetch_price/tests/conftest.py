"""Pytest configuration and fixtures for fetch_price tests."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from shared.db.models import Base, BtcPrice
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def binance_api_url():
    """Base URL for Binance API."""
    return "https://api.binance.com"


@pytest.fixture
def sample_binance_response():
    """Sample Binance /api/v3/klines response for BTCUSDT 1h."""
    return [
        [
            1714521600000,      # Kline open time (Unix ms) - 2024-05-01 00:00:00 UTC
            "63000.50",         # Open
            "63500.75",         # High
            "62800.25",         # Low
            "63200.00",         # Close
            "1234.56789012",    # Volume
            1714525199999,      # Kline close time
            "77777777.77",      # Quote asset volume
            5000,               # Number of trades
            "617.28394506",     # Taker buy base asset volume
            "38888888.88",      # Taker buy quote asset volume
            "0"                 # Unused field
        ]
    ]


@pytest.fixture
def sample_binance_multiple_candles():
    """Sample Binance response with 3 candles."""
    return [
        [
            1714528800000,      # 2024-05-01 02:00:00 UTC (newest)
            "63400.00",
            "63600.00",
            "63300.00",
            "63500.00",
            "800.12345678",
            1714532399999,
            "50000000.00",
            3000,
            "400.06172839",
            "25000000.00",
            "0"
        ],
        [
            1714525200000,      # 2024-05-01 01:00:00 UTC
            "63200.00",
            "63450.00",
            "63100.00",
            "63400.00",
            "950.98765432",
            1714528799999,
            "60000000.00",
            4000,
            "475.49382716",
            "30000000.00",
            "0"
        ],
        [
            1714521600000,      # 2024-05-01 00:00:00 UTC (oldest)
            "63000.50",
            "63500.75",
            "62800.25",
            "63200.00",
            "1234.56789012",
            1714525199999,
            "77777777.77",
            5000,
            "617.28394506",
            "38888888.88",
            "0"
        ]
    ]


@pytest.fixture
def test_db_engine():
    """Create in-memory SQLite engine for tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def test_db_session(test_db_engine):
    """Create database session for tests with automatic cleanup."""
    test_session_local = sessionmaker(bind=test_db_engine)
    session = test_session_local()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def sample_price_data():
    """Sample price data as dictionaries (ready for database)."""
    return [
        {
            "timestamp": datetime(2024, 5, 1, 2, 0, 0, tzinfo=timezone.utc),
            "open": Decimal("63400.00"),
            "high": Decimal("63600.00"),
            "low": Decimal("63300.00"),
            "close": Decimal("63500.00"),
            "volume": Decimal("800.12345678"),
            "source": "binance"
        },
        {
            "timestamp": datetime(2024, 5, 1, 1, 0, 0, tzinfo=timezone.utc),
            "open": Decimal("63200.00"),
            "high": Decimal("63450.00"),
            "low": Decimal("63100.00"),
            "close": Decimal("63400.00"),
            "volume": Decimal("950.98765432"),
            "source": "binance"
        },
        {
            "timestamp": datetime(2024, 5, 1, 0, 0, 0, tzinfo=timezone.utc),
            "open": Decimal("63000.50"),
            "high": Decimal("63500.75"),
            "low": Decimal("62800.25"),
            "close": Decimal("63200.00"),
            "volume": Decimal("1234.56789012"),
            "source": "binance"
        }
    ]


@pytest.fixture
def existing_btc_prices(test_db_session):
    """Pre-populate database with 2 existing prices."""
    prices = [
        BtcPrice(
            timestamp=datetime(2024, 5, 1, 1, 0, 0, tzinfo=timezone.utc),
            open=Decimal("63200.00"),
            high=Decimal("63450.00"),
            low=Decimal("63100.00"),
            close=Decimal("63400.00"),
            volume=Decimal("950.98765432"),
            source="binance"
        ),
        BtcPrice(
            timestamp=datetime(2024, 5, 1, 0, 0, 0, tzinfo=timezone.utc),
            open=Decimal("63000.50"),
            high=Decimal("63500.75"),
            low=Decimal("62800.25"),
            close=Decimal("63200.00"),
            volume=Decimal("1234.56789012"),
            source="binance"
        )
    ]
    test_db_session.add_all(prices)
    test_db_session.commit()
    return prices
