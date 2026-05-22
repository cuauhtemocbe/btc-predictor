"""
Tests for the daily predictor job.

Covers all 4 Gherkin acceptance criteria scenarios:
1. Predict next day price (happy path)
2. Insufficient historical data
3. No active model
4. Prediction already exists (idempotency)
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
from shared.db.models import BtcPrice, Model, Prediction
from sqlalchemy.orm import Session

from workers.daily import predictor
from workers.daily.models import LinearRegressionModel

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
        assert model_instance.is_trained is True

    def test_no_active_model(self, db_session: Session) -> None:
        """Should raise ValueError when no active model exists."""
        with pytest.raises(ValueError, match="No active models found"):
            predictor.get_active_model(db_session)

    def test_inactive_model_not_loaded(
        self, db_session: Session, sample_trained_model: Model
    ) -> None:
        """Should not load inactive models."""
        # Deactivate the model
        sample_trained_model.is_active = False
        db_session.commit()

        with pytest.raises(ValueError, match="No active models found"):
            predictor.get_active_model(db_session)


class TestGetRecentPrices:
    """Test the get_recent_prices() function."""

    def test_success_30_days(
        self, db_session: Session, sample_btc_prices_30_days: list[BtcPrice]
    ) -> None:
        """Should fetch 30 recent prices in chronological order."""
        prices = predictor.get_recent_prices(db_session, window_days=30)

        assert len(prices) == 30
        # Should be oldest to newest (chronological)
        assert prices[0] < prices[-1]
        # Should be Decimal type
        assert all(isinstance(p, Decimal) for p in prices)

    def test_insufficient_data(
        self, db_session: Session, sample_btc_prices_10_days: list[BtcPrice]
    ) -> None:
        """Should raise ValueError when insufficient data."""
        with pytest.raises(ValueError, match="Insufficient data: need 30, have 10"):
            predictor.get_recent_prices(db_session, window_days=30)

    def test_no_data(self, db_session: Session) -> None:
        """Should raise ValueError when no price data exists."""
        with pytest.raises(ValueError, match="Insufficient data: need 30, have 0"):
            predictor.get_recent_prices(db_session, window_days=30)


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
        self, db_session: Session, sample_prediction_for_tomorrow: Prediction
    ) -> None:
        """Should return True when prediction exists."""
        tomorrow = date.today() + timedelta(days=1)

        exists = predictor.check_existing_prediction(db_session, tomorrow)

        assert exists is True

    def test_prediction_does_not_exist(self, db_session: Session) -> None:
        """Should return False when prediction does not exist."""
        tomorrow = date.today() + timedelta(days=1)

        exists = predictor.check_existing_prediction(db_session, tomorrow)

        assert exists is False


class TestSavePrediction:
    """Test the save_prediction() function."""

    def test_creates_prediction_record(
        self, db_session: Session, sample_trained_model: Model
    ) -> None:
        """Should create a new prediction record with correct fields."""
        tomorrow = date.today() + timedelta(days=1)
        current_price = Decimal("51000.00")
        predicted_price = 51500.00

        prediction = predictor.save_prediction(
            session=db_session,
            model_id=sample_trained_model.id,
            predicted_for=tomorrow,
            current_price=current_price,
            predicted_price=predicted_price,
        )

        # Verify all fields
        assert prediction.id is not None
        assert prediction.model_id == sample_trained_model.id
        assert prediction.predicted_for == tomorrow
        assert prediction.price_at_prediction == current_price
        assert prediction.predicted_price == Decimal("51500.00")

        # Evaluation fields should be NULL
        assert prediction.actual_price is None
        assert prediction.evaluated_at is None
        assert prediction.error_abs is None
        assert prediction.error_pct is None
        assert prediction.direction_correct is None
        assert prediction.pnl_simulated is None

    def test_predicted_at_is_recent(
        self, db_session: Session, sample_trained_model: Model
    ) -> None:
        """Should set predicted_at to current UTC time."""
        before = datetime.now(UTC)

        prediction = predictor.save_prediction(
            session=db_session,
            model_id=sample_trained_model.id,
            predicted_for=date.today() + timedelta(days=1),
            current_price=Decimal("51000.00"),
            predicted_price=51500.00,
        )

        after = datetime.now(UTC)

        # Handle timezone-naive datetimes from SQLite
        predicted_at = prediction.predicted_at
        if predicted_at.tzinfo is None:
            predicted_at = predicted_at.replace(tzinfo=UTC)

        assert before <= predicted_at <= after


# ============================================================================
# Integration tests for Gherkin scenarios
# ============================================================================


class TestPredictorGherkinScenarios:
    """Integration tests for all 4 Gherkin acceptance criteria."""

    def test_scenario_1_predict_next_day_price(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_btc_prices_30_days: list[BtcPrice],
    ) -> None:
        """
        Gherkin Scenario 1: Predict next day price

        Given the models table has an active LinearRegressionModel (window_days=30)
        And the btc_prices table has 30+ records
        When I run the predictor main()
        Then a new record is inserted into predictions
        And predicted_for = tomorrow's date
        And predicted_price is a float > 0
        And actual_price is NULL (not evaluated yet)
        """
        # Setup: Active model exists, 30+ prices exist (from fixtures)
        tomorrow = date.today() + timedelta(days=1)
        model_id = sample_trained_model.id  # Store ID before main() commits

        # Verify no prediction exists yet
        count_before = db_session.query(Prediction).count()
        assert count_before == 0

        # Mock parse_args to avoid pytest argument conflicts
        from argparse import Namespace

        def mock_parse_args():
            return Namespace(multi_model=False)

        # Mock SessionLocal to return our test session
        original_session_local = predictor.SessionLocal
        original_parse_args = predictor.parse_args
        predictor.SessionLocal = lambda: db_session
        predictor.parse_args = mock_parse_args

        try:
            # Execute
            exit_code = predictor.main()

            # Assert
            assert exit_code == 0

            # Verify prediction was created
            predictions = db_session.query(Prediction).all()
            assert len(predictions) == 1

            prediction = predictions[0]
            assert prediction.predicted_for == tomorrow
            assert prediction.predicted_price > 0
            assert prediction.actual_price is None
            assert prediction.model_id == model_id

        finally:
            # Restore originals
            predictor.SessionLocal = original_session_local
            predictor.parse_args = original_parse_args

    def test_scenario_2_insufficient_historical_data(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_btc_prices_10_days: list[BtcPrice],
    ) -> None:
        """
        Gherkin Scenario 2: Insufficient historical data

        Given the btc_prices table has only 10 records
        And the active model requires window_days=30
        When I run the predictor main()
        Then a ValueError is logged: "Insufficient data: need 30, have 10"
        And no prediction is inserted
        """
        # Setup: Active model exists, only 10 prices (from fixtures)
        count_before = db_session.query(Prediction).count()

        # Mock parse_args and SessionLocal
        from argparse import Namespace

        def mock_parse_args():
            return Namespace(multi_model=False)

        original_session_local = predictor.SessionLocal
        original_parse_args = predictor.parse_args
        predictor.SessionLocal = lambda: db_session
        predictor.parse_args = mock_parse_args

        try:
            # Execute
            exit_code = predictor.main()

            # Assert
            assert exit_code == 1  # Should exit with error code

            # Verify no prediction was created
            count_after = db_session.query(Prediction).count()
            assert count_after == count_before

        finally:
            predictor.SessionLocal = original_session_local
            predictor.parse_args = original_parse_args

    def test_scenario_3_no_active_model(
        self, db_session: Session, sample_btc_prices_30_days: list[BtcPrice]
    ) -> None:
        """
        Gherkin Scenario 3: No active model

        Given the models table has no record with is_active=True
        When I run the predictor main()
        Then a ValueError is logged: "No active models found"
        And the job exits with code 1
        """
        # Setup: No active model (don't use sample_trained_model fixture)
        count_before = db_session.query(Prediction).count()

        # Mock parse_args and SessionLocal
        from argparse import Namespace

        def mock_parse_args():
            return Namespace(multi_model=False)

        original_session_local = predictor.SessionLocal
        original_parse_args = predictor.parse_args
        predictor.SessionLocal = lambda: db_session
        predictor.parse_args = mock_parse_args

        try:
            # Execute
            exit_code = predictor.main()

            # Assert
            assert exit_code == 1

            # Verify no prediction was created
            count_after = db_session.query(Prediction).count()
            assert count_after == count_before

        finally:
            predictor.SessionLocal = original_session_local
            predictor.parse_args = original_parse_args

    def test_scenario_4_prediction_already_exists(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_btc_prices_30_days: list[BtcPrice],
        sample_prediction_for_tomorrow: Prediction,
    ) -> None:
        """
        Gherkin Scenario 4: Prediction already exists for tomorrow

        Given a prediction already exists for predicted_for=tomorrow
        When I run the predictor main()
        Then the job logs "Prediction for tomorrow already exists, skipping"
        And the job exits with code 0 (success, idempotent)
        """
        # Setup: Prediction for tomorrow already exists (from fixture)
        count_before = db_session.query(Prediction).count()
        assert count_before == 1  # The existing prediction

        # Mock parse_args and SessionLocal
        from argparse import Namespace

        def mock_parse_args():
            return Namespace(multi_model=False)

        original_session_local = predictor.SessionLocal
        original_parse_args = predictor.parse_args
        predictor.SessionLocal = lambda: db_session
        predictor.parse_args = mock_parse_args

        try:
            # Execute
            exit_code = predictor.main()

            # Assert
            assert exit_code == 0  # Success (idempotent)

            # Verify no additional prediction was created
            count_after = db_session.query(Prediction).count()
            assert count_after == count_before  # Still just 1

        finally:
            predictor.SessionLocal = original_session_local
            predictor.parse_args = original_parse_args
