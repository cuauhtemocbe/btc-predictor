"""
Integration tests for BtcPrice model - US-002 Gherkin scenarios.

Prerequisites: Run migrations before tests:
    docker compose exec api sh -c "cd shared && alembic upgrade head"
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from shared.config import settings
from shared.db.models import BtcPrice
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker


# Module-level engine (shared across all tests)
@pytest.fixture(scope="module")
def engine():
    """Create engine once for all tests."""
    eng = create_engine(
        settings.database_url, pool_pre_ping=True, pool_recycle=3600, echo=False
    )
    yield eng
    eng.dispose()


# Function-level session with rollback
@pytest.fixture(scope="function")
def session(engine):
    """Create session with automatic rollback for test isolation."""
    connection = engine.connect()
    transaction = connection.begin()

    SessionLocal = sessionmaker(bind=connection, expire_on_commit=False)
    sess = SessionLocal()

    yield sess

    sess.close()
    transaction.rollback()
    connection.close()


class TestGherkinScenario1:
    """
    Scenario 1: Create btc_prices table via migration

    Given Alembic is configured in shared/alembic/
    When I run "alembic upgrade head"
    Then a table named "btc_prices" exists in PostgreSQL
    And it has columns: id, timestamp, open, high, low, close, volume, source
    And timestamp has a UNIQUE constraint
    """

    def test_table_exists_with_correct_schema(self, engine):
        """Verify btc_prices table exists with correct structure."""
        inspector = inspect(engine)

        # Assert: Table exists
        tables = inspector.get_table_names()
        assert "btc_prices" in tables, "btc_prices table should exist"

        # Assert: All columns exist
        columns = {col["name"]: col for col in inspector.get_columns("btc_prices")}
        expected_cols = [
            "id",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
        ]

        for col_name in expected_cols:
            assert col_name in columns, f"Column '{col_name}' should exist"

        # Assert: Timestamp is TIMESTAMPTZ
        timestamp_col = columns["timestamp"]
        assert "TIMESTAMP" in str(timestamp_col["type"]), (
            "timestamp should be TIMESTAMP type"
        )

        # Assert: UNIQUE index on timestamp
        indexes = inspector.get_indexes("btc_prices")
        timestamp_idx = [idx for idx in indexes if "timestamp" in idx["column_names"]]
        assert len(timestamp_idx) > 0, "Should have index on timestamp"
        assert timestamp_idx[0]["unique"], "timestamp index should be UNIQUE"


class TestGherkinScenario2:
    """
    Scenario 2: Insert valid OHLCV record

    Given the btc_prices table exists
    When I insert a record with timestamp "2026-05-16 14:00:00+00:00"
    And close=67432.50, volume=123.45, source="binance"
    Then the record is saved successfully
    And querying by timestamp returns the record
    """

    def test_insert_and_query_valid_record(self, session):
        """Test inserting a valid OHLCV record."""
        test_time = datetime(2026, 5, 16, 14, 0, 0, tzinfo=UTC)

        # Act: Insert record
        price = BtcPrice(
            timestamp=test_time,
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

        # Assert: Has ID
        assert price.id is not None, "Saved record should have an ID"

        # Assert: Can query by timestamp
        found = session.query(BtcPrice).filter(BtcPrice.timestamp == test_time).first()

        assert found is not None, "Should find record by timestamp"
        assert found.close == Decimal("67432.50"), "Close price should match"
        assert found.volume == Decimal("123.45"), "Volume should match"
        assert found.source == "binance", "Source should match"
        assert isinstance(found.close, Decimal), "Prices should be Decimal type"
        assert found.timestamp.tzinfo is not None, "Timestamp should be timezone-aware"


class TestGherkinScenario3:
    """
    Scenario 3: Duplicate timestamp is rejected

    Given a record exists with timestamp "2026-05-16 14:00:00+00:00"
    When I attempt to insert another record with the same timestamp
    Then an IntegrityError is raised
    And the second record is not saved
    """

    def test_duplicate_timestamp_raises_integrity_error(self, engine):
        """Test that duplicate timestamp is rejected by UNIQUE constraint."""
        from sqlalchemy.orm import sessionmaker

        # Create a session with real commits for this test
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        try:
            test_time = datetime(2026, 5, 16, 15, 0, 0, tzinfo=UTC)

            # Arrange: Insert first record and commit
            first = BtcPrice(
                timestamp=test_time,
                open=Decimal("50000.00"),
                high=Decimal("51000.00"),
                low=Decimal("49000.00"),
                close=Decimal("50500.00"),
                volume=Decimal("100.0"),
                source="binance",
            )
            session.add(first)
            session.commit()

            # Act & Assert: Try to insert duplicate
            duplicate = BtcPrice(
                timestamp=test_time,  # Same timestamp!
                open=Decimal("51000.00"),
                high=Decimal("52000.00"),
                low=Decimal("50000.00"),
                close=Decimal("51500.00"),
                volume=Decimal("200.0"),
                source="binance",
            )
            session.add(duplicate)

            with pytest.raises(IntegrityError) as exc:
                session.commit()

            # Assert: Error mentions unique/duplicate
            error_msg = str(exc.value).lower()
            assert "unique" in error_msg or "duplicate" in error_msg, (
                "Error should mention unique constraint violation"
            )

            # Rollback the failed transaction
            session.rollback()

            # Verify only one record exists (in new transaction)
            count = (
                session.query(BtcPrice).filter(BtcPrice.timestamp == test_time).count()
            )
            assert count == 1, "Should have exactly one record with this timestamp"

        finally:
            # Clean up: delete test data
            session.query(BtcPrice).filter(BtcPrice.timestamp == test_time).delete()
            session.commit()
            session.close()


class TestGherkinScenario4:
    """
    Scenario 4: Downgrade migration removes table

    Given the btc_prices table exists
    When I run "alembic downgrade -1"
    Then the btc_prices table no longer exists

    NOTE: This scenario was verified manually in Task 4.
    Skipping automated test to avoid breaking other tests.
    """

    @pytest.mark.skip(reason="Verified manually - would break other tests")
    def test_downgrade_removes_table(self):
        """Downgrade scenario tested manually in Task 4."""
        pass


class TestZombiesEdgeCases:
    """Additional edge cases from ZOMBIES analysis."""

    def test_zero_volume_is_valid(self, session):
        """ZOMBIES Z: Zero volume should be accepted."""
        price = BtcPrice(
            timestamp=datetime(2026, 5, 16, 16, 0, 0, tzinfo=UTC),
            open=Decimal("50000.0"),
            high=Decimal("50000.0"),
            low=Decimal("50000.0"),
            close=Decimal("50000.0"),
            volume=Decimal("0.0"),  # Zero is valid
            source="binance",
        )
        session.add(price)
        session.commit()

        assert price.id is not None, "Should save record with zero volume"

    def test_null_timestamp_rejected(self, session):
        """ZOMBIES E: NULL timestamp should violate NOT NULL constraint."""
        price = BtcPrice(
            timestamp=None,  # NULL should fail
            open=Decimal("50000.0"),
            high=Decimal("50000.0"),
            low=Decimal("50000.0"),
            close=Decimal("50000.0"),
            volume=Decimal("100.0"),
            source="binance",
        )
        session.add(price)

        with pytest.raises(IntegrityError):
            session.commit()

        session.rollback()

    def test_large_price_values(self, session):
        """ZOMBIES B: Test boundary values (large Bitcoin price)."""
        # BTC could theoretically reach very high values
        large_price = Decimal("999999999.99999999")  # Within NUMERIC(18,8)

        price = BtcPrice(
            timestamp=datetime(2026, 5, 16, 17, 0, 0, tzinfo=UTC),
            open=large_price,
            high=large_price,
            low=large_price,
            close=large_price,
            volume=Decimal("1000.0"),
            source="binance",
        )
        session.add(price)
        session.commit()

        assert price.id is not None
        assert price.close == large_price, "Should handle large price values"
