"""
Tests for the weekly predictor job.

Covers Gherkin acceptance criteria scenarios from US-022:
1. Weekly predictor runs and predicts 7 days ahead
2. Uses daily close prices (not hourly)
3. Idempotency (prediction already exists)
4. Insufficient data error handling
"""

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest
from shared.db.models import BtcPrice, Model, Prediction
from sqlalchemy.orm import Session

from workers.weekly import predictor
from workers.weekly.models import LinearRegressionModel

# ============================================================================
# Unit tests for helper functions
# ============================================================================


class TestGetActiveModel:
    """Test the get_active_model() function."""

    def test_success(self, db_session: Session, sample_trained_model: Model) -> None:
        """Should load and deserialize the active model."""
        model_record, model_instance = predictor.get_active_model(db_session)

        assert model_record.id == sample_trained_model.id
        assert model_record.is_active is True
        assert isinstance(model_instance, LinearRegressionModel)

    def test_no_active_model(self, db_session: Session) -> None:
        """Should raise ValueError when no active model exists."""
        with pytest.raises(ValueError, match="No active model found"):
            predictor.get_active_model(db_session)


class TestGetDailyClosePrices:
    """Test the get_daily_close_prices() function."""

    def test_success_30_days(
        self, db_session: Session, sample_daily_close_prices_30_days: list[BtcPrice]
    ) -> None:
        """Should fetch 30 DAILY close prices (not hourly)."""
        prices = predictor.get_daily_close_prices(db_session, window_days=30)

        # Should return exactly 30 prices (one per day, not 24 per day)
        assert len(prices) == 30

        # Should be oldest to newest (chronological)
        assert prices[0] < prices[-1]

        # Should be Decimal type
        assert all(isinstance(p, Decimal) for p in prices)

    def test_insufficient_data(
        self, db_session: Session, sample_daily_close_prices_10_days: list[BtcPrice]
    ) -> None:
        """Should raise ValueError when insufficient data (< 30 days)."""
        with pytest.raises(
            ValueError, match="Insufficient data: need 30 days, have 10"
        ):
            predictor.get_daily_close_prices(db_session, window_days=30)

    def test_no_data(self, db_session: Session) -> None:
        """Should raise ValueError when no price data exists."""
        with pytest.raises(ValueError, match="Insufficient data: need 30 days, have 0"):
            predictor.get_daily_close_prices(db_session, window_days=30)

    def test_uses_daily_not_hourly(
        self, db_session: Session, sample_daily_close_prices_30_days: list[BtcPrice]
    ) -> None:
        """
        Gherkin: Weekly predictor uses daily close prices (not hourly).

        Given 30 days of hourly price data (720 records)
        When get_daily_close_prices() is called with window_days=30
        Then it should return 30 prices (1 per day)
        And not 720 prices (24 per day)
        """
        # We have 30 days * 24 hours = 720 records in DB
        total_records = db_session.query(BtcPrice).count()
        assert total_records == 720

        # But get_daily_close_prices should return only 30 (daily)
        prices = predictor.get_daily_close_prices(db_session, window_days=30)
        assert len(prices) == 30


class TestPrepareFeatures:
    """Test the prepare_features() function."""

    def test_converts_decimals_to_numpy_array(self) -> None:
        """Should convert list of Decimals to numpy array."""
        prices = [Decimal("50000.00"), Decimal("50100.50"), Decimal("50200.75")]

        X = predictor.prepare_features(prices)

        assert isinstance(X, np.ndarray)
        assert X.shape == (1, 3)  # Single sample, 3 features
        assert X.dtype == np.float64
        assert np.allclose(X[0], [50000.00, 50100.50, 50200.75])

    def test_30_day_window(self) -> None:
        """Should handle 30-day window correctly."""
        prices = [Decimal(str(50000 + i * 10)) for i in range(30)]

        X = predictor.prepare_features(prices)

        assert X.shape == (1, 30)
        assert len(X[0]) == 30


class TestCheckExistingPrediction:
    """Test the check_existing_prediction() function."""

    def test_prediction_exists(
        self,
        db_session: Session,
        sample_weekly_prediction_for_next_monday: Prediction,
    ) -> None:
        """
        Gherkin: Idempotency - re-running weekly predictor doesn't duplicate.

        Given a weekly prediction already exists for next Monday
        When check_existing_prediction() is called
        Then it should return True
        """
        next_monday = date.today() + timedelta(days=7)

        exists = predictor.check_existing_prediction(
            db_session, next_monday, timeframe="1w"
        )

        assert exists is True

    def test_prediction_does_not_exist(self, db_session: Session) -> None:
        """Should return False when prediction does not exist."""
        next_monday = date.today() + timedelta(days=7)

        exists = predictor.check_existing_prediction(
            db_session, next_monday, timeframe="1w"
        )

        assert exists is False

    def test_daily_prediction_does_not_interfere(
        self, db_session: Session, sample_trained_model: Model
    ) -> None:
        """
        Should not confuse daily (1d) and weekly (1w) predictions.

        Given a daily prediction exists for a date
        When checking for a weekly prediction for the same date
        Then it should return False (different timeframes)
        """
        target_date = date.today() + timedelta(days=7)

        # Create a DAILY prediction for the date
        daily_prediction = Prediction(
            model_id=sample_trained_model.id,
            predicted_for=target_date,
            timeframe="1d",  # Daily, not weekly
            predicted_at=predictor.datetime.now(predictor.UTC),
            price_at_prediction=Decimal("51000.00"),
            predicted_price=Decimal("51500.00"),
        )
        db_session.add(daily_prediction)
        db_session.commit()

        # Check for WEEKLY prediction (should not exist)
        exists = predictor.check_existing_prediction(
            db_session, target_date, timeframe="1w"
        )

        assert exists is False


