"""
Tests for the weekly evaluator job.

Covers Gherkin acceptance criteria scenarios from US-022:
1. Weekly evaluator evaluates predictions 7 days later
2. PnL calculation is consistent across timeframes (1d vs 1w)
3. Direction correctness calculation
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from shared.db.models import Model, Prediction, Price
from workers.daily.evaluator import EvaluationMetrics
from workers.weekly import evaluator

# weekly.evaluator.fetch_actual_price is re-exported from the daily module, not in its
# public API, so mypy rejects the attribute; look it up through vars().
fetch_actual_price = vars(evaluator)["fetch_actual_price"]

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
            predicted_at=datetime.now(UTC) - timedelta(days=7),
            price_at_prediction=Decimal("66000.00"),
            predicted_price=Decimal("67000.00"),
            actual_price=Decimal("67500.00"),  # Already evaluated!
            evaluated_at=datetime.now(UTC),
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
            predicted_at=datetime.now(UTC) - timedelta(days=1),
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
    """The weekly evaluator settles against the bar opened the day before."""

    def test_fetches_bar_opened_the_day_before(
        self, db_session: Session, sample_actual_price_for_today: Price
    ) -> None:
        """
        Given the daily bar opened yesterday is stored
        When fetch_actual_price() is called for today
        Then it returns that bar's close
        """
        price = fetch_actual_price(db_session, date.today())

        assert price == Decimal("67500.00")  # Close price from fixture

    def test_returns_none_when_bar_missing(self, db_session: Session) -> None:
        """Given no bar is stored, fetch_actual_price() returns None."""
        assert fetch_actual_price(db_session, date.today()) is None

    def test_ignores_bar_opened_on_the_prediction_date(
        self, db_session: Session
    ) -> None:
        """
        The bar opened on predicted_for is still open at that date; it belongs
        to the next prediction.
        """
        target = date(2026, 10, 5)
        for day, close in ((date(2026, 10, 4), "100"), (date(2026, 10, 5), "200")):
            db_session.add(
                Price(
                    timestamp=datetime.combine(day, time(0, 0), tzinfo=UTC),
                    open=Decimal(close),
                    high=Decimal(close),
                    low=Decimal(close),
                    close=Decimal(close),
                    volume=Decimal("0"),
                    source="binance_vision",
                )
            )
        db_session.commit()

        assert fetch_actual_price(db_session, target) == Decimal("100")


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
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("66000.00"),
            predicted_price=Decimal("67000.00"),
        )

        # Create weekly prediction (same values, different timeframe)
        weekly_pred = Prediction(
            model_id=sample_trained_model.id,
            predicted_for=date.today(),
            timeframe="1w",
            predicted_at=datetime.now(UTC),
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

        metrics: EvaluationMetrics = {
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
        sample_actual_price_for_today: Price,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Gherkin: Weekly evaluator evaluates predictions 7 days later.

        Given a weekly prediction exists for today (unevaluated)
        And the daily bar opened yesterday is stored
        When the weekly evaluator runs
        Then it should calculate error metrics and PnL
        And update the prediction with evaluation results
        """
        import workers.weekly.evaluator as eval_module

        monkeypatch.setattr(eval_module, "SessionLocal", lambda: db_session)

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

    def test_exits_successfully_when_no_predictions(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Should exit successfully when no predictions to evaluate.

        Given no weekly predictions exist for today
        When the weekly evaluator runs
        Then it should log "No predictions to evaluate"
        And exit with code 0 (success, not an error)
        """
        import workers.weekly.evaluator as eval_module

        monkeypatch.setattr(eval_module, "SessionLocal", lambda: db_session)

        exit_code = evaluator.main()

        # Should succeed (nothing to do is not an error)
        assert exit_code == 0

    def test_skips_when_actual_price_not_available(
        self,
        db_session: Session,
        sample_unevaluated_weekly_prediction_for_today: Prediction,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Should leave the prediction pending when its bar is not stored yet.

        Given a weekly prediction exists for today
        But the daily bar opened yesterday is NOT stored yet
        When the weekly evaluator runs
        Then it should skip evaluation (will retry next Monday)
        And exit with code 0
        """
        import workers.weekly.evaluator as eval_module

        monkeypatch.setattr(eval_module, "SessionLocal", lambda: db_session)

        # Verify the settling bar does NOT exist
        today = date.today()
        price = fetch_actual_price(db_session, today)
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


# ============================================================================
# Pending weekly predictions (#143)
# ============================================================================


def _patch_session(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_session() -> Session:
        monkeypatch.setattr(db_session, "close", lambda: None)
        return db_session

    monkeypatch.setattr("workers.weekly.evaluator.SessionLocal", mock_session)


def _add_daily_bar(db_session: Session, opened: date, close: str) -> None:
    price = Decimal(close)
    db_session.add(
        Price(
            timestamp=datetime.combine(opened, time(0, 0), tzinfo=UTC),
            open=price,
            high=price,
            low=price,
            close=price,
            volume=Decimal("1"),
            source="binance_vision",
        )
    )
    db_session.commit()


def _add_prediction(
    db_session: Session,
    model: Model,
    predicted_for: date,
    timeframe: str = "1w",
) -> Prediction:
    prediction = Prediction(
        model_id=model.id,
        predicted_for=predicted_for,
        timeframe=timeframe,
        predicted_at=datetime.now(UTC),
        price_at_prediction=Decimal("84880.05"),
        predicted_price=Decimal("85500.00"),
    )
    db_session.add(prediction)
    db_session.commit()
    db_session.refresh(prediction)
    return prediction


class TestPendingWeeklyPredictions:
    def test_prediction_scored_against_bar_it_predicted(
        self,
        db_session: Session,
        sample_trained_model: Model,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Prediction for Monday 10-12: the bar opened Sunday 10-11 settles it."""
        _patch_session(db_session, monkeypatch)
        _add_daily_bar(db_session, date(2026, 10, 11), "85100.00")
        prediction = _add_prediction(
            db_session, sample_trained_model, date(2026, 10, 12)
        )

        assert evaluator.main(today=date(2026, 10, 12)) == 0

        db_session.refresh(prediction)
        assert prediction.actual_price == Decimal("85100.00")
        assert prediction.evaluated_at is not None
        assert prediction.error_abs is not None
        assert prediction.direction_correct is not None

    def test_missing_bar_stays_pending_and_names_the_bar(
        self,
        db_session: Session,
        sample_trained_model: Model,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _patch_session(db_session, monkeypatch)
        prediction = _add_prediction(
            db_session, sample_trained_model, date(2026, 10, 12)
        )

        with caplog.at_level("INFO"):
            exit_code = evaluator.main(today=date(2026, 10, 12))

        assert exit_code == 0
        db_session.refresh(prediction)
        assert prediction.actual_price is None
        assert prediction.evaluated_at is None
        assert "daily bar opened 2026-10-11" in caplog.text
        assert "7am" not in caplog.text

    def test_past_pending_prediction_is_evaluated_on_a_later_run(
        self,
        db_session: Session,
        sample_trained_model: Model,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A Monday whose bar arrived late is settled by the next Monday's run."""
        _patch_session(db_session, monkeypatch)
        _add_daily_bar(db_session, date(2026, 10, 11), "85100.00")
        _add_daily_bar(db_session, date(2026, 10, 18), "86000.00")
        late = _add_prediction(db_session, sample_trained_model, date(2026, 10, 12))
        current = _add_prediction(db_session, sample_trained_model, date(2026, 10, 19))

        assert evaluator.main(today=date(2026, 10, 19)) == 0

        db_session.refresh(late)
        db_session.refresh(current)
        assert late.actual_price == Decimal("85100.00")
        assert current.actual_price == Decimal("86000.00")

    def test_a_missing_bar_does_not_block_the_other_dates(
        self,
        db_session: Session,
        sample_trained_model: Model,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_session(db_session, monkeypatch)
        _add_daily_bar(db_session, date(2026, 10, 18), "86000.00")
        gap = _add_prediction(db_session, sample_trained_model, date(2026, 10, 12))
        current = _add_prediction(db_session, sample_trained_model, date(2026, 10, 19))

        assert evaluator.main(today=date(2026, 10, 19)) == 0

        db_session.refresh(gap)
        db_session.refresh(current)
        assert gap.actual_price is None
        assert current.actual_price == Decimal("86000.00")

    def test_already_evaluated_prediction_is_untouched(
        self,
        db_session: Session,
        sample_trained_model: Model,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_session(db_session, monkeypatch)
        _add_daily_bar(db_session, date(2026, 10, 11), "85100.00")
        evaluated_at = datetime(2026, 10, 12, 7, 0, tzinfo=UTC)
        prediction = _add_prediction(
            db_session, sample_trained_model, date(2026, 10, 12)
        )
        prediction.actual_price = Decimal("1.00")
        prediction.evaluated_at = evaluated_at
        db_session.commit()

        assert evaluator.main(today=date(2026, 10, 19)) == 0

        db_session.refresh(prediction)
        assert prediction.actual_price == Decimal("1.00")
        assert prediction.evaluated_at == evaluated_at

    def test_daily_predictions_are_left_alone(
        self,
        db_session: Session,
        sample_trained_model: Model,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_session(db_session, monkeypatch)
        _add_daily_bar(db_session, date(2026, 10, 11), "85100.00")
        prediction = _add_prediction(
            db_session, sample_trained_model, date(2026, 10, 12), timeframe="1d"
        )

        assert evaluator.main(today=date(2026, 10, 12)) == 0

        db_session.refresh(prediction)
        assert prediction.actual_price is None

    def test_future_predictions_are_untouched(
        self,
        db_session: Session,
        sample_trained_model: Model,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_session(db_session, monkeypatch)
        _add_daily_bar(db_session, date(2026, 10, 18), "86000.00")
        prediction = _add_prediction(
            db_session, sample_trained_model, date(2026, 10, 19)
        )

        assert evaluator.main(today=date(2026, 10, 12)) == 0

        db_session.refresh(prediction)
        assert prediction.actual_price is None
