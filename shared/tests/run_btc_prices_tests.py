#!/usr/bin/env python3
"""
Direct test runner for btc_prices tests (bypasses pytest).

Run with: docker compose exec api python shared/tests/run_btc_prices_tests.py
"""

import sys
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from shared.config import settings
from shared.db.models import BtcPrice


def run_test(name, test_func):
    """Run a single test and report result."""
    try:
        test_func()
        print(f"✓ {name}")
        return True
    except AssertionError as e:
        print(f"✗ {name}: {e}")
        return False
    except Exception as e:
        print(f"✗ {name}: Unexpected error: {e}")
        return False


def test_scenario_1_table_exists():
    """Gherkin Scenario 1: Table structure is correct."""
    engine = create_engine(settings.database_url)
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

    # Assert: UNIQUE index on timestamp
    indexes = inspector.get_indexes("btc_prices")
    timestamp_idx = [idx for idx in indexes if "timestamp" in idx["column_names"]]
    assert len(timestamp_idx) > 0, "Should have index on timestamp"
    assert timestamp_idx[0]["unique"], "timestamp index should be UNIQUE"

    engine.dispose()


def test_scenario_2_insert_valid_record():
    """Gherkin Scenario 2: Insert and query valid OHLCV record."""
    engine = create_engine(settings.database_url)
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    try:
        test_time = datetime(2026, 5, 16, 20, 30, 0, tzinfo=UTC)

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

        assert price.id is not None, "Should have ID after commit"

        # Query back
        found = session.query(BtcPrice).filter(BtcPrice.timestamp == test_time).first()
        assert found is not None, "Should find record by timestamp"
        assert found.close == Decimal("67432.50"), "Close price should match"
        assert found.source == "binance", "Source should match"

    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_scenario_3_duplicate_timestamp():
    """Gherkin Scenario 3: Duplicate timestamp is rejected."""
    engine = create_engine(settings.database_url)
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    try:
        test_time = datetime(2026, 5, 16, 20, 31, 0, tzinfo=UTC)

        # Insert first record
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

        # Try to insert duplicate
        duplicate = BtcPrice(
            timestamp=test_time,  # Same timestamp
            open=Decimal("51000.00"),
            high=Decimal("52000.00"),
            low=Decimal("50000.00"),
            close=Decimal("51500.00"),
            volume=Decimal("200.0"),
            source="binance",
        )
        session.add(duplicate)

        try:
            session.commit()
            assert False, "Should have raised IntegrityError"
        except IntegrityError as e:
            error_msg = str(e).lower()
            assert "unique" in error_msg or "duplicate" in error_msg, (
                "Error should mention unique constraint"
            )

    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_edge_case_zero_volume():
    """ZOMBIES edge case: Zero volume is valid."""
    engine = create_engine(settings.database_url)
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    try:
        price = BtcPrice(
            timestamp=datetime(2026, 5, 16, 20, 32, 0, tzinfo=UTC),
            open=Decimal("50000.0"),
            high=Decimal("50000.0"),
            low=Decimal("50000.0"),
            close=Decimal("50000.0"),
            volume=Decimal("0.0"),
            source="binance",
        )
        session.add(price)
        session.commit()

        assert price.id is not None, "Should save record with zero volume"

    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def main():
    """Run all tests and report results."""
    print("=" * 70)
    print("BTC Prices Integration Tests - US-002 Gherkin Scenarios")
    print("=" * 70)
    print()

    tests = [
        ("Scenario 1: Table exists with correct schema", test_scenario_1_table_exists),
        (
            "Scenario 2: Insert and query valid record",
            test_scenario_2_insert_valid_record,
        ),
        (
            "Scenario 3: Duplicate timestamp rejected",
            test_scenario_3_duplicate_timestamp,
        ),
        ("Edge case: Zero volume is valid", test_edge_case_zero_volume),
    ]

    results = []
    for name, test_func in tests:
        results.append(run_test(name, test_func))
        print()

    print("=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("✓ ALL TESTS PASSED")
        return 0
    else:
        print(f"✗ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
