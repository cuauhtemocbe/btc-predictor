"""
Tests for US-025: Multi-Model Predictions (Parallel)

Tests the multi-model prediction system where:
- Predictor generates predictions from ALL active models
  (when --multi-model flag is used)
- Evaluator evaluates predictions from all models
- System handles individual model failures gracefully
- Idempotency works per-model (not just per-date)

Covers 5 critical Gherkin scenarios from US-025:
1. Multi-model mode generates predictions for all active models
2. CLI flag controls multi vs single mode
3. Evaluator evaluates all model predictions
4. Handle prediction failure for one model
5. Idempotency per model (multi-model mode)
"""

from argparse import Namespace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from shared.db.models import BtcPrice, Model, Prediction
from workers.daily import evaluator, predictor

# ============================================================================
# Additional fixtures for multi-model scenarios
# ============================================================================


@pytest.fixture
def three_active_models(
    db_session: Session,
    cached_linear_artifact: bytes,
    cached_xgboost_artifact: bytes,
    cached_lstm_artifact: bytes,
) -> list[Model]:
    """
    Create 3 trained models (linear, xgboost, lstm) all active.

    Uses cached artifacts from module-scoped fixtures to avoid
    redundant training (3-5s speedup per test).

    Returns:
        List of 3 Model records with is_active=True
    """
    models = []

    # Model 1: LinearRegression (using cached artifact)
    model1 = Model(
        name="linear_v1",
        version="1.0.0",
        params={"window_days": 30},
        artifact=cached_linear_artifact,  # NO training!
        trained_at=datetime.now(UTC),
        train_from=date.today() - timedelta(days=60),
        train_to=date.today() - timedelta(days=1),
        is_active=True,
    )
    db_session.add(model1)
    models.append(model1)

    # Model 2: XGBoost (using cached artifact)
    model2 = Model(
        name="xgboost_v1",
        version="1.0.0",
        params={"window_days": 30, "n_estimators": 100},
        artifact=cached_xgboost_artifact,  # NO training!
        trained_at=datetime.now(UTC),
        train_from=date.today() - timedelta(days=60),
        train_to=date.today() - timedelta(days=1),
        is_active=True,
    )
    db_session.add(model2)
    models.append(model2)

    # Model 3: LSTM (using cached artifact)
    model3 = Model(
        name="lstm_v1",
        version="1.0.0",
        params={"window_days": 30, "epochs": 10},
        artifact=cached_lstm_artifact,  # NO training!
        trained_at=datetime.now(UTC),
        train_from=date.today() - timedelta(days=60),
        train_to=date.today() - timedelta(days=1),
        is_active=True,
    )
    db_session.add(model3)
    models.append(model3)

    db_session.commit()

    # Refresh all models to get their IDs
    for model in models:
        db_session.refresh(model)

    return models


# ============================================================================
# Test 1: Multi-model mode generates predictions for all active models
# ============================================================================


class TestMultiModelPredictions:
    """Test that multi-model mode generates predictions from ALL active models."""

    def test_multi_model_mode_generates_predictions_for_all_active_models(
        self,
        db_session: Session,
        three_active_models: list[Model],
        sample_btc_prices_30_days: list[BtcPrice],
    ) -> None:
        """
        Gherkin Scenario: Predictor generates predictions from all active models

        Given there are 3 active models (linear, xgboost, lstm)
        When the predictor runs with --multi-model flag
        Then it generates 3 predictions for tomorrow (one per model)
        And all predictions have predicted_for = tomorrow
        And all predictions have the same price_at_prediction (current price)
        """
        # Given: 3 active models exist (from fixture)
        assert len(three_active_models) == 3
        assert all(m.is_active for m in three_active_models)

        tomorrow = date.today() + timedelta(days=1)

        # Verify no predictions exist yet
        count_before = db_session.query(Prediction).count()
        assert count_before == 0

        # Mock parse_args to enable multi-model mode
        def mock_parse_args():
            return Namespace(multi_model=True)

        original_parse_args = predictor.parse_args
        predictor.parse_args = mock_parse_args

        try:
            # When: predictor runs in multi-model mode
            exit_code = predictor.main(session=db_session)

            # Then: job exits successfully
            assert exit_code == 0

            # And: 3 predictions are created (one per model)
            predictions = db_session.query(Prediction).all()
            assert len(predictions) == 3

            # And: all predictions are for tomorrow
            assert all(p.predicted_for == tomorrow for p in predictions)

            # And: predictions are from different models
            model_ids = {p.model_id for p in predictions}
            assert len(model_ids) == 3  # All 3 models predicted

            # And: all predictions have the same price_at_prediction (current price)
            current_prices = {p.price_at_prediction for p in predictions}
            assert len(current_prices) == 1  # Same current price for all

            # And: all predictions have predicted_price set (not NULL)
            assert all(p.predicted_price is not None for p in predictions)

            # And: evaluation fields are NULL (not evaluated yet)
            assert all(p.actual_price is None for p in predictions)

        finally:
            predictor.parse_args = original_parse_args


