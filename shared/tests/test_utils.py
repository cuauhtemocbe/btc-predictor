"""
Tests for utility functions.

Covers all Gherkin scenarios from US-013:
- Calculate PnL for different prediction/outcome combinations
"""

from datetime import date
from decimal import Decimal

import numpy as np
import pytest

from shared.utils import (
    calculate_accuracy,
    calculate_mape,
    calculate_max_drawdown,
    calculate_model_mape,
    calculate_pnl,
    calculate_pnl_long_short,
    calculate_pnl_realistic,
    calculate_pnl_threshold,
    calculate_sharpe_ratio,
    calculate_total_pnl,
    calculate_win_rate,
    get_all_models_metrics,
    get_cumulative_pnl,
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
        prices = np.array(
            [50000, 51000, 52000, 53000, 54000, 55000, 56000, 57000, 58000, 59000],
            dtype=float,
        )
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


# ============================================================================
# Tests for Model Metrics Functions (US-026)
# ============================================================================


class TestCalculateAccuracy:
    """Test calculate_accuracy function for model comparison dashboard."""

    def test_accuracy_with_all_correct_predictions(
        self, db_session, sample_model, evaluated_prediction
    ):
        """Test 100% accuracy when all predictions are correct."""
        model = sample_model(name="linear_v1")

        # Create 3 correct predictions
        for i in range(3):
            evaluated_prediction(
                model_id=model.id,
                predicted_for=date(2024, 5, 10 + i),
                direction_correct=True,
            )

        accuracy = calculate_accuracy(db_session, model.id)

        assert accuracy == 1.0  # 100%

    def test_accuracy_with_mixed_predictions(
        self, db_session, sample_model, evaluated_prediction
    ):
        """Test accuracy calculation with mix of correct/incorrect predictions."""
        model = sample_model(name="lstm_v1")

        # Create 5 predictions: 3 correct, 2 incorrect
        for i in range(3):
            evaluated_prediction(
                model_id=model.id,
                predicted_for=date(2024, 5, 1 + i),
                direction_correct=True,
            )
        for i in range(2):
            evaluated_prediction(
                model_id=model.id,
                predicted_for=date(2024, 5, 4 + i),
                direction_correct=False,
            )

        accuracy = calculate_accuracy(db_session, model.id)

        assert accuracy == 0.6  # 60% (3/5)

    def test_accuracy_returns_none_for_no_evaluated_predictions(
        self, db_session, sample_model, sample_prediction
    ):
        """Test that None is returned when no evaluated predictions exist."""
        model = sample_model(name="xgboost_v1")

        # Create unevaluated predictions (actual_price = NULL)
        sample_prediction(model_id=model.id, predicted_for=date(2024, 5, 1))
        sample_prediction(model_id=model.id, predicted_for=date(2024, 5, 2))

        accuracy = calculate_accuracy(db_session, model.id)

        assert accuracy is None

    def test_accuracy_with_date_filter(
        self, db_session, sample_model, evaluated_prediction
    ):
        """Test accuracy calculation with date range filter."""
        model = sample_model(name="arima_v1")

        # Predictions outside range
        evaluated_prediction(
            model_id=model.id, predicted_for=date(2024, 4, 28), direction_correct=False
        )
        evaluated_prediction(
            model_id=model.id, predicted_for=date(2024, 4, 29), direction_correct=False
        )

        # Predictions inside range (May 1-10): 2 correct
        for i in range(2):
            evaluated_prediction(
                model_id=model.id,
                predicted_for=date(2024, 5, 1 + i),
                direction_correct=True,
            )

        # Predictions outside range
        evaluated_prediction(
            model_id=model.id, predicted_for=date(2024, 5, 15), direction_correct=False
        )

        accuracy = calculate_accuracy(
            db_session,
            model.id,
            start_date=date(2024, 5, 1),
            end_date=date(2024, 5, 10),
        )

        assert accuracy == 1.0  # 100% for May 1-10 only


class TestCalculateModelMape:
    """Test calculate_model_mape function."""

    def test_mape_calculation_from_database(
        self, db_session, sample_model, evaluated_prediction
    ):
        """Test MAPE calculation from database predictions."""
        model = sample_model(name="linear_v1")

        # Create predictions with known errors
        # Error %: 2%, 1.5%, 3%
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 1),
            predicted_price=Decimal("67000"),
            actual_price=Decimal("68000"),  # error: 1000/68000 = 1.47%
        )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 2),
            predicted_price=Decimal("68000"),
            actual_price=Decimal("67000"),  # error: 1000/67000 = 1.49%
        )

        mape = calculate_model_mape(db_session, model.id)

        # Expected: (1.47 + 1.49) / 2 ≈ 1.48%
        assert mape is not None
        assert 1.4 < mape < 1.6

    def test_mape_returns_none_for_no_predictions(self, db_session, sample_model):
        """Test that None is returned when no predictions exist."""
        model = sample_model(name="lstm_v1")

        mape = calculate_model_mape(db_session, model.id)

        assert mape is None


