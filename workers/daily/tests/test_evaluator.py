"""
Tests for the daily evaluator job.

Covers all 3 Gherkin acceptance criteria scenarios:
1. Evaluate yesterday's prediction (happy path)
2. No unevaluated predictions
3. Missing actual price in btc_prices

Plus comprehensive tests for:
- Direction logic (4 cases)
- Error calculation accuracy
- PnL simulation integration
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from shared.db.models import BtcPrice, Model, Prediction
from workers.daily import evaluator

# ============================================================================
# Unit tests for helper functions
# ============================================================================


class TestCalculateDirectionCorrect:
    """Test the calculate_direction_correct() function."""

    def test_predicted_up_actual_up_correct(self) -> None:
        """Should return True when predicted UP and actual UP."""
        result = evaluator.calculate_direction_correct(
            predicted_price=Decimal("67000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("67500"),
        )
        assert result is True

    def test_predicted_up_actual_down_incorrect(self) -> None:
        """Should return False when predicted UP but actual DOWN."""
        result = evaluator.calculate_direction_correct(
            predicted_price=Decimal("67000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("65000"),
        )
        assert result is False

    def test_predicted_down_actual_down_correct(self) -> None:
        """Should return True when predicted DOWN and actual DOWN."""
        result = evaluator.calculate_direction_correct(
            predicted_price=Decimal("65000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("64000"),
        )
        assert result is True

    def test_predicted_down_actual_up_incorrect(self) -> None:
        """Should return False when predicted DOWN but actual UP."""
        result = evaluator.calculate_direction_correct(
            predicted_price=Decimal("65000"),
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("67000"),
        )
        assert result is False

    def test_predicted_flat_actual_down_correct(self) -> None:
        """Should return True when predicted flat and actual DOWN."""
        result = evaluator.calculate_direction_correct(
            predicted_price=Decimal("66000"),  # Same as price_at_prediction
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("65000"),
        )
        assert result is True

    def test_predicted_flat_actual_up_incorrect(self) -> None:
        """Should return False when predicted flat but actual UP."""
        result = evaluator.calculate_direction_correct(
            predicted_price=Decimal("66000"),  # Same as price_at_prediction
            price_at_prediction=Decimal("66000"),
            actual_price=Decimal("67000"),
        )
        assert result is False


class TestCalculateMetrics:
    """Test the calculate_metrics() function."""

    def test_error_calculation_accuracy(
        self, db_session: Session, sample_unevaluated_prediction_for_today: Prediction
    ) -> None:
        """Should calculate error_abs and error_pct correctly."""
        prediction = sample_unevaluated_prediction_for_today
        # Prediction: predicted=67000, price_at_prediction=66000
        actual_price = Decimal("67500.00")

        metrics = evaluator.calculate_metrics(prediction, actual_price)

        # error_abs = |67500 - 67000| = 500
        assert metrics["error_abs"] == Decimal("500.00")

        # error_pct = (500 / 67500) * 100 ≈ 0.74%
        expected_pct = (Decimal("500.00") / Decimal("67500.00")) * Decimal("100")
        assert abs(metrics["error_pct"] - expected_pct) < Decimal("0.01")

    def test_direction_correct_integration(
        self, db_session: Session, sample_unevaluated_prediction_for_today: Prediction
    ) -> None:
        """Should integrate direction logic correctly."""
        prediction = sample_unevaluated_prediction_for_today
        # Prediction: predicted=67000 > price_at_prediction=66000 (predicted UP)
        actual_price = Decimal("67500.00")  # Actual UP

        metrics = evaluator.calculate_metrics(prediction, actual_price)

        assert metrics["direction_correct"] is True

    def test_pnl_simulation_integration_predicted_up_profit(
        self, db_session: Session, sample_unevaluated_prediction_for_today: Prediction
    ) -> None:
        """Should calculate positive PnL when predicted UP and actual UP."""
        prediction = sample_unevaluated_prediction_for_today
        # Prediction: predicted=67000 > price_at_prediction=66000 (go long)
        actual_price = Decimal("67500.00")  # Profit: 67500 - 66000 = 1500

        metrics = evaluator.calculate_metrics(prediction, actual_price)

        assert metrics["pnl_simulated"] == Decimal("1500.00")

    def test_pnl_simulation_integration_predicted_up_loss(
        self, db_session: Session, sample_unevaluated_prediction_for_today: Prediction
    ) -> None:
        """Should calculate negative PnL when predicted UP but actual DOWN."""
        prediction = sample_unevaluated_prediction_for_today
        # Prediction: predicted=67000 > price_at_prediction=66000 (go long)
        actual_price = Decimal("65000.00")  # Loss: 65000 - 66000 = -1000

        metrics = evaluator.calculate_metrics(prediction, actual_price)

        assert metrics["pnl_simulated"] == Decimal("-1000.00")

    def test_pnl_simulation_integration_predicted_down_no_trade(
        self, db_session: Session, sample_trained_model: Model
    ) -> None:
        """Should calculate zero PnL when predicted DOWN (no trade)."""
        # Create prediction with predicted_price < price_at_prediction (predicted DOWN)
        prediction = Prediction(
            model_id=sample_trained_model.id,
            predicted_for=date.today(),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("66000.00"),
            predicted_price=Decimal("65000.00"),  # Predicted DOWN
            actual_price=None,
        )
        db_session.add(prediction)
        db_session.commit()

        actual_price = Decimal("64000.00")  # Actual DOWN (correct prediction)

        metrics = evaluator.calculate_metrics(prediction, actual_price)

        assert metrics["pnl_simulated"] == Decimal("0.00")

    def test_division_by_zero_protection(
        self, db_session: Session, sample_unevaluated_prediction_for_today: Prediction
    ) -> None:
        """Should raise ValueError when actual_price is zero."""
        prediction = sample_unevaluated_prediction_for_today
        actual_price = Decimal("0.00")

        with pytest.raises(ValueError, match="actual_price cannot be zero"):
            evaluator.calculate_metrics(prediction, actual_price)


class TestFindUnevaluatedPrediction:
    """Test the find_unevaluated_prediction() function."""

    def test_find_unevaluated_prediction(
        self, db_session: Session, sample_unevaluated_prediction_for_today: Prediction
    ) -> None:
        """Should find prediction with actual_price=NULL."""
        today = date.today()

        prediction = evaluator.find_unevaluated_prediction(db_session, today)

        assert prediction is not None
        assert prediction.id == sample_unevaluated_prediction_for_today.id
        assert prediction.actual_price is None

    def test_no_unevaluated_predictions(
        self, db_session: Session, sample_evaluated_prediction_for_today: Prediction
    ) -> None:
        """Should return None when all predictions are evaluated."""
        today = date.today()

        prediction = evaluator.find_unevaluated_prediction(db_session, today)

        assert prediction is None

    def test_no_predictions_for_date(self, db_session: Session) -> None:
        """Should return None when no predictions exist for the date."""
        today = date.today()

        prediction = evaluator.find_unevaluated_prediction(db_session, today)

        assert prediction is None

    def test_multiple_predictions_returns_first_by_model_id(
        self, db_session: Session, sample_trained_model: Model
    ) -> None:
        """
        Should return first prediction ordered by model_id.

        When multiple models predict for the same day.
        """
        today = date.today()

        # Create a second model with higher ID
        model2 = Model(
            name="lstm_v1",
            version="1.0.0",
            is_active=False,
            trained_at=datetime.now(UTC),
            train_from=today - timedelta(days=90),
            train_to=today - timedelta(days=1),
            params={"window_days": 30},
            artifact=b"model2_artifact",
        )
        db_session.add(model2)
        db_session.commit()

        # Create two unevaluated predictions for today from different models
        prediction1 = Prediction(
            model_id=sample_trained_model.id,  # Lower model_id
            predicted_for=today,
            timeframe="1d",
            predicted_at=datetime.now(UTC) - timedelta(hours=2),
            price_at_prediction=Decimal("66000.00"),
            predicted_price=Decimal("67000.00"),
            actual_price=None,
        )
        prediction2 = Prediction(
            model_id=model2.id,  # Higher model_id
            predicted_for=today,
            timeframe="1d",
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("66500.00"),
            predicted_price=Decimal("67500.00"),
            actual_price=None,
        )

        db_session.add_all([prediction1, prediction2])
        db_session.commit()

        result = evaluator.find_unevaluated_prediction(db_session, today)

        # Should return prediction with lowest model_id (consistent ordering)
        assert result is not None
        assert result.model_id == sample_trained_model.id
        assert result.predicted_price == Decimal("67000.00")


class TestFetchActualPrice:
    """Test the fetch_actual_price() function."""

    def test_fetch_existing_price(
        self, db_session: Session, sample_actual_price_for_today: BtcPrice
    ) -> None:
        """Should fetch 7am close price for today."""
        today = date.today()

        price = evaluator.fetch_actual_price(db_session, today)

        assert price is not None
        assert price == Decimal("67500.00")

    def test_missing_price_returns_none(self, db_session: Session) -> None:
        """Should return None when no price data exists for 7am."""
        today = date.today()

        price = evaluator.fetch_actual_price(db_session, today)

        assert price is None

    def test_fetch_actual_price_with_4hour_candles(self, db_session: Session) -> None:
        """Test evaluator finds 8am candle with 4-hour granularity."""
        target_date = date(2026, 5, 24)

        # Insert 4-hour candles for May 24: 0am, 4am, 8am, 12pm, 4pm, 8pm
        candles = [
            datetime(2026, 5, 24, 0, 0, tzinfo=UTC),  # 0am
            datetime(2026, 5, 24, 4, 0, tzinfo=UTC),  # 4am
            datetime(2026, 5, 24, 8, 0, tzinfo=UTC),  # 8am ← should be selected
            datetime(2026, 5, 24, 12, 0, tzinfo=UTC),  # 12pm
            datetime(2026, 5, 24, 16, 0, tzinfo=UTC),  # 4pm
            datetime(2026, 5, 24, 20, 0, tzinfo=UTC),  # 8pm
        ]

        for i, timestamp in enumerate(candles):
            price = Decimal("95000.00") + Decimal(i * 100)  # Incrementing prices
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

        # Should find 8am candle (index 2 → $95200)
        result = evaluator.fetch_actual_price(db_session, target_date)

        assert result == Decimal("95200.00")

    def test_fetch_actual_price_no_data_after_7am(self, db_session: Session) -> None:
        """Should return None if no candles exist at or after 7am on target date."""
        target_date = date(2026, 5, 25)

        # Insert candles only before 7am (0am, 4am)
        early_candles = [
            datetime(2026, 5, 25, 0, 0, tzinfo=UTC),  # 0am
            datetime(2026, 5, 25, 4, 0, tzinfo=UTC),  # 4am
        ]

        for i, timestamp in enumerate(early_candles):
            price = Decimal("96000.00") + Decimal(i * 100)
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

        # Should return None (no candles >= 7am)
        result = evaluator.fetch_actual_price(db_session, target_date)

        assert result is None

    def test_fetch_actual_price_excludes_next_day(self, db_session: Session) -> None:
        """Should not return candles from the next day."""
        target_date = date(2026, 5, 26)

        # Insert candles for May 26 (0am, 4am only) and May 27 (0am, 4am, 8am)
        candles = [
            # May 26 (target date) - only early candles
            (datetime(2026, 5, 26, 0, 0, tzinfo=UTC), Decimal("97000.00")),
            (datetime(2026, 5, 26, 4, 0, tzinfo=UTC), Decimal("97100.00")),
            # May 27 (next day) - has 8am candle but should be excluded
            (datetime(2026, 5, 27, 0, 0, tzinfo=UTC), Decimal("97200.00")),
            (datetime(2026, 5, 27, 4, 0, tzinfo=UTC), Decimal("97300.00")),
            (datetime(2026, 5, 27, 8, 0, tzinfo=UTC), Decimal("97400.00")),
        ]

        for timestamp, price in candles:
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

        # Should return None (no candles >= 7am on May 26, May 27's 8am excluded)
        result = evaluator.fetch_actual_price(db_session, target_date)

        assert result is None


class TestUpdatePrediction:
    """Test the update_prediction() function."""

    def test_update_prediction_success(
        self, db_session: Session, sample_unevaluated_prediction_for_today: Prediction
    ) -> None:
        """Should update all evaluation fields including new PnL strategies."""
        prediction = sample_unevaluated_prediction_for_today
        actual_price = Decimal("67500.00")
        metrics = {
            "error_abs": Decimal("500.00"),
            "error_pct": Decimal("0.74"),
            "direction_correct": True,
            "pnl_simulated": Decimal("1500.00"),
            "pnl_long_short": Decimal("1500.00"),
            "pnl_threshold": Decimal("1500.00"),
            "pnl_realistic": Decimal("1368.00"),
        }

        evaluator.update_prediction(db_session, prediction, actual_price, metrics)

        # Refresh from DB to verify commit
        db_session.refresh(prediction)

        assert prediction.actual_price == actual_price
        assert prediction.evaluated_at is not None
        assert prediction.error_abs == Decimal("500.00")
        assert prediction.error_pct == Decimal("0.74")
        assert prediction.direction_correct is True
        assert prediction.pnl_simulated == Decimal("1500.00")
        assert prediction.pnl_long_short == Decimal("1500.00")
        assert prediction.pnl_threshold == Decimal("1500.00")
        assert prediction.pnl_realistic == Decimal("1368.00")


# ============================================================================
# Integration tests for main() function
# ============================================================================


class TestEvaluatorMain:
    """Test the main() entry point."""

    def test_evaluate_yesterday_prediction_success(
        self,
        db_session: Session,
        sample_unevaluated_prediction_for_today: Prediction,
        sample_actual_price_for_today: BtcPrice,
        monkeypatch,
    ) -> None:
        """
        Gherkin Scenario 1: Evaluate yesterday's prediction.

        Given a prediction exists for predicted_for=today with actual_price=NULL
        And btc_prices has a record for today 7am
        When I run evaluator.main()
        Then the prediction record is updated with evaluation results
        And exit code is 0
        """
        prediction_id = sample_unevaluated_prediction_for_today.id

        # Mock SessionLocal to return our test session, but don't close it
        def mock_session():
            session = db_session
            # Override close to be no-op for testing
            session.close = lambda: None
            return session

        monkeypatch.setattr("workers.daily.evaluator.SessionLocal", mock_session)

        exit_code = evaluator.main()

        assert exit_code == 0

        # Re-fetch prediction to verify it was updated
        from sqlalchemy import select

        from shared.db.models import Prediction

        stmt = select(Prediction).where(Prediction.id == prediction_id)
        prediction = db_session.execute(stmt).scalar_one()

        assert prediction.actual_price == Decimal("67500.00")
        assert prediction.evaluated_at is not None
        assert prediction.error_abs == Decimal("500.00")
        assert prediction.direction_correct is True
        assert prediction.pnl_simulated == Decimal("1500.00")

    def test_no_unevaluated_predictions_success(
        self,
        db_session: Session,
        sample_evaluated_prediction_for_today: Prediction,
        monkeypatch,
    ) -> None:
        """
        Gherkin Scenario 2: No unevaluated predictions.

        Given all predictions have actual_price != NULL
        When I run evaluator.main()
        Then the job logs "No predictions to evaluate"
        And exit code is 0
        """

        # Mock SessionLocal to return our test session, but don't close it
        def mock_session():
            session = db_session
            session.close = lambda: None
            return session

        monkeypatch.setattr("workers.daily.evaluator.SessionLocal", mock_session)

        exit_code = evaluator.main()

        assert exit_code == 0
        # Prediction should remain unchanged (already evaluated)
        assert sample_evaluated_prediction_for_today.evaluated_at is not None

    def test_missing_actual_price_success(
        self,
        db_session: Session,
        sample_unevaluated_prediction_for_today: Prediction,
        monkeypatch,
    ) -> None:
        """
        Gherkin Scenario 3: Missing actual price in btc_prices.

        Given a prediction exists for predicted_for=today
        And btc_prices has no record for today 7am
        When I run evaluator.main()
        Then the job logs "Actual price not available yet"
        And prediction is not updated
        And exit code is 0 (will retry tomorrow)
        """
        prediction_id = sample_unevaluated_prediction_for_today.id

        # Mock SessionLocal to return our test session, but don't close it
        def mock_session():
            session = db_session
            session.close = lambda: None
            return session

        monkeypatch.setattr("workers.daily.evaluator.SessionLocal", mock_session)

        exit_code = evaluator.main()

        assert exit_code == 0

        # Re-fetch prediction to verify it was NOT updated
        from sqlalchemy import select

        from shared.db.models import Prediction

        stmt = select(Prediction).where(Prediction.id == prediction_id)
        prediction = db_session.execute(stmt).scalar_one()

        assert prediction.actual_price is None
        assert prediction.evaluated_at is None
        assert prediction.error_abs is None

    def test_error_handling_database_exception(
        self,
        db_session: Session,
        sample_unevaluated_prediction_for_today: Prediction,
        sample_actual_price_for_today: BtcPrice,
        monkeypatch,
    ) -> None:
        """
        Should continue processing and return exit code 0.

        Even when individual predictions fail.
        """

        def mock_session():
            session = db_session
            session.close = lambda: None
            return session

        monkeypatch.setattr("workers.daily.evaluator.SessionLocal", mock_session)

        # Mock update_prediction to raise an exception
        def mock_update_error(*args, **kwargs):
            raise Exception("Database connection lost")

        monkeypatch.setattr(
            "workers.daily.evaluator.update_prediction", mock_update_error
        )

        exit_code = evaluator.main()

        # Should continue processing and return 0 (error is logged but job doesn't fail)
        assert exit_code == 0
