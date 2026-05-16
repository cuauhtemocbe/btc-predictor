"""
Simple integration tests for BtcPrice model and btc_prices table.

These tests assume migrations have been applied:
    docker compose exec api sh -c "cd shared && alembic upgrade head"
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from shared.config import settings
from shared.db.models import BtcPrice


@pytest.fixture(scope="module")
def engine():
    """Create engine for tests."""
    eng = create_engine(settings.database_url)
    yield eng
    eng.dispose()


@pytest.fixture(scope="function")
def session(engine):
    """Create session with automatic rollback."""
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    sess = Session()

    yield sess

    sess.close()
    transaction.rollback()
    connection.close()


def test_insert_valid_ohlcv_record(session):
    """Gherkin Scenario 2: Insert valid OHLCV record."""
    test_timestamp = datetime(2026, 5, 16, 15, 0, 0, tzinfo=timezone.utc)

    price = BtcPrice(
        timestamp=test_timestamp,
        open=Decimal("67000.00"),
        high=Decimal("67500.00"),
        low=Decimal("66900.00"),
        close=Decimal("67432.50"),
        volume=Decimal("123.45"),
        source="binance",
    )
    session.add(price)
    session.commit()
    session.refresh(price)

    assert price.id is not None

    retrieved = session.query(BtcPrice).filter(BtcPrice.timestamp == test_timestamp).first()
    assert retrieved is not None
    assert retrieved.close == Decimal("67432.50")
    assert retrieved.source == "binance"


def test_duplicate_timestamp_rejected(session):
    """Gherkin Scenario 3: Duplicate timestamp is rejected."""
    test_timestamp = datetime(2026, 5, 16, 16, 0, 0, tzinfo=timezone.utc)

    first = BtcPrice(
        timestamp=test_timestamp,
        open=Decimal("50000.00"),
        high=Decimal("51000.00"),
        low=Decimal("49000.00"),
        close=Decimal("50500.00"),
        volume=Decimal("100.0"),
        source="binance",
    )
    session.add(first)
    session.commit()

    duplicate = BtcPrice(
        timestamp=test_timestamp,  # Same timestamp
        open=Decimal("51000.00"),
        high=Decimal("52000.00"),
        low=Decimal("50000.00"),
        close=Decimal("51500.00"),
        volume=Decimal("200.0"),
        source="binance",
    )
    session.add(duplicate)

    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()


def test_zero_volume_is_valid(session):
    """ZOMBIES edge case: Zero volume is valid."""
    price = BtcPrice(
        timestamp=datetime(2026, 5, 16, 17, 0, 0, tzinfo=timezone.utc),
        open=Decimal("50000.0"),
        high=Decimal("50000.0"),
        low=Decimal("50000.0"),
        close=Decimal("50000.0"),
        volume=Decimal("0.0"),
        source="binance",
    )
    session.add(price)
    session.commit()
    assert price.id is not None