class TestCalculateTotalPnl:
    """Test calculate_total_pnl function."""

    def test_total_pnl_sums_all_predictions(
        self, db_session, sample_model, evaluated_prediction
    ):
        """Test total PnL calculation sums all predictions."""
        model = sample_model(name="xgboost_v1")

        # Create predictions with different PnLs
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 1),
            pnl_simulated=Decimal("100.00"),
        )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 2),
            pnl_simulated=Decimal("-50.00"),
        )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 3),
            pnl_simulated=Decimal("200.00"),
        )

        total_pnl = calculate_total_pnl(db_session, model.id)

        assert total_pnl == 250.0  # 100 - 50 + 200

    def test_total_pnl_returns_none_for_no_predictions(self, db_session, sample_model):
        """Test that None is returned when no predictions exist."""
        model = sample_model(name="arima_v1")

        total_pnl = calculate_total_pnl(db_session, model.id)

        assert total_pnl is None

    def test_total_pnl_with_date_filter(
        self, db_session, sample_model, evaluated_prediction
    ):
        """Test total PnL with date range filter."""
        model = sample_model(name="linear_v1")

        # Outside range
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 4, 30),
            pnl_simulated=Decimal("1000.00"),
        )

        # Inside range
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 1),
            pnl_simulated=Decimal("100.00"),
        )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 2),
            pnl_simulated=Decimal("50.00"),
        )

        # Outside range
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 10),
            pnl_simulated=Decimal("2000.00"),
        )

        total_pnl = calculate_total_pnl(
            db_session, model.id, start_date=date(2024, 5, 1), end_date=date(2024, 5, 5)
        )

        assert total_pnl == 150.0  # Only May 1-5


class TestCalculateWinRate:
    """Test calculate_win_rate function."""

    def test_win_rate_calculation(self, db_session, sample_model, evaluated_prediction):
        """Test win rate calculation: % of positive PnL predictions."""
        model = sample_model(name="lstm_v1")

        # Create 5 predictions: 3 wins, 2 losses
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 1),
            pnl_simulated=Decimal("100.00"),
        )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 2),
            pnl_simulated=Decimal("50.00"),
        )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 3),
            pnl_simulated=Decimal("-30.00"),
        )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 4),
            pnl_simulated=Decimal("150.00"),
        )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 5),
            pnl_simulated=Decimal("-20.00"),
        )

        win_rate = calculate_win_rate(db_session, model.id)

        assert win_rate == 0.6  # 60% (3/5)

    def test_win_rate_with_zero_pnl(
        self, db_session, sample_model, evaluated_prediction
    ):
        """Test that zero PnL counts as a loss."""
        model = sample_model(name="xgboost_v1")

        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 1),
            pnl_simulated=Decimal("100.00"),
        )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 2),
            pnl_simulated=Decimal("0.00"),  # No trade
        )

        win_rate = calculate_win_rate(db_session, model.id)

        assert win_rate == 0.5  # 50% (1 win, 1 zero)