# ============================================================================
# Test 2: CLI flag controls multi vs single mode
# ============================================================================


class TestCLIFlag:
    """Test that --multi-model flag controls behavior correctly."""

    def test_single_model_mode_uses_only_first_active_model(
        self,
        db_session: Session,
        three_active_models: list[Model],
        sample_btc_prices_30_days: list[BtcPrice],
    ) -> None:
        """
        Gherkin Scenario: Single-model mode uses only the "best" active model

        Given there are 3 active models
        When the predictor runs WITHOUT --multi-model flag (default)
        Then it generates only 1 prediction (from the first active model)
        """
        # Given: 3 active models exist
        assert len(three_active_models) == 3

        # Mock parse_args to DISABLE multi-model mode (default)
        def mock_parse_args():
            return Namespace(multi_model=False)

        original_parse_args = predictor.parse_args
        predictor.parse_args = mock_parse_args

        try:
            # When: predictor runs in single-model mode (default)
            exit_code = predictor.main(session=db_session)

            # Then: job exits successfully
            assert exit_code == 0

            # And: only 1 prediction is created
            predictions = db_session.query(Prediction).all()
            assert len(predictions) == 1

            # And: the prediction is from the first active model (primary)
            prediction = predictions[0]
            assert prediction.model_id == three_active_models[0].id

        finally:
            predictor.parse_args = original_parse_args

    def test_multi_model_flag_enabled_uses_all_active_models(
        self,
        db_session: Session,
        three_active_models: list[Model],
        sample_btc_prices_30_days: list[BtcPrice],
    ) -> None:
        """
        Gherkin Scenario: CLI flag to enable multi-model mode

        Given there are 3 active models
        When I run predictor with --multi-model flag
        Then multi-model mode is enabled
        And it predicts with all 3 active models
        """
        # Given: 3 active models exist
        assert len(three_active_models) == 3

        # Mock parse_args to ENABLE multi-model mode
        def mock_parse_args():
            return Namespace(multi_model=True)

        original_parse_args = predictor.parse_args
        predictor.parse_args = mock_parse_args

        try:
            # When: predictor runs with --multi-model flag
            exit_code = predictor.main(session=db_session)

            # Then: job exits successfully
            assert exit_code == 0

            # And: 3 predictions are created (all active models)
            predictions = db_session.query(Prediction).all()
            assert len(predictions) == 3

        finally:
            predictor.parse_args = original_parse_args


# ============================================================================
# Test 3: Evaluator evaluates predictions for all models
# ============================================================================


class TestEvaluatorMultiModel:
    """Test that evaluator evaluates predictions from ALL models."""

    def test_evaluator_evaluates_all_model_predictions(
        self,
        db_session: Session,
        three_active_models: list[Model],
        sample_actual_price_for_today: BtcPrice,
        monkeypatch,
    ) -> None:
        """
        Gherkin Scenario: Evaluator evaluates predictions for all models

        Given there are 3 unevaluated predictions for today (from 3 models)
        When the evaluator runs
        Then it evaluates all 3 predictions
        And all predictions have actual_price != NULL
        And all predictions have error metrics calculated
        """
        # Given: 3 unevaluated predictions for today from 3 different models
        today = date.today()

        prediction1 = Prediction(
            model_id=three_active_models[0].id,
            predicted_for=today,
            predicted_at=datetime.now(UTC) - timedelta(hours=2),
            price_at_prediction=Decimal("66000.00"),
            predicted_price=Decimal("67000.00"),
            actual_price=None,
        )
        prediction2 = Prediction(
            model_id=three_active_models[1].id,
            predicted_for=today,
            predicted_at=datetime.now(UTC) - timedelta(hours=2),
            price_at_prediction=Decimal("66000.00"),
            predicted_price=Decimal("67200.00"),
            actual_price=None,
        )
        prediction3 = Prediction(
            model_id=three_active_models[2].id,
            predicted_for=today,
            predicted_at=datetime.now(UTC) - timedelta(hours=2),
            price_at_prediction=Decimal("66000.00"),
            predicted_price=Decimal("66800.00"),
            actual_price=None,
        )

        db_session.add_all([prediction1, prediction2, prediction3])
        db_session.commit()

        # Verify 3 unevaluated predictions exist
        unevaluated = evaluator.find_unevaluated_predictions(db_session, today)
        assert len(unevaluated) == 3

        # Mock SessionLocal to return our test session
        def mock_session():
            session = db_session
            # Override close to be no-op for testing
            session.close = lambda: None
            return session

        monkeypatch.setattr("workers.daily.evaluator.SessionLocal", mock_session)

        # When: evaluator runs
        exit_code = evaluator.main()

        # Then: job exits successfully
        assert exit_code == 0

        # And: all 3 predictions are now evaluated
        evaluated = (
            db_session.query(Prediction)
            .filter(Prediction.predicted_for == today)
            .filter(Prediction.actual_price.isnot(None))
            .all()
        )
        assert len(evaluated) == 3

        # And: all predictions have actual_price set (same for all models)
        actual_prices = {p.actual_price for p in evaluated}
        assert len(actual_prices) == 1  # Same actual price
        assert Decimal("67500.00") in actual_prices  # From fixture

        # And: all predictions have error metrics calculated
        for prediction in evaluated:
            assert prediction.error_abs is not None
            assert prediction.error_pct is not None
            assert prediction.direction_correct is not None
            assert prediction.pnl_simulated is not None
            assert prediction.evaluated_at is not None


