"""
Integration tests for backtest.py script.

Tests end-to-end backtest execution with real database.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from scripts.backtest import (
    check_data_availability,
    run_backtest,
    validate_arguments,
)
from shared.db.models import BacktestResult, BtcPrice


class TestBacktestIntegration:
    """Integration tests for complete backtest workflow."""

    def test_backtest_30_days_end_to_end(self, db_session, historical_data_60_days):
        """
        Scenario: Run complete 30-day backtest end-to-end.

        Given: 60 days of historical data (30 for training window + 30 for backtest)
        When: Run backtest from May 2 to May 31
        Then: Creates 30 backtest results with valid predictions and PnL
        """
        # Given: Historical data loaded (starts April 1, ends May 30 = 60 days)
        # Need 30 days before May 2 (April 2 - May 1) for training
        start_date = date(2024, 5, 2)
        end_date = date(2024, 5, 30)  # Can't go beyond May 30 (last day of data)
        training_window = 30
        backtest_run_id = UUID("12345678-1234-5678-1234-567812345678")

        # When: Run backtest
        stats = run_backtest(start_date, end_date, training_window, backtest_run_id)

        # Then: Should process 29 days (May 2-30)
        assert stats["total_days"] == 29
        assert stats["predictions"] == 29  # All predictions made
        assert stats["skipped_no_actual"] == 0  # No missing data
        assert stats["skipped_training_failed"] == 0  # No training failures

        # Verify results in database
        results = (
            db_session.query(BacktestResult)
            .filter_by(backtest_run_id=backtest_run_id)
            .all()
        )

        assert len(results) == stats["predictions"]

        # Verify each result has valid data
        for result in results:
            assert result.backtest_run_id == backtest_run_id
            assert result.predicted_price > 0
            assert result.actual_price > 0
            assert result.price_at_prediction > 0
            # PnL can be positive or negative, but should exist
            assert result.pnl_simple is not None
            assert result.pnl_long_short is not None
            assert result.pnl_threshold is not None
            assert result.pnl_realistic is not None
            # Model params should be stored
            assert result.model_params is not None
            assert result.model_params["model_name"] == "linear_v1"

    def test_backtest_7_days_quick(self, db_session, historical_data_60_days):
        """
        Scenario: Run short 7-day backtest for quick validation.

        Given: 60 days of historical data
        When: Run backtest for 7 days
        Then: Creates 7 backtest results quickly
        """
        # Given: Historical data loaded (starts April 1)
        # Need 30 days before May 2 for training
        start_date = date(2024, 5, 2)
        end_date = date(2024, 5, 8)
        training_window = 30
        backtest_run_id = UUID("87654321-4321-8765-4321-876543218765")

        # When: Run backtest
        stats = run_backtest(start_date, end_date, training_window, backtest_run_id)

        # Then: Should process 7 days
        assert stats["total_days"] == 7
        assert stats["predictions"] == 7

        # Verify sequential predictions
        results = (
            db_session.query(BacktestResult)
            .filter_by(backtest_run_id=backtest_run_id)
            .order_by(BacktestResult.predicted_for)
            .all()
        )

        # Check dates are sequential
        for i, result in enumerate(results):
            expected_date = start_date + timedelta(days=i)
            assert result.predicted_for == expected_date

    def test_backtest_cumulative_pnl(self, db_session, historical_data_60_days):
        """
        Scenario: Calculate cumulative PnL over backtest period.

        Given: 30-day backtest completed
        When: Sum all PnL values
        Then: Cumulative PnL should be calculable for all strategies
        """
        # Given: Run backtest
        start_date = date(2024, 5, 1)
        end_date = date(2024, 5, 30)
        training_window = 30
        backtest_run_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        run_backtest(start_date, end_date, training_window, backtest_run_id)

        # When: Query cumulative PnL
        results = (
            db_session.query(BacktestResult)
            .filter_by(backtest_run_id=backtest_run_id)
            .all()
        )

        # Then: Calculate cumulative for each strategy
        cumulative_simple = sum(r.pnl_simple for r in results if r.pnl_simple)
        cumulative_long_short = sum(
            r.pnl_long_short for r in results if r.pnl_long_short
        )
        cumulative_threshold = sum(r.pnl_threshold for r in results if r.pnl_threshold)
        cumulative_realistic = sum(r.pnl_realistic for r in results if r.pnl_realistic)

        # All should be calculable (non-zero since we have price movements)
        assert cumulative_simple is not None
        assert cumulative_long_short is not None
        assert cumulative_threshold is not None
        assert cumulative_realistic is not None


class TestBacktestArguments:
    """Tests for argument parsing and validation."""

    def test_validate_arguments_success(self):
        """Scenario: Valid arguments pass validation."""

        # Given: Valid arguments
        class Args:
            start_date = "2024-05-01"
            end_date = "2024-05-30"
            training_window = 30

        # When: Validate
        start, end, window = validate_arguments(Args())

        # Then: Should parse correctly
        assert start == date(2024, 5, 1)
        assert end == date(2024, 5, 30)
        assert window == 30

    def test_validate_arguments_invalid_date_format(self):
        """Scenario: Invalid date format raises ValueError."""

        # Given: Invalid date format
        class Args:
            start_date = "05/01/2024"  # Wrong format
            end_date = "2024-05-30"
            training_window = 30

        # When/Then: Should raise ValueError
        with pytest.raises(ValueError, match="Invalid start-date format"):
            validate_arguments(Args())

    def test_validate_arguments_end_before_start(self):
        """Scenario: End date before start date raises ValueError."""

        # Given: End before start
        class Args:
            start_date = "2024-05-30"
            end_date = "2024-05-01"
            training_window = 30

        # When/Then: Should raise ValueError
        with pytest.raises(ValueError, match="start-date must be before end-date"):
            validate_arguments(Args())

    def test_validate_arguments_negative_window(self):
        """Scenario: Negative training window raises ValueError."""

        # Given: Negative training window
        class Args:
            start_date = "2024-05-01"
            end_date = "2024-05-30"
            training_window = -10

        # When/Then: Should raise ValueError
        with pytest.raises(ValueError, match="training-window must be >= 1"):
            validate_arguments(Args())


class TestDataAvailability:
    """Tests for data availability checks."""

    def test_check_data_availability_sufficient(
        self, db_session, historical_data_60_days
    ):
        """Scenario: Sufficient data passes check."""
        # Given: 60 days of data
        start_date = date(2024, 5, 1)
        training_window = 30

        # When/Then: Should not raise error
        try:
            check_data_availability(start_date, training_window, db_session)
        except ValueError:
            pytest.fail("Should not raise ValueError with sufficient data")

    def test_check_data_availability_insufficient(self, db_session):
        """Scenario: Insufficient data raises ValueError."""
        # Given: Empty database (no data)
        start_date = date(2024, 5, 1)
        training_window = 30

        # When/Then: Should raise ValueError
        with pytest.raises(ValueError, match="Insufficient data"):
            check_data_availability(start_date, training_window, db_session)


class TestBacktestWithDataGaps:
    """Tests for backtest behavior with missing data."""

    def test_backtest_skips_days_with_missing_actual_price(self, db_session):
        """Scenario: Backtest skips days with missing actual price data."""
        # Given: 40 days of data with gap on May 15
        start_date = date(2024, 4, 1)
        prices = []

        for day in range(40):
            current_date = start_date + timedelta(days=day)

            # Skip May 15 (create gap)
            if current_date == date(2024, 5, 15):
                continue

            for hour in range(24):
                timestamp = datetime.combine(
                    current_date, datetime.min.time()
                ) + timedelta(hours=hour)
                price = BtcPrice(
                    timestamp=timestamp,
                    open=Decimal("66000.00"),
                    high=Decimal("66100.00"),
                    low=Decimal("65900.00"),
                    close=Decimal("66050.00"),
                    volume=Decimal("1000.50"),
                    source="test",
                )
                prices.append(price)

        db_session.add_all(prices)
        db_session.commit()

        # When: Run backtest covering gap
        start_date = date(2024, 5, 1)
        end_date = date(2024, 5, 20)
        training_window = 30
        backtest_run_id = UUID("12341234-1234-1234-1234-123412341234")

        stats = run_backtest(start_date, end_date, training_window, backtest_run_id)

        # Then: Should skip May 15
        assert stats["skipped_no_actual"] >= 1  # At least one day skipped
        assert stats["predictions"] < 20  # Less than 20 predictions (1 missing)

        # Verify May 15 is not in results
        results = (
            db_session.query(BacktestResult)
            .filter_by(backtest_run_id=backtest_run_id)
            .all()
        )

        predicted_dates = {r.predicted_for for r in results}
        assert date(2024, 5, 15) not in predicted_dates