class TestCalculateSharpeRatio:
    """Test calculate_sharpe_ratio function."""

    def test_sharpe_ratio_calculation(
        self, db_session, sample_model, evaluated_prediction
    ):
        """Test Sharpe ratio calculation with multiple predictions."""
        model = sample_model(name="arima_v1")

        # Create predictions with varying returns
        for i, pnl in enumerate([100, -50, 150, 80, -30]):
            evaluated_prediction(
                model_id=model.id,
                predicted_for=date(2024, 5, 1 + i),
                price_at_prediction=Decimal("67000.00"),
                pnl_simulated=Decimal(str(pnl)),
            )

        sharpe = calculate_sharpe_ratio(db_session, model.id)

        # Should return a numeric value (can be positive or negative)
        assert sharpe is not None
        assert isinstance(sharpe, float)

    def test_sharpe_ratio_returns_none_for_insufficient_data(
        self, db_session, sample_model, evaluated_prediction
    ):
        """Test that None is returned when < 2 predictions."""
        model = sample_model(name="linear_v1")

        # Only 1 prediction
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 1),
            pnl_simulated=Decimal("100.00"),
        )

        sharpe = calculate_sharpe_ratio(db_session, model.id)

        assert sharpe is None  # Need at least 2 for stdev


class TestCalculateMaxDrawdown:
    """Test calculate_max_drawdown function."""

    def test_max_drawdown_calculation(
        self, db_session, sample_model, evaluated_prediction
    ):
        """Test max drawdown calculation."""
        model = sample_model(name="lstm_v1")

        # Create predictions with drawdown scenario
        # Cumulative: 100, 50, 200, 100, 80
        # Running max: 100, 100, 200, 200, 200
        # Drawdown: 0, -50, 0, -100, -120
        # Max drawdown: -120
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 1),
            pnl_simulated=Decimal("100.00"),
        )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 2),
            pnl_simulated=Decimal("-50.00"),
        )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 3),
            pnl_simulated=Decimal("150.00"),
        )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 4),
            pnl_simulated=Decimal("-100.00"),
        )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 5),
            pnl_simulated=Decimal("-20.00"),
        )

        max_dd = calculate_max_drawdown(db_session, model.id)

        assert max_dd == -120.0

    def test_max_drawdown_returns_none_for_no_predictions(
        self, db_session, sample_model
    ):
        """Test that None is returned when no predictions exist."""
        model = sample_model(name="xgboost_v1")

        max_dd = calculate_max_drawdown(db_session, model.id)

        assert max_dd is None


class TestGetCumulativePnl:
    """Test get_cumulative_pnl function."""

    def test_cumulative_pnl_time_series(
        self, db_session, sample_model, evaluated_prediction
    ):
        """Test cumulative PnL time series generation."""
        model = sample_model(name="linear_v1")

        # Create predictions
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 1),
            pnl_simulated=Decimal("100.00"),
        )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 2),
            pnl_simulated=Decimal("-50.00"),
        )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 3),
            pnl_simulated=Decimal("200.00"),
        )

        cumulative = get_cumulative_pnl(db_session, model.id)

        assert len(cumulative) == 3
        assert cumulative[0] == {"date": "2024-05-01", "cumulative_pnl": 100.0}
        assert cumulative[1] == {"date": "2024-05-02", "cumulative_pnl": 50.0}
        assert cumulative[2] == {"date": "2024-05-03", "cumulative_pnl": 250.0}

    def test_cumulative_pnl_returns_empty_list_for_no_predictions(
        self, db_session, sample_model
    ):
        """Test that empty list is returned when no predictions exist."""
        model = sample_model(name="arima_v1")

        cumulative = get_cumulative_pnl(db_session, model.id)

        assert cumulative == []