# ============================================================================
# Test 4: Handle prediction failure for one model
# ============================================================================


class TestMultiModelFailureHandling:
    """Test that multi-model mode handles individual model failures gracefully."""

    def test_multi_model_handles_individual_model_failure(
        self,
        db_session: Session,
        three_active_models: list[Model],
        sample_btc_prices_30_days: list[BtcPrice],
    ) -> None:
        """
        Gherkin Scenario: Handle prediction failure for one model

        Given there are 3 active models
        And one model fails to deserialize
        When the predictor runs in multi-model mode
        Then it logs the failure
        And continues predicting with the other 2 models
        And saves 2 predictions (not 3)
        And the job exits successfully (code 0)
        """
        # Given: 3 active models exist
        assert len(three_active_models) == 3

        # Mock deserialize_model to fail for LSTM (model 3)
        original_deserialize = predictor.deserialize_model

        def mock_deserialize(model_record: Model):
            if model_record.name == "lstm_v1":
                raise RuntimeError("LSTM deserialization failed (simulated)")
            return original_deserialize(model_record)

        # Mock parse_args for multi-model mode
        def mock_parse_args():
            return Namespace(multi_model=True)

        original_parse_args = predictor.parse_args
        predictor.parse_args = mock_parse_args
        predictor.deserialize_model = mock_deserialize

        try:
            # When: predictor runs in multi-model mode
            exit_code = predictor.main(session=db_session)

            # Then: job exits successfully (despite 1 model failing)
            assert exit_code == 0

            # And: only 2 predictions are created (linear + xgboost)
            predictions = db_session.query(Prediction).all()
            assert len(predictions) == 2

            # And: predictions are from models 1 and 2 (not model 3)
            model_ids = {p.model_id for p in predictions}
            assert three_active_models[0].id in model_ids  # linear
            assert three_active_models[1].id in model_ids  # xgboost
            assert three_active_models[2].id not in model_ids  # lstm failed

        finally:
            predictor.parse_args = original_parse_args
            predictor.deserialize_model = original_deserialize


# ============================================================================
# Test 5: Idempotency per model (multi-model mode)
# ============================================================================


class TestMultiModelIdempotency:
    """Test that multi-model mode idempotency works per-model."""

    def test_multi_model_idempotency_per_model(
        self,
        db_session: Session,
        three_active_models: list[Model],
        sample_btc_prices_30_days: list[BtcPrice],
    ) -> None:
        """
        Gherkin Scenario: Idempotency - re-running predictor doesn't
        duplicate predictions

        Given the predictor already created 3 predictions for tomorrow (3 models)
        When the predictor runs again in multi-model mode
        Then it checks if predictions exist for (predicted_for=tomorrow, model_id=X)
        And skips insertion for all 3 models
        And logs "Predictions already exist, skipping"
        And the job exits successfully (code 0)
        """
        # Given: 3 predictions already exist for tomorrow (one per model)
        tomorrow = date.today() + timedelta(days=1)

        for model in three_active_models:
            prediction = Prediction(
                model_id=model.id,
                predicted_for=tomorrow,
                predicted_at=datetime.now(UTC),
                price_at_prediction=Decimal("51000.00"),
                predicted_price=Decimal("51500.00"),
                actual_price=None,
            )
            db_session.add(prediction)

        db_session.commit()

        # Verify 3 predictions exist
        count_before = db_session.query(Prediction).count()
        assert count_before == 3

        # Mock parse_args for multi-model mode
        def mock_parse_args():
            return Namespace(multi_model=True)

        original_parse_args = predictor.parse_args
        predictor.parse_args = mock_parse_args

        try:
            # When: predictor runs again in multi-model mode
            exit_code = predictor.main(session=db_session)

            # Then: job exits successfully (idempotent)
            assert exit_code == 0

            # And: no additional predictions are created (still just 3)
            count_after = db_session.query(Prediction).count()
            assert count_after == count_before  # Still 3

            # And: all 3 predictions are unchanged
            predictions = db_session.query(Prediction).all()
            assert len(predictions) == 3
            assert all(p.predicted_for == tomorrow for p in predictions)

        finally:
            predictor.parse_args = original_parse_args
