"""
Tests for utility functions.

Covers all Gherkin scenarios from US-013:
- Calculate PnL for different prediction/outcome combinations
"""

import math
import statistics
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session

from shared.db.models import Model, Prediction
from shared.utils import (
    calculate_pnl,
    calculate_pnl_long_short,
    calculate_pnl_realistic,
    calculate_pnl_threshold,
    get_all_models_metrics,
    get_family_cumulative_pnl,
    utc_now,
    utc_today,
)


class TestCalculatePnl:
    """Test calculate_pnl function with Gherkin scenarios and edge cases."""

    def test_predicted_up_actual_up_profit(self) -> None:
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

    def test_predicted_up_actual_down_loss(self) -> None:
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

    def test_predicted_down_actual_down_no_trade(self) -> None:
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

    def test_predicted_down_actual_up_no_trade(self) -> None:
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

    def test_all_prices_equal(self) -> None:
        """Edge case: All prices are equal → 0 PnL."""
        result = calculate_pnl(
            predicted_price=Decimal("67000"),
            price_at_prediction=Decimal("67000"),
            actual_price=Decimal("67000"),
        )
        assert result == Decimal("0.00")

    def test_predicted_equal_to_before(self) -> None:
        """Edge case: predicted == before (no directional signal) → 0 PnL."""
        result = calculate_pnl(
            predicted_price=Decimal("67000"),
            price_at_prediction=Decimal("67000"),
            actual_price=Decimal("68000"),
        )
        assert result == Decimal("0.00")

    def test_large_profit(self) -> None:
        """Edge case: Large price movement upward → large profit."""
        result = calculate_pnl(
            predicted_price=Decimal("70000"),
            price_at_prediction=Decimal("60000"),
            actual_price=Decimal("75000"),
        )
        assert result == Decimal("15000.00")

    def test_large_loss(self) -> None:
        """Edge case: Large price movement downward after long → large loss."""
        result = calculate_pnl(
            predicted_price=Decimal("70000"),
            price_at_prediction=Decimal("60000"),
            actual_price=Decimal("50000"),
        )
        assert result == Decimal("-10000.00")

    def test_small_price_differences(self) -> None:
        """Edge case: Very small price movements → small PnL."""
        result = calculate_pnl(
            predicted_price=Decimal("67000.50"),
            price_at_prediction=Decimal("67000.00"),
            actual_price=Decimal("67000.25"),
        )
        assert result == Decimal("0.25")

    def test_decimal_precision(self) -> None:
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

    def test_predicted_up_actual_up_long_profit(self) -> None:
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

    def test_predicted_down_actual_down_short_profit(self) -> None:
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

    def test_predicted_up_actual_down_long_loss(self) -> None:
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

    def test_predicted_down_actual_up_short_loss(self) -> None:
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

    def test_all_prices_equal(self) -> None:
        """Edge case: All prices equal → 0 PnL."""
        result = calculate_pnl_long_short(
            predicted_price=Decimal("66000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("66000"),
        )
        assert result == Decimal("0.00")


class TestCalculatePnlThreshold:
    """Test calculate_pnl_threshold function with Gherkin scenarios from US-017."""

    def test_below_threshold_no_trade(self) -> None:
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

    def test_above_threshold_long_profit(self) -> None:
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

    def test_above_threshold_short_profit(self) -> None:
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

    def test_exactly_at_threshold(self) -> None:
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

    def test_custom_threshold_2_percent(self) -> None:
        """Edge case: Custom threshold of 2% filters out 1.5% moves."""
        result = calculate_pnl_threshold(
            predicted_price=Decimal("67000"),  # 1.5% change
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("67500"),
            threshold=Decimal("2.0"),
        )
        assert result == Decimal("0.00")

    def test_custom_threshold_0_5_percent(self) -> None:
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

    def test_realistic_pnl_with_fees(self) -> None:
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

    def test_realistic_pnl_applies_stop_loss(self) -> None:
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

    def test_realistic_pnl_small_loss_no_stop_loss(self) -> None:
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

    def test_realistic_pnl_short_profit(self) -> None:
        """Edge case: Short position profit with fees."""
        result = calculate_pnl_realistic(
            predicted_price=Decimal("65000"),  # Predicted DOWN
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("64000"),
        )
        # Gross short profit: 2000, Fees: 132
        # Net: 2000 - 132 = 1868
        assert result == Decimal("1868.00")

    def test_realistic_pnl_stop_loss_on_short(self) -> None:
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

    def test_realistic_pnl_custom_fees(self) -> None:
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

    def test_realistic_pnl_custom_stop_loss(self) -> None:
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
# Tests for Model Metrics Functions (US-026)
# ============================================================================


def _family_row(db: Session, model: Model, **filters: Any) -> dict[str, Any]:
    """The ``get_all_models_metrics`` row of the family ``model`` belongs to."""
    return next(m for m in get_all_models_metrics(db, **filters) if m["id"] == model.id)


class TestGetAllModelsMetrics:
    """Test get_all_models_metrics function."""

    def test_get_metrics_for_multiple_models(
        self,
        db_session: Session,
        sample_model: Callable[..., Model],
        evaluated_prediction: Callable[..., Prediction],
    ) -> None:
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
        m1 = next(m for m in metrics if m["name"] == "linear")
        assert m1["predictions_count"] == 2
        assert m1["accuracy"] == 1.0
        assert m1["total_pnl"] == 150.0
        assert m1["is_active"] is True

        # Check model 2 metrics
        m2 = next(m for m in metrics if m["name"] == "lstm")
        assert m2["predictions_count"] == 1
        assert m2["accuracy"] == 0.0
        assert m2["total_pnl"] == -30.0
        assert m2["is_active"] is False

    def test_get_metrics_with_no_models(self, db_session: Session) -> None:
        """Test that empty list is returned when no models exist."""
        metrics = get_all_models_metrics(db_session)

        assert metrics == []

    def test_get_metrics_handles_models_without_predictions(
        self, db_session: Session, sample_model: Callable[..., Model]
    ) -> None:
        """Test that models without predictions show None for metrics."""
        sample_model(name="xgboost_v1")

        metrics = get_all_models_metrics(db_session)

        assert len(metrics) == 1
        assert metrics[0]["predictions_count"] == 0
        assert metrics[0]["accuracy"] is None
        assert metrics[0]["total_pnl"] is None


class TestFamilyAggregation:
    """One row per (symbol, family, timeframe) over every version (#178)."""

    def test_versions_of_a_family_make_one_row_over_all_their_predictions(
        self,
        db_session: Session,
        sample_model: Callable[..., Model],
        evaluated_prediction: Callable[..., Prediction],
    ) -> None:
        old = sample_model(
            name="linear_v1",
            version="a",
            train_from=date(2024, 3, 1),
            train_to=date(2024, 4, 30),
            trained_at=datetime(2024, 5, 1, tzinfo=UTC),
        )
        new = sample_model(
            name="linear_v2",
            version="b",
            is_active=True,
            train_from=date(2024, 3, 1),
            train_to=date(2024, 5, 2),
            trained_at=datetime(2024, 5, 3, tzinfo=UTC),
        )
        # Created newest first: the order of the series is by date, not by version.
        evaluated_prediction(
            model_id=new.id, predicted_for=date(2024, 5, 3), pnl_simulated=Decimal("50")
        )
        evaluated_prediction(
            model_id=old.id,
            predicted_for=date(2024, 5, 2),
            direction_correct=False,
            pnl_simulated=Decimal("-100"),
        )
        evaluated_prediction(
            model_id=old.id, predicted_for=date(2024, 5, 1), pnl_simulated=Decimal("20")
        )

        (row,) = get_all_models_metrics(db_session)

        assert row["name"] == "linear"
        assert row["id"] == new.id
        assert row["version"] == "b"
        assert row["is_active"] is True
        assert row["versions_count"] == 2
        assert row["first_train_to"] == date(2024, 4, 30)
        assert row["last_train_to"] == date(2024, 5, 2)
        assert row["trained_at"] == datetime(2024, 5, 3, tzinfo=UTC)
        assert row["predictions_count"] == 3
        assert row["accuracy"] == round(2 / 3, 4)
        assert row["win_rate"] == round(2 / 3, 4)
        assert row["total_pnl"] == -30.0
        returns = [20 / 67000, -100 / 67000, 50 / 67000]
        assert row["sharpe_ratio"] == round(
            statistics.mean(returns) / statistics.stdev(returns) * math.sqrt(365), 2
        )
        # Equity 1 -> +0.03% -> -0.15% -> +0.07%: the fall is the second day's.
        assert row["max_drawdown_pct"] == round(-100 / 67000 * 100, 2)

    def test_the_representative_model_is_the_newest_when_none_is_active(
        self, db_session: Session, sample_model: Callable[..., Model]
    ) -> None:
        sample_model(name="linear_v1", trained_at=datetime(2024, 5, 1, tzinfo=UTC))
        newest = sample_model(
            name="linear_v2", version="2", trained_at=datetime(2024, 5, 2, tzinfo=UTC)
        )

        (row,) = get_all_models_metrics(db_session)

        assert row["id"] == newest.id
        assert row["is_active"] is False

    def test_families_and_symbols_stay_separate_rows(
        self,
        db_session: Session,
        sample_model: Callable[..., Model],
        evaluated_prediction: Callable[..., Prediction],
    ) -> None:
        btc = sample_model(name="linear_v1")
        gold = sample_model(name="linear_v1", version="g")
        gold.symbol = "PAXGUSDT"
        other = sample_model(name="other_v1", version="o")
        db_session.flush()
        for model in (btc, gold, other):
            evaluated_prediction(model_id=model.id, predicted_for=date(2024, 5, 1))

        rows = get_all_models_metrics(db_session)

        assert [(r["symbol"], r["name"]) for r in rows] == [
            ("BTCUSDT", "linear"),
            ("BTCUSDT", "other"),
            ("PAXGUSDT", "linear"),
        ]
        assert [r["predictions_count"] for r in rows] == [1, 1, 1]

    def test_date_filter_applies_to_the_whole_family(
        self,
        db_session: Session,
        sample_model: Callable[..., Model],
        evaluated_prediction: Callable[..., Prediction],
    ) -> None:
        one = sample_model(name="linear_v1")
        two = sample_model(name="linear_v2", version="2")
        for model, day in ((one, 1), (one, 2), (two, 3), (two, 4)):
            evaluated_prediction(model_id=model.id, predicted_for=date(2024, 5, day))

        (row,) = get_all_models_metrics(
            db_session, start_date=date(2024, 5, 2), end_date=date(2024, 5, 3)
        )

        assert row["predictions_count"] == 2

    def test_a_family_without_evaluated_predictions_has_no_metrics(
        self, db_session: Session, sample_model: Callable[..., Model]
    ) -> None:
        sample_model(name="linear_v1")

        (row,) = get_all_models_metrics(db_session, timeframe="1d")

        assert row["predictions_count"] == 0
        assert row["sharpe_ratio"] is None
        assert row["max_drawdown_pct"] is None
        assert row["baseline"] is None

    def test_cumulative_series_runs_over_every_version_in_date_order(
        self,
        db_session: Session,
        sample_model: Callable[..., Model],
        evaluated_prediction: Callable[..., Prediction],
    ) -> None:
        one = sample_model(name="linear_v1")
        two = sample_model(name="linear_v2", version="2")
        evaluated_prediction(
            model_id=two.id, predicted_for=date(2024, 5, 2), pnl_simulated=Decimal("5")
        )
        evaluated_prediction(
            model_id=one.id, predicted_for=date(2024, 5, 1), pnl_simulated=Decimal("10")
        )

        series = get_family_cumulative_pnl(db_session, timeframe="1d")

        assert series == {
            "linear": [
                {"date": "2024-05-01", "cumulative_pnl": 10.0},
                {"date": "2024-05-02", "cumulative_pnl": 15.0},
            ]
        }

    def test_cumulative_series_without_models_is_empty(
        self, db_session: Session
    ) -> None:
        assert get_family_cumulative_pnl(db_session) == {}


class TestMetricsForTheDailyTimeframe:
    """
    Metrics accept the daily timeframe filter (issues #67, #183).

    ``1d`` is the only timeframe the database accepts, so the filter selects
    every prediction; it must give the same figures as no filter.
    """

    def _seed_daily(
        self,
        sample_model: Callable[..., Model],
        evaluated_prediction: Callable[..., Prediction],
    ) -> Model:
        model = sample_model(name="linear_v1")

        # 3 correct, 1 incorrect, total pnl = 100+100+100-50 = 250
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
        return model

    def test_daily_metrics_use_the_daily_predictions(
        self,
        db_session: Session,
        sample_model: Callable[..., Model],
        evaluated_prediction: Callable[..., Prediction],
    ) -> None:
        """Accuracy, total PnL, win rate, Sharpe and drawdown for timeframe "1d"."""
        model = self._seed_daily(sample_model, evaluated_prediction)

        row = _family_row(db_session, model, timeframe="1d")

        assert row["accuracy"] == 0.75
        assert row["total_pnl"] == 250.0
        assert row["win_rate"] == 0.75
        assert row["sharpe_ratio"] is not None
        assert row["max_drawdown_pct"] is not None

    def test_missing_timeframe_gives_the_same_figures(
        self,
        db_session: Session,
        sample_model: Callable[..., Model],
        evaluated_prediction: Callable[..., Prediction],
    ) -> None:
        """Without a timeframe filter the daily figures are unchanged."""
        model = self._seed_daily(sample_model, evaluated_prediction)

        daily = _family_row(db_session, model, timeframe="1d")
        unfiltered = _family_row(db_session, model)

        assert unfiltered["total_pnl"] == 250.0
        for key in ("accuracy", "win_rate", "sharpe_ratio", "max_drawdown_pct"):
            assert unfiltered[key] == daily[key]


class TestReturnBasedMetrics:
    """Sharpe ratio and max drawdown are derived from returns (#177)."""

    def test_sharpe_ratio_is_mean_over_stdev_of_returns_times_sqrt_365(
        self,
        db_session: Session,
        sample_model: Callable[..., Model],
        evaluated_prediction: Callable[..., Prediction],
    ) -> None:
        """
        Given daily returns with mean m and standard deviation s
        Then the Sharpe ratio is m / s * sqrt(365)
        """
        model = sample_model(name="linear_v1")
        returns = [0.01, -0.02, 0.03, 0.005]
        for i, ret in enumerate(returns):
            evaluated_prediction(
                model_id=model.id,
                predicted_for=date(2024, 5, 1 + i),
                price_at_prediction=Decimal("100.00"),
                pnl_simulated=Decimal(str(round(ret * 100, 4))),
            )

        expected = (
            statistics.fmean(returns) / statistics.stdev(returns) * math.sqrt(365)
        )

        assert _family_row(db_session, model)["sharpe_ratio"] == pytest.approx(
            expected, abs=0.01
        )

    def test_sharpe_ratio_does_not_depend_on_the_price_level(
        self,
        db_session: Session,
        sample_model: Callable[..., Model],
        evaluated_prediction: Callable[..., Prediction],
    ) -> None:
        """The same percentage moves at BTC = 10,000 and 500,000 give one Sharpe."""
        low = sample_model(name="linear_v1")  # one family per model
        high = sample_model(name="ridge_v1")
        for i, ret in enumerate([0.01, -0.02, 0.03, 0.005, -0.01]):
            for model, price in ((low, 10_000), (high, 500_000)):
                evaluated_prediction(
                    model_id=model.id,
                    predicted_for=date(2024, 5, 1 + i),
                    price_at_prediction=Decimal(price),
                    pnl_simulated=Decimal(str(round(ret * price, 2))),
                )

        low_sharpe = _family_row(db_session, low)["sharpe_ratio"]
        assert low_sharpe is not None
        assert low_sharpe == pytest.approx(
            _family_row(db_session, high)["sharpe_ratio"]
        )

    def test_sharpe_ratio_is_none_when_the_returns_do_not_vary(
        self,
        db_session: Session,
        sample_model: Callable[..., Model],
        evaluated_prediction: Callable[..., Prediction],
    ) -> None:
        model = sample_model(name="linear_v1")
        for i in range(3):
            evaluated_prediction(
                model_id=model.id,
                predicted_for=date(2024, 5, 1 + i),
                pnl_simulated=Decimal("0.00"),
            )

        assert _family_row(db_session, model)["sharpe_ratio"] is None

    def test_get_all_models_metrics_exposes_return_based_fields_only(
        self,
        db_session: Session,
        sample_model: Callable[..., Model],
        evaluated_prediction: Callable[..., Prediction],
    ) -> None:
        """
        Given a model with returns of +10%, -10% and -10%
        Then max_drawdown_pct is the compounded -19%, the dollar max_drawdown
        figure is gone
        """
        model = sample_model(name="linear_v1")
        for i, pnl in enumerate([10, -10, -10]):
            evaluated_prediction(
                model_id=model.id,
                predicted_for=date(2024, 5, 1 + i),
                price_at_prediction=Decimal("100.00"),
                pnl_simulated=Decimal(str(pnl)),
            )

        metrics = get_all_models_metrics(db_session)
        row = next(m for m in metrics if m["id"] == model.id)

        assert row["max_drawdown_pct"] == pytest.approx(-19.0)
        assert "max_drawdown" not in row

    def test_get_all_models_metrics_has_no_return_metrics_without_predictions(
        self, db_session: Session, sample_model: Callable[..., Model]
    ) -> None:
        model = sample_model(name="linear_v1")

        row = next(m for m in get_all_models_metrics(db_session) if m["id"] == model.id)

        assert row["sharpe_ratio"] is None
        assert row["max_drawdown_pct"] is None


class TestUtcNow:
    """utc_now() is the timezone-aware UTC clock behind utc_today (#175)."""

    def test_is_timezone_aware_utc(self) -> None:
        now = utc_now()

        assert now.utcoffset() == timedelta(0)

    def test_follows_the_frozen_clock(self, mexico_city_at_0010_utc: datetime) -> None:
        assert utc_now() == mexico_city_at_0010_utc


class TestUtcToday:
    """utc_today() follows the UTC clock, not the process time zone (#173)."""

    def test_returns_the_utc_date_while_the_local_date_is_a_day_behind(
        self, mexico_city_at_0010_utc: datetime
    ) -> None:
        # Guard: the local date is the 3rd here, so a local-date call would be wrong
        assert mexico_city_at_0010_utc.astimezone().date() == date(2026, 10, 3)

        assert utc_today() == date(2026, 10, 4)

    def test_matches_the_utc_calendar_date_of_now(self) -> None:
        before = datetime.now(UTC).date()

        today = utc_today()

        assert before <= today <= datetime.now(UTC).date()