class TestGetAllModelsMetrics:
    """Test get_all_models_metrics function."""

    def test_get_metrics_for_multiple_models(
        self, db_session, sample_model, evaluated_prediction
    ):
        """Test getting metrics for all models in one call."""
        # Create 2 models with predictions
        model1 = sample_model(name="linear_v1", version="1.0.0", is_active=True)
        model2 = sample_model(name="lstm_v1", version="1.0.0", is_active=False)

        # Model 1: 2 predictions
        evaluated_prediction(
            model_id=model1.id,
            predicted_for=date(2024, 5, 1),
            direction_correct=True,
            pnl_simulated=Decimal("100.00"),
        )
        evaluated_prediction(
            model_id=model1.id,
            predicted_for=date(2024, 5, 2),
            direction_correct=True,
            pnl_simulated=Decimal("50.00"),
        )

        # Model 2: 1 prediction
        evaluated_prediction(
            model_id=model2.id,
            predicted_for=date(2024, 5, 1),
            direction_correct=False,
            pnl_simulated=Decimal("-30.00"),
        )

        metrics = get_all_models_metrics(db_session)

        assert len(metrics) == 2

        # Check model 1 metrics
        m1 = next(m for m in metrics if m["name"] == "linear_v1")
        assert m1["predictions_count"] == 2
        assert m1["accuracy"] == 1.0
        assert m1["total_pnl"] == 150.0
        assert m1["is_active"] is True

        # Check model 2 metrics
        m2 = next(m for m in metrics if m["name"] == "lstm_v1")
        assert m2["predictions_count"] == 1
        assert m2["accuracy"] == 0.0
        assert m2["total_pnl"] == -30.0
        assert m2["is_active"] is False

    def test_get_metrics_with_no_models(self, db_session):
        """Test that empty list is returned when no models exist."""
        metrics = get_all_models_metrics(db_session)

        assert metrics == []

    def test_get_metrics_handles_models_without_predictions(
        self, db_session, sample_model
    ):
        """Test that models without predictions show None for metrics."""
        sample_model(name="xgboost_v1")

        metrics = get_all_models_metrics(db_session)

        assert len(metrics) == 1
        assert metrics[0]["predictions_count"] == 0
        assert metrics[0]["accuracy"] is None
        assert metrics[0]["total_pnl"] is None