class TestSavePrediction:
    """Test the save_prediction() function."""

    def test_creates_weekly_prediction_record(
        self, db_session: Session, sample_trained_model: Model
    ) -> None:
        """
        Gherkin: Weekly predictor creates prediction with timeframe='1w'.

        Given a trained model and predicted price
        When save_prediction() is called with timeframe='1w'
        Then a new Prediction record is created
        And timeframe field is set to '1w'
        And predicted_for is 7 days ahead
        """
        next_monday = date.today() + timedelta(days=7)
        current_price = Decimal("51000.00")
        predicted_price = 51500.00

        prediction = predictor.save_prediction(
            session=db_session,
            model_id=sample_trained_model.id,
            predicted_for=next_monday,
            current_price=current_price,
            predicted_price=predicted_price,
            timeframe="1w",
        )

        # Verify all fields
        assert prediction.id is not None
        assert prediction.model_id == sample_trained_model.id
        assert prediction.predicted_for == next_monday
        assert prediction.timeframe == "1w"  # Weekly timeframe
        assert prediction.predicted_price == Decimal("51500.00")
        assert prediction.price_at_prediction == current_price
        assert prediction.actual_price is None  # Not evaluated yet
        assert prediction.evaluated_at is None


# ============================================================================
# Integration test for main() function
# ============================================================================


class TestMainWeeklyPredictor:
    """Test the main() entry point for weekly predictor job."""

    def test_success_predicts_7_days_ahead(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_daily_close_prices_30_days: list[BtcPrice],
    ) -> None:
        """
        Gherkin: Weekly predictor predicts 7 days ahead.

        Given a trained model exists
        And 30 days of daily close prices are available
        When the weekly predictor runs
        Then it creates a prediction for 7 days ahead
        And timeframe is '1w'
        """
        # Patch SessionLocal to return our test session
        import workers.weekly.predictor as pred_module

        original_session = pred_module.SessionLocal
        pred_module.SessionLocal = lambda: db_session

        try:
            exit_code = predictor.main()

            # Should succeed
            assert exit_code == 0

            # Should create a weekly prediction
            predictions = (
                db_session.query(Prediction).filter(Prediction.timeframe == "1w").all()
            )
            assert len(predictions) == 1

            # Should be for 7 days ahead
            prediction = predictions[0]
            expected_date = date.today() + timedelta(days=7)
            assert prediction.predicted_for == expected_date
            assert prediction.timeframe == "1w"
            assert prediction.predicted_price is not None

        finally:
            pred_module.SessionLocal = original_session

    def test_idempotency_skips_existing_prediction(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_daily_close_prices_30_days: list[BtcPrice],
        sample_weekly_prediction_for_next_monday: Prediction,
    ) -> None:
        """
        Gherkin: Idempotency - re-running doesn't duplicate.

        Given a weekly prediction already exists for next Monday
        And 30 days of price data are available
        When the weekly predictor runs again
        Then it should skip insertion (idempotent)
        And exit with code 0 (success)
        And no duplicate prediction is created
        """
        import workers.weekly.predictor as pred_module

        original_session = pred_module.SessionLocal
        pred_module.SessionLocal = lambda: db_session

        try:
            # Count predictions before
            count_before = (
                db_session.query(Prediction)
                .filter(Prediction.timeframe == "1w")
                .count()
            )
            assert count_before == 1  # From fixture

            # Run predictor
            exit_code = predictor.main()

            # Should succeed (idempotent behavior returns 0)
            assert exit_code == 0

            # Should NOT create a new prediction
            count_after = (
                db_session.query(Prediction)
                .filter(Prediction.timeframe == "1w")
                .count()
            )
            assert count_after == 1  # Still only 1 prediction

        finally:
            pred_module.SessionLocal = original_session

    def test_insufficient_data_fails_gracefully(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_daily_close_prices_10_days: list[BtcPrice],
    ) -> None:
        """
        Gherkin: Weekly predictor fails gracefully if insufficient data.

        Given a trained model exists
        But only 10 days of price data are available
        And the model requires 30 days
        When the weekly predictor runs
        Then it should log "Insufficient data: need 30 days, have 10"
        And exit with code 1 (failure)
        And not insert a prediction
        """
        import workers.weekly.predictor as pred_module

        original_session = pred_module.SessionLocal
        pred_module.SessionLocal = lambda: db_session

        try:
            exit_code = predictor.main()

            # Should fail
            assert exit_code == 1

            # Should NOT create any prediction
            predictions = (
                db_session.query(Prediction).filter(Prediction.timeframe == "1w").all()
            )
            assert len(predictions) == 0

        finally:
            pred_module.SessionLocal = original_session

    def test_no_active_model_fails(
        self,
        db_session: Session,
        sample_daily_close_prices_30_days: list[BtcPrice],
    ) -> None:
        """
        Should fail when no active model exists.

        Given 30 days of price data exist
        But no active model is available
        When the weekly predictor runs
        Then it should exit with code 1 (failure)
        """
        import workers.weekly.predictor as pred_module

        original_session = pred_module.SessionLocal
        pred_module.SessionLocal = lambda: db_session

        try:
            exit_code = predictor.main()

            # Should fail
            assert exit_code == 1

            # Should NOT create any prediction
            predictions = db_session.query(Prediction).all()
            assert len(predictions) == 0

        finally:
            pred_module.SessionLocal = original_session
