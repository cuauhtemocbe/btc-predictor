"""
Tests for utility functions.

Covers all Gherkin scenarios from US-013:
- Calculate PnL for different prediction/outcome combinations
"""

from decimal import Decimal

import numpy as np
import pytest

from shared.utils import (
    calculate_mape,
    calculate_pnl,
    calculate_pnl_long_short,
    calculate_pnl_realistic,
    calculate_pnl_threshold,
    split_train_validation,
)


class TestCalculatePnl:
    """Test calculate_pnl function with Gherkin scenarios and edge cases."""

    def test_predicted_up_actual_up_profit(self):
        """
        Scenario: Predicted UP, actual UP → profit
        Given predicted_price=68000
        And price_at_prediction=67000
        And actual_price=68500
        When I call calculate_pnl(predicted, before, actual)
        Then the result is 1500
        """
        result = calculate_pnl(
            predicted_price=Decimal("68000"),
            price_at_prediction=Decimal("67000"),
            actual_price=Decimal("68500"),
        )
        assert result == Decimal("1500.00")

    def test_predicted_up_actual_down_loss(self):
        """
        Scenario: Predicted UP, actual DOWN → loss
        Given predicted_price=68000
        And price_at_prediction=67000
        And actual_price=66000
        When I call calculate_pnl(predicted, before, actual)
        Then the result is -1000
        """
        result = calculate_pnl(
            predicted_price=Decimal("68000"),
            price_at_prediction=Decimal("67000"),
            actual_price=Decimal("66000"),
        )
        assert result == Decimal("-1000.00")

    def test_predicted_down_actual_down_no_trade(self):
        """
        Scenario: Predicted DOWN, actual DOWN → no trade (0 PnL)
        Given predicted_price=66000
        And price_at_prediction=67000
        And actual_price=65000
        When I call calculate_pnl(predicted, before, actual)
        Then the result is 0
        """
        result = calculate_pnl(
            predicted_price=Decimal("66000"),
            price_at_prediction=Decimal("67000"),
            actual_price=Decimal("65000"),
        )
        assert result == Decimal("0.00")

    def test_predicted_down_actual_up_no_trade(self):
        """
        Scenario: Predicted DOWN, actual UP → no trade (0 PnL)
        Given predicted_price=66000
        And price_at_prediction=67000
        And actual_price=68000
        When I call calculate_pnl(predicted, before, actual)
        Then the result is 0
        """
        result = calculate_pnl(
            predicted_price=Decimal("66000"),
            price_at_prediction=Decimal("67000"),
            actual_price=Decimal("68000"),
        )
        assert result == Decimal("0.00")

    def test_all_prices_equal(self):
        """Edge case: All prices are equal → 0 PnL."""
        result = calculate_pnl(
            predicted_price=Decimal("67000"),
            price_at_prediction=Decimal("67000"),
            actual_price=Decimal("67000"),
        )
        assert result == Decimal("0.00")

    def test_predicted_equal_to_before(self):
        """Edge case: predicted == before (no directional signal) → 0 PnL."""
        result = calculate_pnl(
            predicted_price=Decimal("67000"),
            price_at_prediction=Decimal("67000"),
            actual_price=Decimal("68000"),
        )
        assert result == Decimal("0.00")

    def test_large_profit(self):
        """Edge case: Large price movement upward → large profit."""
        result = calculate_pnl(
            predicted_price=Decimal("70000"),
            price_at_prediction=Decimal("60000"),
            actual_price=Decimal("75000"),
        )
        assert result == Decimal("15000.00")

    def test_large_loss(self):
        """Edge case: Large price movement downward after long → large loss."""
        result = calculate_pnl(
            predicted_price=Decimal("70000"),
            price_at_prediction=Decimal("60000"),
            actual_price=Decimal("50000"),
        )
        assert result == Decimal("-10000.00")

    def test_small_price_differences(self):
        """Edge case: Very small price movements → small PnL."""
        result = calculate_pnl(
            predicted_price=Decimal("67000.50"),
            price_at_prediction=Decimal("67000.00"),
            actual_price=Decimal("67000.25"),
        )
        assert result == Decimal("0.25")

    def test_decimal_precision(self):
        """Edge case: Ensure Decimal precision is maintained."""
        result = calculate_pnl(
            predicted_price=Decimal("67123.456"),
            price_at_prediction=Decimal("67000.123"),
            actual_price=Decimal("67500.789"),
        )
        # Should be actual - before = 67500.789 - 67000.123 = 500.666
        assert result == Decimal("500.666")