class TestMetricsRespectTimeframe:
    """
    Timeframe-separated performance metrics (issue #67).

    A model can have both daily (1d) and weekly (1w) evaluated predictions
    in the same date range; every metric function must be able to isolate
    one timeframe instead of always mixing them.
    """

    def _seed_daily_and_weekly(self, sample_model, evaluated_prediction):
        model = sample_model(name="linear_v1")

        # Daily: 3 correct, 1 incorrect, total pnl = 100+100+100-50 = 250
        for i in range(3):
            evaluated_prediction(
                model_id=model.id,
                predicted_for=date(2024, 5, 1 + i),
                direction_correct=True,
                pnl_simulated=Decimal("100.00"),
                timeframe="1d",
            )
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 4),
            direction_correct=False,
            pnl_simulated=Decimal("-50.00"),
            timeframe="1d",
        )

        # Weekly: 1 correct, total pnl = 1000
        evaluated_prediction(
            model_id=model.id,
            predicted_for=date(2024, 5, 8),
            direction_correct=True,
            pnl_simulated=Decimal("1000.00"),
            timeframe="1w",
        )

        return model

    def test_daily_metrics_include_only_daily_predictions(
        self, db_session, sample_model, evaluated_prediction
    ):
        """
        Given a model has evaluated daily and weekly predictions in the
        same date range
        When daily metrics are requested for timeframe "1d"
        Then accuracy, total PnL, and win rate use only daily predictions
        """
        model = self._seed_daily_and_weekly(sample_model, evaluated_prediction)

        assert calculate_accuracy(db_session, model.id, timeframe="1d") == 0.75
        assert calculate_total_pnl(db_session, model.id, timeframe="1d") == 250.0
        assert calculate_win_rate(db_session, model.id, timeframe="1d") == 0.75

    def test_weekly_metrics_include_only_weekly_predictions(
        self, db_session, sample_model, evaluated_prediction
    ):
        """
        Given the same mixed data
        When weekly metrics are requested for timeframe "1w"
        Then accuracy, total PnL, and win rate use only weekly predictions
        """
        model = self._seed_daily_and_weekly(sample_model, evaluated_prediction)

        assert calculate_accuracy(db_session, model.id, timeframe="1w") == 1.0
        assert calculate_total_pnl(db_session, model.id, timeframe="1w") == 1000.0
        assert calculate_win_rate(db_session, model.id, timeframe="1w") == 1.0

    def test_missing_timeframe_mixes_both(
        self, db_session, sample_model, evaluated_prediction
    ):
        """
        Without a timeframe filter, utils functions mix every timeframe --
        the API layer is what applies DEFAULT_TIMEFRAME (see
        api-service/tests), not these lower-level functions themselves.
        """
        model = self._seed_daily_and_weekly(sample_model, evaluated_prediction)

        assert calculate_total_pnl(db_session, model.id) == 1250.0  # 250 + 1000

    def test_cumulative_pnl_does_not_mix_timeframes(
        self, db_session, sample_model, evaluated_prediction
    ):
        """
        Scenario: Cumulative PnL does not mix timeframes

        Given a model has daily and weekly PnL records
        When cumulative PnL is requested for one timeframe
        Then the returned series contains only records from that timeframe
        """
        model = self._seed_daily_and_weekly(sample_model, evaluated_prediction)

        daily_series = get_cumulative_pnl(db_session, model.id, timeframe="1d")
        weekly_series = get_cumulative_pnl(db_session, model.id, timeframe="1w")

        assert len(daily_series) == 4
        assert daily_series[-1]["cumulative_pnl"] == 250.0

        assert len(weekly_series) == 1
        assert weekly_series[-1]["cumulative_pnl"] == 1000.0

    def test_sharpe_and_drawdown_respect_timeframe(
        self, db_session, sample_model, evaluated_prediction
    ):
        """Sharpe ratio and max drawdown must also isolate one timeframe."""
        model = self._seed_daily_and_weekly(sample_model, evaluated_prediction)

        # Sharpe needs >= 2 data points; daily has 4, weekly has only 1
        daily_sharpe = calculate_sharpe_ratio(db_session, model.id, timeframe="1d")
        weekly_sharpe = calculate_sharpe_ratio(db_session, model.id, timeframe="1w")
        assert daily_sharpe is not None
        assert weekly_sharpe is None  # insufficient data points for that timeframe

        daily_dd = calculate_max_drawdown(db_session, model.id, timeframe="1d")
        weekly_dd = calculate_max_drawdown(db_session, model.id, timeframe="1w")
        assert daily_dd is not None
        assert weekly_dd == 0.0  # single positive data point, no drawdown

    def test_get_all_models_metrics_respects_timeframe(
        self, db_session, sample_model, evaluated_prediction
    ):
        """get_all_models_metrics() must thread timeframe through every metric."""
        model = self._seed_daily_and_weekly(sample_model, evaluated_prediction)

        daily_metrics = get_all_models_metrics(db_session, timeframe="1d")
        weekly_metrics = get_all_models_metrics(db_session, timeframe="1w")

        m1_daily = next(m for m in daily_metrics if m["id"] == model.id)
        m1_weekly = next(m for m in weekly_metrics if m["id"] == model.id)

        assert m1_daily["predictions_count"] == 4
        assert m1_daily["total_pnl"] == 250.0

        assert m1_weekly["predictions_count"] == 1
        assert m1_weekly["total_pnl"] == 1000.0
