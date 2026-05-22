"""
Unit tests for backtest utility functions.

Tests:
- fetch_training_data: Fetch rolling training window from btc_prices
- generate_prediction: Train model and generate prediction
- save_backtest_result: Save backtest result to database
- get_actual_price_for_date: Get actual BTC price for specific date
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

import pandas as pd
import pytest

from scripts.backtest_utils import (
    fetch_training_data,
    generate_prediction,
    get_actual_price_for_date,
    save_backtest_result,
)
from shared.db.models import BacktestResult, BtcPrice


class TestFetchTrainingData:
    """Tests for fetch_training_data function."""

    def test_fetch_30_day_window(self, db_session, sample_btc_prices):
        """Scenario: Fetch 30-day training window successfully."""
        # Given: 60 days of daily data
        end_date = date(2024, 5, 31)

        # When: Fetch 30-day window
        result = fetch_training_data(end_date, window_days=30, db=db_session)

        # Then: Should return DataFrame with ~30-31 rows (daily frequency)
        assert result is not None
        assert isinstance(result, pd.DataFrame)
        assert len(result) >= 30  # At least 30 days
        assert len(result) <= 31  # At most 31 days (includes partial days)

        # Check columns
        expected_columns = ["timestamp", "open", "high", "low", "close", "volume"]
        assert list(result.columns) == expected_columns

        # Check date range
        assert result["timestamp"].min().date() >= end_date - timedelta(days=30)
        assert result["timestamp"].max().date() <= end_date

    def test_fetch_insufficient_data(self, db_session, sample_btc_prices):
        """Scenario: Return None when insufficient data."""
        # Given: Only 60 days of data
        # When: Request 90-day window (more than available)
        end_date = date(2024, 5, 31)
        result = fetch_training_data(end_date, window_days=90, db=db_session)

        # Then: Should return None
        assert result is None

    def test_fetch_no_data(self, db_session):
        """Scenario: Return None when no data exists."""
        # Given: Empty database
        # When: Fetch training data
        end_date = date(2024, 5, 31)
        result = fetch_training_data(end_date, window_days=30, db=db_session)

        # Then: Should return None
        assert result is None

    def test_fetch_custom_window(self, db_session, sample_btc_prices):
        """Scenario: Fetch custom window size (60 days)."""
        # Given: 60 days of daily data
        end_date = date(2024, 6, 30)

        # When: Fetch 60-day window
        result = fetch_training_data(end_date, window_days=60, db=db_session)

        # Then: Should return DataFrame with ~60 rows (daily frequency)
        assert result is not None
        assert len(result) >= 60  # At least 60 days


class TestGeneratePrediction:
    """Tests for generate_prediction function."""

    def test_generate_prediction_success(self, db_session, sample_btc_prices):
        """Scenario: Successfully train model and generate prediction."""
        # Given: 60 days of training data
        end_date = date(2024, 6, 29)
        training_data = fetch_training_data(end_date, window_days=60, db=db_session)
        assert training_data is not None

        prediction_date = date(2024, 6, 30)
        price_at_prediction = Decimal("68000.00")

        # When: Generate prediction
        predicted_price, model_params = generate_prediction(
            training_data, prediction_date, price_at_prediction, db=db_session
        )

        # Then: Should return valid prediction and params
        assert isinstance(predicted_price, Decimal)
        assert predicted_price > 0

        # Check model params
        assert model_params["model_name"] == "linear_v1"
        assert model_params["window_days"] == 30
        assert "train_from" in model_params
        assert "train_to" in model_params
        assert model_params["training_samples"] > 0
        assert model_params["training_days"] >= 30

    def test_generate_prediction_insufficient_data(self, db_session):
        """Scenario: Raise ValueError when insufficient training data."""
        # Given: Only 10 days of daily data (not enough for 30-day window)
        start_date = date(2024, 5, 1)
        prices = []
        for day in range(10):
            current_date = start_date + timedelta(days=day)
            # Create 1 record per day at 12:00 PM (daily frequency)
            timestamp = datetime.combine(current_date, time(12, 0))
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

        training_data = pd.DataFrame(
            [
                {
                    "timestamp": p.timestamp,
                    "open": float(p.open),
                    "high": float(p.high),
                    "low": float(p.low),
                    "close": float(p.close),
                    "volume": float(p.volume),
                }
                for p in prices
            ]
        )

        # When/Then: Should raise ValueError
        with pytest.raises(ValueError, match="Insufficient data for training"):
            generate_prediction(
                training_data,
                date(2024, 5, 11),
                Decimal("66000.00"),
                db=db_session,
            )


class TestSaveBacktestResult:
    """Tests for save_backtest_result function."""

    def test_save_result_success(self, db_session):
        """Scenario: Successfully save backtest result to database."""
        # Given: Backtest result data
        backtest_run_id = uuid4()
        predicted_for = date(2024, 5, 15)
        predicted_at = datetime(2024, 5, 14, 23, 59, 59)
        price_at_prediction = Decimal("66000.00")
        predicted_price = Decimal("67000.00")
        actual_price = Decimal("67500.00")
        pnl_simple = Decimal("1500.00")
        pnl_long_short = Decimal("1500.00")
        pnl_threshold = Decimal("1500.00")
        pnl_realistic = Decimal("1368.00")
        model_params = {
            "model_name": "linear_v1",
            "window_days": 30,
            "train_from": "2024-04-15",
            "train_to": "2024-05-14",
        }

        # When: Save result
        result = save_backtest_result(
            backtest_run_id=backtest_run_id,
            predicted_for=predicted_for,
            predicted_at=predicted_at,
            price_at_prediction=price_at_prediction,
            predicted_price=predicted_price,
            actual_price=actual_price,
            pnl_simple=pnl_simple,
            pnl_long_short=pnl_long_short,
            pnl_threshold=pnl_threshold,
            pnl_realistic=pnl_realistic,
            model_params=model_params,
            db=db_session,
        )

        # Then: Should save successfully
        assert result.id is not None
        assert result.backtest_run_id == backtest_run_id
        assert result.predicted_for == predicted_for
        assert result.predicted_price == predicted_price
        assert result.actual_price == actual_price
        assert result.pnl_realistic == pnl_realistic

        # Verify in database
        saved = db_session.query(BacktestResult).filter_by(id=result.id).first()
        assert saved is not None
        assert saved.backtest_run_id == backtest_run_id

    def test_save_multiple_results_same_run(self, db_session):
        """Scenario: Save multiple results with same backtest_run_id."""
        # Given: Same backtest_run_id for multiple predictions
        backtest_run_id = uuid4()

        # When: Save 3 results with same run ID
        for day in range(10, 13):  # Use days 10-12 to avoid day 0
            save_backtest_result(
                backtest_run_id=backtest_run_id,
                predicted_for=date(2024, 5, day),
                predicted_at=datetime(2024, 5, day - 1, 23, 59, 59),
                price_at_prediction=Decimal("66000.00"),
                predicted_price=Decimal("67000.00"),
                actual_price=Decimal("67500.00"),
                pnl_simple=Decimal("1500.00"),
                pnl_long_short=Decimal("1500.00"),
                pnl_threshold=Decimal("1500.00"),
                pnl_realistic=Decimal("1368.00"),
                model_params={"model_name": "linear_v1"},
                db=db_session,
            )

        # Then: All 3 results should be saved with same backtest_run_id
        results = (
            db_session.query(BacktestResult)
            .filter_by(backtest_run_id=backtest_run_id)
            .all()
        )
        assert len(results) == 3
        assert all(r.backtest_run_id == backtest_run_id for r in results)


class TestGetActualPriceForDate:
    """Tests for get_actual_price_for_date function."""

    def test_get_price_exists(self, db_session, sample_btc_prices):
        """Scenario: Get actual price when data exists."""
        # Given: Price data for May 15, 2024
        target_date = date(2024, 5, 15)

        # When: Get actual price
        price = get_actual_price_for_date(target_date, db=db_session)

        # Then: Should return closing price
        assert price is not None
        assert isinstance(price, Decimal)
        assert price > 0

    def test_get_price_not_exists(self, db_session, sample_btc_prices):
        """Scenario: Return None when no price data for date."""
        # Given: Data only for May-June 2024
        # When: Request price for date outside range
        target_date = date(2024, 12, 31)
        price = get_actual_price_for_date(target_date, db=db_session)

        # Then: Should return None
        assert price is None

    def test_get_last_price_of_day(self, db_session):
        """Scenario: Get last price of the day (23:00 close)."""
        # Given: Multiple prices for same day
        target_date = date(2024, 5, 15)
        prices = []
        for hour in range(24):
            timestamp = datetime.combine(target_date, datetime.min.time()) + timedelta(
                hours=hour
            )
            # Each hour has different close price
            price = BtcPrice(
                timestamp=timestamp,
                open=Decimal("66000.00"),
                high=Decimal("66100.00"),
                low=Decimal("65900.00"),
                close=Decimal("66000.00") + Decimal(hour * 100),  # Increasing
                volume=Decimal("1000.50"),
                source="test",
            )
            prices.append(price)

        db_session.add_all(prices)
        db_session.commit()

        # When: Get actual price
        price = get_actual_price_for_date(target_date, db=db_session)

        # Then: Should return last close (hour 23)
        expected_last_close = Decimal("66000.00") + Decimal(23 * 100)
        assert price == expected_last_close