class TestCalculatePnlLongShort:
    """Test calculate_pnl_long_short function with Gherkin scenarios from US-017."""

    def test_predicted_up_actual_up_long_profit(self):
        """
        Scenario: Calculate long/short symmetric PnL - Long profit
        Given predicted_price=67000 (UP)
        And price_at_prediction=66000
        And actual_price=67500
        When the evaluator calculates pnl_long_short
        Then it returns 1500 (long profit)
        """
        result = calculate_pnl_long_short(
            predicted_price=Decimal("67000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("67500"),
        )
        assert result == Decimal("1500.00")

    def test_predicted_down_actual_down_short_profit(self):
        """
        Scenario: Calculate long/short symmetric PnL - Short profit
        Given predicted_price=65000 (DOWN)
        And price_at_prediction=66000
        And actual_price=64000
        When the evaluator calculates pnl_long_short
        Then it returns 2000 (short profit: 66000 - 64000)
        And the strategy is "long if UP, short if DOWN"
        """
        result = calculate_pnl_long_short(
            predicted_price=Decimal("65000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("64000"),
        )
        assert result == Decimal("2000.00")

    def test_predicted_up_actual_down_long_loss(self):
        """
        Scenario: Long position, price goes down → loss
        Given predicted_price=67000 (UP)
        And price_at_prediction=66000
        And actual_price=65000
        When the evaluator calculates pnl_long_short
        Then it returns -1000 (long loss)
        """
        result = calculate_pnl_long_short(
            predicted_price=Decimal("67000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("65000"),
        )
        assert result == Decimal("-1000.00")

    def test_predicted_down_actual_up_short_loss(self):
        """
        Scenario: Short position, price goes up → loss
        Given predicted_price=65000 (DOWN)
        And price_at_prediction=66000
        And actual_price=67000
        When the evaluator calculates pnl_long_short
        Then it returns -1000 (short loss: 66000 - 67000)
        """
        result = calculate_pnl_long_short(
            predicted_price=Decimal("65000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("67000"),
        )
        assert result == Decimal("-1000.00")

    def test_all_prices_equal(self):
        """Edge case: All prices equal → 0 PnL."""
        result = calculate_pnl_long_short(
            predicted_price=Decimal("66000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("66000"),
        )
        assert result == Decimal("0.00")


class TestCalculatePnlThreshold:
    """Test calculate_pnl_threshold function with Gherkin scenarios from US-017."""

    def test_below_threshold_no_trade(self):
        """
        Scenario: Calculate PnL with threshold (only trade if predicted change > 1%)
        Given price_at_prediction=66000
        And predicted_price=66500 (only 0.76% change)
        When the evaluator calculates pnl_threshold with threshold=1.0
        Then it returns 0 (change too small, no trade)
        """
        result = calculate_pnl_threshold(
            predicted_price=Decimal("66500"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("67000"),
            threshold=Decimal("1.0"),
        )
        assert result == Decimal("0.00")

    def test_above_threshold_long_profit(self):
        """
        Scenario Outline: Calculate PnL with threshold - above threshold UP
        Given price_at_prediction=66000
        And predicted_price=67000 (1.5% change)
        And actual_price=67500
        When the evaluator calculates pnl_threshold with threshold=1.0
        Then pnl_threshold=1500 (1.5% change, above threshold)
        """
        result = calculate_pnl_threshold(
            predicted_price=Decimal("67000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("67500"),
            threshold=Decimal("1.0"),
        )
        assert result == Decimal("1500.00")

    def test_above_threshold_short_profit(self):
        """
        Scenario Outline: Calculate PnL with threshold - above threshold DOWN
        Given price_at_prediction=66000
        And predicted_price=65000 (1.5% change down)
        And actual_price=64000
        When the evaluator calculates pnl_threshold with threshold=1.0
        Then pnl_threshold=2000 (1.5% change down, short profit)
        """
        result = calculate_pnl_threshold(
            predicted_price=Decimal("65000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("64000"),
            threshold=Decimal("1.0"),
        )
        assert result == Decimal("2000.00")

    def test_exactly_at_threshold(self):
        """Edge case: Exactly at 1% threshold → trade executes (>= threshold)."""
        # 1% of 66000 = 660, so 66660 is exactly 1%
        result = calculate_pnl_threshold(
            predicted_price=Decimal("66660"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("67000"),
            threshold=Decimal("1.0"),
        )
        # At exactly 1%, trade executes (change_pct >= threshold)
        assert result == Decimal("1000.00")

    def test_custom_threshold_2_percent(self):
        """Edge case: Custom threshold of 2% filters out 1.5% moves."""
        result = calculate_pnl_threshold(
            predicted_price=Decimal("67000"),  # 1.5% change
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("67500"),
            threshold=Decimal("2.0"),
        )
        assert result == Decimal("0.00")

    def test_custom_threshold_0_5_percent(self):
        """Edge case: Lower threshold 0.5% allows 0.76% move."""
        result = calculate_pnl_threshold(
            predicted_price=Decimal("66500"),  # 0.76% change
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("67000"),
            threshold=Decimal("0.5"),
        )
        assert result == Decimal("1000.00")


class TestCalculatePnlRealistic:
    """Test calculate_pnl_realistic function with Gherkin scenarios from US-017."""

    def test_realistic_pnl_with_fees(self):
        """
        Scenario: Calculate realistic PnL with fees and stop-loss
        Given trading fee is 0.1% per trade (entry + exit)
        And stop_loss is 2% of price_at_prediction
        And predicted_price=67000 (long position)
        And actual_price=67500
        When the evaluator calculates pnl_realistic
        Then the gross PnL is 1500
        And fees are 132 (66000 * 0.001 * 2)
        And pnl_realistic=1368 (1500 - 132)
        """
        result = calculate_pnl_realistic(
            predicted_price=Decimal("67000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("67500"),
        )
        # Gross PnL: 1500, Fees: 66000 * 0.001 * 2 = 132
        # Net: 1500 - 132 = 1368
        assert result == Decimal("1368.00")

    def test_realistic_pnl_applies_stop_loss(self):
        """
        Scenario: Realistic PnL applies stop-loss when loss exceeds limit
        Given predicted_price=67000 (long position)
        And actual_price=63000 (loss of 3000 = 4.5%)
        And stop_loss is 2% (max loss = 1320)
        When the evaluator calculates pnl_realistic
        Then the loss is capped at -1320
        And fees are applied (132)
        And pnl_realistic=-1452
        """
        result = calculate_pnl_realistic(
            predicted_price=Decimal("67000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("63000"),
        )
        # Gross loss would be -3000, but stop-loss caps at -1320 (2%)
        # Fees: 132
        # Net: -1320 - 132 = -1452
        assert result == Decimal("-1452.00")

    def test_realistic_pnl_small_loss_no_stop_loss(self):
        """
        Scenario: Small loss below stop-loss threshold
        Given predicted_price=67000 (long)
        And actual_price=65500 (loss of 500 = 0.76%)
        When the evaluator calculates pnl_realistic
        Then the loss is NOT capped (below 2%)
        And fees are applied
        And pnl_realistic=-632 (-500 - 132)
        """
        result = calculate_pnl_realistic(
            predicted_price=Decimal("67000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("65500"),
        )
        # Gross loss: -500, Fees: 132
        # Net: -500 - 132 = -632
        assert result == Decimal("-632.00")

    def test_realistic_pnl_short_profit(self):
        """Edge case: Short position profit with fees."""
        result = calculate_pnl_realistic(
            predicted_price=Decimal("65000"),  # Predicted DOWN
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("64000"),
        )
        # Gross short profit: 2000, Fees: 132
        # Net: 2000 - 132 = 1868
        assert result == Decimal("1868.00")

    def test_realistic_pnl_stop_loss_on_short(self):
        """Edge case: Short position with stop-loss triggered."""
        result = calculate_pnl_realistic(
            predicted_price=Decimal("65000"),  # Predicted DOWN
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("70000"),  # Price goes way up
        )
        # Gross short loss would be -4000, but stop-loss caps at -1320
        # Fees: 132
        # Net: -1320 - 132 = -1452
        assert result == Decimal("-1452.00")

    def test_realistic_pnl_custom_fees(self):
        """Edge case: Custom fee percentage."""
        result = calculate_pnl_realistic(
            predicted_price=Decimal("67000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("67500"),
            fee_pct=Decimal("0.2"),  # 0.2% instead of 0.1%
        )
        # Gross PnL: 1500, Fees: 66000 * 0.002 * 2 = 264
        # Net: 1500 - 264 = 1236
        assert result == Decimal("1236.00")

    def test_realistic_pnl_custom_stop_loss(self):
        """Edge case: Custom stop-loss percentage."""
        result = calculate_pnl_realistic(
            predicted_price=Decimal("67000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("63000"),
            stop_loss_pct=Decimal("3.0"),  # 3% instead of 2%
        )
        # Gross loss: -3000, Stop-loss: 66000 * 0.03 = -1980
        # Loss is capped at -1980, Fees: 132
        # Net: -1980 - 132 = -2112
        assert result == Decimal("-2112.00")


# ============================================================================
# Validation Split and MAPE Tests (US-024)
# ============================================================================


class TestSplitTrainValidation:
    """Test split_train_validation function for model training."""

    def test_split_train_validation_correct_sizes(self):
        """Test that split returns correct array sizes (70/20/10)."""
        # 100 data points → 70 train, 20 val, 10 buffer (discarded)
        prices = np.arange(100, dtype=float) + 50000  # 50000-50099
        train, val = split_train_validation(prices)

        assert len(train) == 70
        assert len(val) == 20

    def test_split_train_validation_chronological_order(self):
        """Test that chronological order is preserved in splits."""
        prices = np.array([50000, 51000, 52000, 53000, 54000,
                          55000, 56000, 57000, 58000, 59000], dtype=float)
        train, val = split_train_validation(prices, train_pct=0.7, val_pct=0.2)

        # Train: first 70% (7 items)
        assert len(train) == 7
        assert train[0] == 50000
        assert train[-1] == 56000

        # Val: next 20% (2 items)
        assert len(val) == 2
        assert val[0] == 57000
        assert val[-1] == 58000

    def test_split_train_validation_raises_on_invalid_percentages(self):
        """Test that ValueError is raised if train_pct + val_pct > 1.0."""
        prices = np.arange(100, dtype=float)

        with pytest.raises(ValueError, match="must be <= 1.0"):
            split_train_validation(prices, train_pct=0.8, val_pct=0.5)

    def test_split_train_validation_raises_on_insufficient_data(self):
        """Test that ValueError is raised if < 10 data points."""
        prices = np.array([50000, 51000], dtype=float)  # Only 2 points

        with pytest.raises(ValueError, match="Need at least 10 data points"):
            split_train_validation(prices)

    def test_split_train_validation_custom_percentages(self):
        """Test split with custom train/val percentages."""
        prices = np.arange(100, dtype=float)
        train, val = split_train_validation(prices, train_pct=0.6, val_pct=0.3)

        assert len(train) == 60
        assert len(val) == 30  # Remaining 10% discarded

    def test_split_train_validation_returns_numpy_arrays(self):
        """Test that returned values are numpy arrays."""
        prices = np.arange(100, dtype=float)
        train, val = split_train_validation(prices)

        assert isinstance(train, np.ndarray)
        assert isinstance(val, np.ndarray)


class TestCalculateMAPE:
    """Test calculate_mape function for validation error calculation."""

    def test_calculate_mape_correct_value(self):
        """Test MAPE calculation with known values."""
        y_true = np.array([50000, 51000, 52000], dtype=float)
        y_pred = np.array([50500, 50800, 52100], dtype=float)

        mape = calculate_mape(y_true, y_pred)

        # Errors: |50000-50500|/50000 = 1%,
        #         |51000-50800|/51000 = 0.39%,
        #         |52000-52100|/52000 = 0.19%
        # Mean: ~0.53% ... wait let me recalculate
        # (500/50000 + 200/51000 + 100/52000) / 3 * 100
        # = (0.01 + 0.00392 + 0.00192) / 3 * 100
        # = 0.01584 / 3 * 100 = 0.528%
        assert abs(mape - 0.528) < 0.01  # Allow small floating point error

    def test_calculate_mape_handles_zeros(self):
        """Test that MAPE raises error when y_true contains zeros."""
        y_true = np.array([50000, 0, 52000], dtype=float)
        y_pred = np.array([50500, 50800, 52100], dtype=float)

        with pytest.raises(ValueError, match="y_true contains zeros"):
            calculate_mape(y_true, y_pred)

    def test_calculate_mape_perfect_prediction(self):
        """Test MAPE with perfect predictions (error = 0)."""
        y_true = np.array([50000, 51000, 52000], dtype=float)
        y_pred = np.array([50000, 51000, 52000], dtype=float)

        mape = calculate_mape(y_true, y_pred)

        assert mape == 0.0

    def test_calculate_mape_raises_on_length_mismatch(self):
        """Test that ValueError is raised if array lengths differ."""
        y_true = np.array([50000, 51000], dtype=float)
        y_pred = np.array([50500, 50800, 52100], dtype=float)

        with pytest.raises(ValueError, match="Arrays must have same length"):
            calculate_mape(y_true, y_pred)

    def test_calculate_mape_raises_on_empty_arrays(self):
        """Test that ValueError is raised for empty arrays."""
        y_true = np.array([], dtype=float)
        y_pred = np.array([], dtype=float)

        with pytest.raises(ValueError, match="Cannot calculate MAPE on empty"):
            calculate_mape(y_true, y_pred)

    def test_calculate_mape_returns_percentage(self):
        """Test that MAPE is returned on 0-100 scale."""
        y_true = np.array([50000, 50000], dtype=float)
        y_pred = np.array([51000, 49000], dtype=float)

        mape = calculate_mape(y_true, y_pred)

        # Errors: 1000/50000 = 2%, 1000/50000 = 2%
        # Mean: 2%
        assert mape == 2.0
        assert 0 <= mape <= 100  # Should be percentage
