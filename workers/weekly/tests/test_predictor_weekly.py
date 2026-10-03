"""
Tests for the weekly predictor job.

Covers Gherkin acceptance criteria scenarios from US-022:
1. Weekly predictor runs and predicts 7 days ahead
2. Uses daily close prices (not hourly)
3. Idempotency (prediction already exists)
4. Insufficient data error handling
"""

import math
import runpy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from shared.db.models import Model, Prediction, Price
from shared.features import DailySeries
from workers.daily import predictor as daily_predictor
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
        with pytest.raises(ValueError, match="No active weekly model found"):
            predictor.get_active_model(db_session)


class TestGetRecentSeries:
    """Test the get_recent_series() function the weekly predictor uses."""

    def test_success_31_days(
        self, db_session: Session, sample_daily_close_prices_31_days: list[Price]
    ) -> None:
        """Should fetch 31 DAILY closes and volumes (not hourly)."""
        series = daily_predictor.get_recent_series(db_session, days=31)

        # Should return exactly 31 rows (one per day, not 24 per day)
        assert len(series) == 31
        assert len(series.volumes) == 31

        # Should be oldest to newest (chronological)
        assert series.closes[0] < series.closes[-1]

        # Should be Decimal type
        assert all(isinstance(p, Decimal) for p in series.closes)

    def test_insufficient_data(
        self, db_session: Session, sample_daily_close_prices_10_days: list[Price]
    ) -> None:
        """Should raise ValueError when insufficient data (< 31 days)."""
        with pytest.raises(
            ValueError, match="Insufficient data: need 31 days, have 10"
        ):
            daily_predictor.get_recent_series(db_session, days=31)

    def test_no_data(self, db_session: Session) -> None:
        """Should raise ValueError when no price data exists."""
        with pytest.raises(ValueError, match="Insufficient data: need 31 days, have 0"):
            daily_predictor.get_recent_series(db_session, days=31)

    def test_uses_daily_not_hourly(
        self, db_session: Session, sample_daily_close_prices_31_days: list[Price]
    ) -> None:
        """
        Gherkin: Weekly predictor uses daily close prices (not hourly).

        Given 31 days of hourly price data (744 records)
        When get_recent_series() is called with days=31
        Then it should return 31 rows (1 per day)
        And not 744 rows (24 per day)
        """
        # We have 31 days * 24 hours = 744 records in DB
        total_records = db_session.query(Price).count()
        assert total_records == 744

        # But get_recent_series should return only 31 (daily)
        series = daily_predictor.get_recent_series(db_session, days=31)
        assert len(series) == 31


class TestPrepareFeatures:
    """The weekly predictor builds the same return features as the daily one."""

    def test_uses_the_daily_feature_builder(self) -> None:
        assert predictor.prepare_features is daily_predictor.prepare_features

    def test_30_day_window_gives_61_return_features(self) -> None:
        series = DailySeries(
            closes=[Decimal(50000 + i * 10) for i in range(31)],
            volumes=[Decimal(1000 + i) for i in range(31)],
        )

        X = predictor.prepare_features(series, window_days=30)

        assert X.shape == (1, 61)


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
        sample_daily_close_prices_31_days: list[Price],
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

    def test_stored_price_is_last_close_times_exp_of_the_7_day_return(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_daily_close_prices_31_days: list[Price],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Given a weekly model that predicts a 7-day log return of +3%
        When the weekly predictor runs
        Then the stored price is the last close * exp(0.03)
        """
        monkeypatch.setattr(predictor, "SessionLocal", lambda: db_session)
        monkeypatch.setattr(LinearRegressionModel, "predict", lambda self, X: 0.03)

        assert predictor.main() == 0

        prediction = db_session.query(Prediction).one()
        assert float(prediction.predicted_price) == pytest.approx(
            float(prediction.price_at_prediction) * math.exp(0.03)
        )
        assert prediction.predicted_price > prediction.price_at_prediction

    def test_price_level_model_is_rejected(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_daily_close_prices_31_days: list[Price],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A weekly model stored before #104 (price target) is not read as a return."""
        sample_trained_model.params = {"window_days": 30, "horizon_days": 7}
        db_session.commit()
        monkeypatch.setattr(predictor, "SessionLocal", lambda: db_session)

        assert predictor.main() == 1
        assert db_session.query(Prediction).count() == 0

    def test_idempotency_skips_existing_prediction(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_daily_close_prices_31_days: list[Price],
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
        sample_daily_close_prices_10_days: list[Price],
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
        sample_daily_close_prices_31_days: list[Price],
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


# ============================================================================
# Models the weekly predictor cannot load, and the module entry point (#159)
# ============================================================================


def _add_active_weekly_model(db_session: Session, name: str, artifact: bytes) -> Model:
    record = Model(
        name=name,
        version="1.0.0",
        params={"window_days": 30, "horizon_days": 7},
        artifact=artifact,
        trained_at=datetime.now(UTC),
        train_from=date.today() - timedelta(days=60),
        train_to=date.today() - timedelta(days=1),
        timeframe="1w",
        is_active=True,
    )
    db_session.add(record)
    db_session.commit()
    return record


class TestUnloadableActiveModel:
    """An active weekly model the predictor cannot deserialize."""

    def test_unknown_model_type_is_a_runtime_error(self, db_session: Session) -> None:
        _add_active_weekly_model(db_session, "mystery_weekly", b"")

        with pytest.raises(RuntimeError, match="Unknown model type: mystery_weekly"):
            predictor.get_active_model(db_session)

    def test_corrupt_artifact_is_a_runtime_error(self, db_session: Session) -> None:
        _add_active_weekly_model(db_session, "linear_weekly_v1", b"corrupt")

        with pytest.raises(RuntimeError, match="Failed to deserialize model"):
            predictor.get_active_model(db_session)

    def test_main_returns_1_and_stores_nothing(
        self,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
        sample_daily_close_prices_31_days: list[Price],
    ) -> None:
        _add_active_weekly_model(db_session, "mystery_weekly", b"")
        monkeypatch.setattr(predictor, "SessionLocal", lambda: db_session)

        assert predictor.main() == 1

        assert db_session.query(Prediction).count() == 0


@pytest.mark.filterwarnings("ignore:.*found in sys.modules:RuntimeWarning")
def test_main_returns_1_on_an_unexpected_error(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: object, **kwargs: object) -> bool:
        raise KeyError("boom")

    monkeypatch.setattr(predictor, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(predictor, "check_existing_prediction", explode)

    assert predictor.main() == 1


@pytest.mark.filterwarnings("ignore:.*found in sys.modules:RuntimeWarning")
def test_running_the_module_exits_with_the_exit_code_of_main(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``python -m workers.weekly.predictor`` ends in ``sys.exit(main())``."""
    # runpy re-executes the module, which re-imports SessionLocal from here. No
    # active weekly model exists, so main() fails and the exit code is 1.
    monkeypatch.setattr("shared.db.database.SessionLocal", lambda: db_session)

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("workers.weekly.predictor", run_name="__main__")

    assert exit_info.value.code == 1
