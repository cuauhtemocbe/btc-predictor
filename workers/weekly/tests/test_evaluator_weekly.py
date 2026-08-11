"""
Tests for the weekly evaluator job.

Covers Gherkin acceptance criteria scenarios from US-022:
1. Weekly evaluator evaluates predictions 7 days later
2. PnL calculation is consistent across timeframes (1d vs 1w)
3. Direction correctness calculation
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from shared.db.models import BtcPrice, Model, Prediction
from workers.weekly import evaluator

# ============================================================================
# Unit tests for helper functions
# ============================================================================


class TestFindUnevaluatedWeeklyPrediction:
    """Test the find_unevaluated_weekly_prediction() function."""

    def test_finds_unevaluated_prediction(
        self,
        db_session: Session,
        sample_unevaluated_weekly_prediction_for_today: Prediction,
    ) -> None:
        """
        Should find an unevaluated weekly prediction for today.

        Given a weekly prediction exists for today with actual_price=NULL
        When find_unevaluated_weekly_prediction() is called
        Then it should return the prediction record
        """
        today = date.today()

        prediction = evaluator.find_unevaluated_weekly_prediction(db_session, today)

        assert prediction is not None
        assert prediction.id == sample_unevaluated_weekly_prediction_for_today.id
        assert prediction.timeframe == "1w"
        assert prediction.actual_price is None  # Unevaluated

    def test_returns_none_when_no_prediction(self, db_session: Session) -> None:
        """
        Should return None when no unevaluated weekly prediction exists.

        Given no weekly prediction exists for today
        When find_unevaluated_weekly_prediction() is called
        Then it should return None
        """
        today = date.today()

        prediction = evaluator.find_unevaluated_weekly_prediction(db_session, today)

        assert prediction is None

    def test_ignores_already_evaluated_predictions(
        self, db_session: Session, sample_trained_model: Model
    ) -> None:
        """
        Should ignore predictions that are already evaluated.

        Given a weekly prediction exists for today BUT it's already evaluated
        When find_unevaluated_weekly_prediction() is called
        Then it should return None (not the evaluated one)
        """
        today = date.today()

        # Create an EVALUATED weekly prediction
        evaluated_prediction = Prediction(
            model_id=sample_trained_model.id,
            predicted_for=today,
            timeframe="1w",
            predicted_at=evaluator.datetime.now(evaluator.UTC) - timedelta(days=7),
            price_at_prediction=Decimal("66000.00"),
            predicted_price=Decimal("67000.00"),
            actual_price=Decimal("67500.00"),  # Already evaluated!
            evaluated_at=evaluator.datetime.now(evaluator.UTC),
            error_abs=Decimal("500.00"),
            error_pct=Decimal("0.74"),
            direction_correct=True,
            pnl_simulated=Decimal("1500.00"),
        )
        db_session.add(evaluated_prediction)
        db_session.commit()

        # Should return None (ignore evaluated predictions)
        prediction = evaluator.find_unevaluated_weekly_prediction(db_session, today)

        assert prediction is None

    def test_ignores_daily_predictions(
        self, db_session: Session, sample_trained_model: Model
    ) -> None:
        """
        Should not confuse daily (1d) and weekly (1w) predictions.

        Given a DAILY prediction exists for today (unevaluated)
        When find_unevaluated_weekly_prediction() is called
        Then it should return None (only looks for weekly)
        """
        today = date.today()

        # Create a DAILY prediction (timeframe='1d')
        daily_prediction = Prediction(
            model_id=sample_trained_model.id,
            predicted_for=today,
            timeframe="1d",  # Daily, not weekly
            predicted_at=evaluator.datetime.now(evaluator.UTC) - timedelta(days=1),
            price_at_prediction=Decimal("66000.00"),
            predicted_price=Decimal("67000.00"),
            actual_price=None,
        )
        db_session.add(daily_prediction)
        db_session.commit()

        # Should return None (not a weekly prediction)
        prediction = evaluator.find_unevaluated_weekly_prediction(db_session, today)

        assert prediction is None


class TestFetchActualPrice:
    """Test the fetch_actual_price() function."""

    def test_fetches_7am_price(
        self, db_session: Session, sample_actual_price_for_today_7am: BtcPrice
    ) -> None:
        """
        Gherkin: Weekly evaluator fetches 7am BTC price.

        Given today's 7am BTC price exists in the database
        When fetch_actual_price() is called for today
        Then it should return the 7am close price
        """
        today = date.today()

        price = evaluator.fetch_actual_price(db_session, today)

        assert price is not None
        assert price == Decimal("67500.00")  # Close price from fixture

    def test_returns_none_when_price_missing(self, db_session: Session) -> None:
        """
        Should return None when 7am price is not available yet.

        Given today's 7am price does NOT exist in database
        When fetch_actual_price() is called
        Then it should return None (will retry next Monday)
        """
        today = date.today()

        price = evaluator.fetch_actual_price(db_session, today)

        assert price is None

    def test_fetches_8am_candle_with_4hour_granularity(
        self, db_session: Session
    ) -> None:
        """
        With 4-hour candles there is no exact 7:00:00 timestamp, so the
        evaluator must fall back to the first candle at or after 7am --
        the same range-based rule as workers/daily/evaluator.py.
        """
        target_date = date(2026, 5, 24)

        # 4-hour candles: 0am, 4am, 8am, 12pm, 4pm, 8pm -- none at exactly 7am
        candles = [
            datetime(2026, 5, 24, 0, 0, tzinfo=UTC),
            datetime(2026, 5, 24, 4, 0, tzinfo=UTC),
            datetime(2026, 5, 24, 8, 0, tzinfo=UTC),  # should be selected
            datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
            datetime(2026, 5, 24, 16, 0, tzinfo=UTC),
            datetime(2026, 5, 24, 20, 0, tzinfo=UTC),
        ]

        for i, timestamp in enumerate(candles):
            price = Decimal("95000.00") + Decimal(i * 100)
            db_session.add(
                BtcPrice(
                    timestamp=timestamp,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=Decimal("0"),
                    source="coingecko",
                )
            )
        db_session.commit()

        result = evaluator.fetch_actual_price(db_session, target_date)

        assert result == Decimal("95200.00")  # 8am candle


class TestCalculateDirectionCorrect:
    """Test the calculate_direction_correct() function."""

    def test_predicted_up_actual_up_is_correct(self) -> None:
        """
        Direction: Predicted UP, Actual UP → Correct.

        Given predicted_price > price_at_prediction (predicted UP)
        And actual_price >= price_at_prediction (actual UP)
        Then direction_correct should be True
        """
        predicted_price = Decimal("67000")  # > 66000 (predicted UP)
        price_at_prediction = Decimal("66000")
        actual_price = Decimal("67500")  # >= 66000 (actual UP)

        is_correct = evaluator.calculate_direction_correct(
            predicted_price, price_at_prediction, actual_price
        )

        assert is_correct is True

    def test_predicted_up_actual_down_is_incorrect(self) -> None:
        """
        Direction: Predicted UP, Actual DOWN → Incorrect.

        Given predicted_price > price_at_prediction (predicted UP)
        But actual_price < price_at_prediction (actual DOWN)
        Then direction_correct should be False
        """
        predicted_price = Decimal("67000")  # > 66000 (predicted UP)
        price_at_prediction = Decimal("66000")
        actual_price = Decimal("65500")  # < 66000 (actual DOWN)

        is_correct = evaluator.calculate_direction_correct(
            predicted_price, price_at_prediction, actual_price
        )

        assert is_correct is False

    def test_predicted_down_actual_down_is_correct(self) -> None:
        """
        Direction: Predicted DOWN, Actual DOWN → Correct.

        Given predicted_price <= price_at_prediction (predicted DOWN)
        And actual_price < price_at_prediction (actual DOWN)
        Then direction_correct should be True
        """
        predicted_price = Decimal("65000")  # < 66000 (predicted DOWN)
        price_at_prediction = Decimal("66000")
        actual_price = Decimal("65500")  # < 66000 (actual DOWN)

        is_correct = evaluator.calculate_direction_correct(
            predicted_price, price_at_prediction, actual_price
        )

        assert is_correct is True

    def test_predicted_down_actual_up_is_incorrect(self) -> None:
        """
        Direction: Predicted DOWN, Actual UP → Incorrect.

        Given predicted_price <= price_at_prediction (predicted DOWN)
        But actual_price >= price_at_prediction (actual UP)
        Then direction_correct should be False
        """
        predicted_price = Decimal("65000")  # < 66000 (predicted DOWN)
        price_at_prediction = Decimal("66000")
        actual_price = Decimal("67500")  # >= 66000 (actual UP)

        is_correct = evaluator.calculate_direction_correct(
            predicted_price, price_at_prediction, actual_price
        )

        assert is_correct is False


class TestCalculateMetrics:
    """Test the calculate_metrics() function."""

    def test_calculates_all_metrics_correctly(
        self,
        db_session: Session,
        sample_unevaluated_weekly_prediction_for_today: Prediction,
    ) -> None:
        """
        Should calculate all 7 metrics for a weekly prediction.

        Given an unevaluated weekly prediction
        And actual_price is known
        When calculate_metrics() is called
        Then it should return all metrics:
        - error_abs, error_pct, direction_correct
        - pnl_simulated, pnl_long_short, pnl_threshold, pnl_realistic
        """
        prediction = sample_unevaluated_weekly_prediction_for_today
        actual_price = Decimal("67500.00")

        metrics = evaluator.calculate_metrics(prediction, actual_price)

        # Check all keys exist
        assert "error_abs" in metrics
        assert "error_pct" in metrics
        assert "direction_correct" in metrics
        assert "pnl_simulated" in metrics
        assert "pnl_long_short" in metrics
        assert "pnl_threshold" in metrics
        assert "pnl_realistic" in metrics

        # Check types
        assert isinstance(metrics["error_abs"], Decimal)
        assert isinstance(metrics["error_pct"], Decimal)
        assert isinstance(metrics["direction_correct"], bool)
        assert isinstance(metrics["pnl_simulated"], Decimal)

    def test_error_abs_calculation(
        self,
        db_session: Session,
        sample_unevaluated_weekly_prediction_for_today: Prediction,
    ) -> None:
        """
        error_abs = |actual_price - predicted_price|

        Given predicted_price = 67000
        And actual_price = 67500
        Then error_abs = |67500 - 67000| = 500
        """
        prediction = sample_unevaluated_weekly_prediction_for_today
        actual_price = Decimal("67500.00")

        metrics = evaluator.calculate_metrics(prediction, actual_price)

        assert metrics["error_abs"] == Decimal("500.00")

    def test_error_pct_calculation(
        self,
        db_session: Session,
        sample_unevaluated_weekly_prediction_for_today: Prediction,
    ) -> None:
        """
        error_pct = (error_abs / actual_price) * 100

        Given predicted_price = 67000
        And actual_price = 67500
        Then error_abs = 500
        And error_pct = (500 / 67500) * 100 ≈ 0.74%
        """
        prediction = sample_unevaluated_weekly_prediction_for_today
        actual_price = Decimal("67500.00")

        metrics = evaluator.calculate_metrics(prediction, actual_price)

        # Allow small floating point differences
        expected_pct = (Decimal("500") / Decimal("67500")) * Decimal("100")
        assert abs(metrics["error_pct"] - expected_pct) < Decimal("0.01")

    def test_pnl_calculation_is_timeframe_agnostic(
        self, db_session: Session, sample_trained_model: Model
    ) -> None:
        """
        Gherkin: PnL calculation is consistent across timeframes.

        Given a DAILY prediction and a WEEKLY prediction with same values
        When PnL is calculated
        Then both should produce the SAME pnl_long_short value
        (formulas are timeframe-agnostic)
        """
        # Create daily prediction
        daily_pred = Prediction(
            model_id=sample_trained_model.id,
            predicted_for=date.today(),
            timeframe="1d",
            predicted_at=evaluator.datetime.now(evaluator.UTC),
            price_at_prediction=Decimal("66000.00"),
            predicted_price=Decimal("67000.00"),
        )

        # Create weekly prediction (same values, different timeframe)
        weekly_pred = Prediction(
            model_id=sample_trained_model.id,
            predicted_for=date.today(),
            timeframe="1w",
            predicted_at=evaluator.datetime.now(evaluator.UTC),
            price_at_prediction=Decimal("66000.00"),
            predicted_price=Decimal("67000.00"),
        )

        actual_price = Decimal("67500.00")

        # Calculate metrics for both
        daily_metrics = evaluator.calculate_metrics(daily_pred, actual_price)
        weekly_metrics = evaluator.calculate_metrics(weekly_pred, actual_price)

        # PnL should be IDENTICAL (timeframe doesn't affect formula)
        assert daily_metrics["pnl_long_short"] == weekly_metrics["pnl_long_short"]
        assert daily_metrics["pnl_simulated"] == weekly_metrics["pnl_simulated"]
        assert daily_metrics["pnl_threshold"] == weekly_metrics["pnl_threshold"]
        assert daily_metrics["pnl_realistic"] == weekly_metrics["pnl_realistic"]

    def test_actual_price_zero_raises_error(
        self,
        db_session: Session,
        sample_unevaluated_weekly_prediction_for_today: Prediction,
    ) -> None:
        """
        Should raise ValueError if actual_price is zero (defensive check).
        """
        prediction = sample_unevaluated_weekly_prediction_for_today
        actual_price = Decimal("0.00")

        with pytest.raises(ValueError, match="actual_price cannot be zero"):
            evaluator.calculate_metrics(prediction, actual_price)


class TestUpdatePrediction:
    """Test the update_prediction() function."""

    def test_updates_all_fields(
        self,
        db_session: Session,
        sample_unevaluated_weekly_prediction_for_today: Prediction,
    ) -> None:
        """
        Should update prediction with all evaluation results.

        Given an unevaluated prediction
        And calculated metrics
        When update_prediction() is called
        Then all evaluation fields should be populated
        """
        prediction = sample_unevaluated_weekly_prediction_for_today
        actual_price = Decimal("67500.00")

        metrics = {
            "error_abs": Decimal("500.00"),
            "error_pct": Decimal("0.74"),
            "direction_correct": True,
            "pnl_simulated": Decimal("1500.00"),
            "pnl_long_short": Decimal("1500.00"),
            "pnl_threshold": Decimal("1500.00"),
            "pnl_realistic": Decimal("1400.00"),
        }

        evaluator.update_prediction(db_session, prediction, actual_price, metrics)

        # Verify all fields updated
        db_session.refresh(prediction)
        assert prediction.actual_price == actual_price
        assert prediction.evaluated_at is not None
        assert prediction.error_abs == Decimal("500.00")
        assert prediction.error_pct == Decimal("0.74")
        assert prediction.direction_correct is True
        assert prediction.pnl_simulated == Decimal("1500.00")
        assert prediction.pnl_long_short == Decimal("1500.00")


# ============================================================================
# Integration test for main() function
# ============================================================================


class TestMainWeeklyEvaluator:
    """Test the main() entry point for weekly evaluator job."""

    def test_success_evaluates_weekly_prediction(
        self,
        db_session: Session,
        sample_unevaluated_weekly_prediction_for_today: Prediction,
        sample_actual_price_for_today_7am: BtcPrice,
    ) -> None:
        """
        Gherkin: Weekly evaluator evaluates predictions 7 days later.

        Given a weekly prediction exists for today (unevaluated)
        And today's 7am BTC price is available
        When the weekly evaluator runs
        Then it should calculate error metrics and PnL
        And update the prediction with evaluation results
        """
        import workers.weekly.evaluator as eval_module

        original_session = eval_module.SessionLocal
        eval_module.SessionLocal = lambda: db_session

        try:
            # Verify prediction is unevaluated
            prediction = sample_unevaluated_weekly_prediction_for_today
            prediction_id = prediction.id
            assert prediction.actual_price is None

            # Run evaluator
            exit_code = evaluator.main()

            # Should succeed
            assert exit_code == 0

            # Re-query prediction to see updated values
            from shared.db.models import Prediction as PredModel

            updated_prediction = (
                db_session.query(PredModel).filter_by(id=prediction_id).one()
            )

            # Verify prediction was evaluated
            assert updated_prediction.actual_price == Decimal("67500.00")
            assert updated_prediction.evaluated_at is not None
            assert updated_prediction.error_abs is not None
            assert updated_prediction.error_pct is not None
            assert updated_prediction.direction_correct is not None
            assert updated_prediction.pnl_long_short is not None

        finally:
            eval_module.SessionLocal = original_session

    def test_exits_successfully_when_no_predictions(self, db_session: Session) -> None:
        """
        Should exit successfully when no predictions to evaluate.

        Given no weekly predictions exist for today
        When the weekly evaluator runs
        Then it should log "No predictions to evaluate"
        And exit with code 0 (success, not an error)
        """
        import workers.weekly.evaluator as eval_module

        original_session = eval_module.SessionLocal
        eval_module.SessionLocal = lambda: db_session

        try:
            exit_code = evaluator.main()

            # Should succeed (nothing to do is not an error)
            assert exit_code == 0

        finally:
            eval_module.SessionLocal = original_session

    def test_skips_when_actual_price_not_available(
        self,
        db_session: Session,
        sample_unevaluated_weekly_prediction_for_today: Prediction,
    ) -> None:
        """
        Should skip evaluation when 7am price is not available yet.

        Given a weekly prediction exists for today
        But today's 7am price is NOT in the database yet
        When the weekly evaluator runs
        Then it should skip evaluation (will retry next Monday)
        And exit with code 0
        """
        import workers.weekly.evaluator as eval_module

        original_session = eval_module.SessionLocal
        eval_module.SessionLocal = lambda: db_session

        try:
            # Verify 7am price does NOT exist
            today = date.today()
            price = evaluator.fetch_actual_price(db_session, today)
            assert price is None

            prediction = sample_unevaluated_weekly_prediction_for_today
            prediction_id = prediction.id

            # Run evaluator
            exit_code = evaluator.main()

            # Should succeed (skip, not error)
            assert exit_code == 0

            # Re-query prediction to verify it remains unevaluated
            from shared.db.models import Prediction as PredModel

            updated_prediction = (
                db_session.query(PredModel).filter_by(id=prediction_id).one()
            )
            assert updated_prediction.actual_price is None

        finally:
            eval_module.SessionLocal = original_session
