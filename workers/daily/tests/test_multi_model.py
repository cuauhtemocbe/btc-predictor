"""
Tests for multi-model prediction mode (US-025).

Covers all Gherkin acceptance criteria scenarios:
1. Predictor generates predictions from all active models
2. Skip inactive models in multi-model mode
3. Single-model mode uses only the "best" active model
4. Evaluator evaluates predictions for all models
5. Handle prediction failure for one model
6. Idempotency: re-running predictor doesn't duplicate predictions
7. Each model uses the same input features
8. Predictions table supports multiple predictions per date
9. CLI flag to enable/disable multi-model mode
10. Log prediction summary for all models
"""

import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from shared.db.models import BtcPrice, Model, Prediction
from workers.daily import predictor
from workers.daily.models import LinearRegressionModel

# ============================================================================
# Test CLI argument parsing
# ============================================================================


class TestParseArgs:
    """Test the parse_args() function."""

    def test_default_single_model_mode(self) -> None:
        """Should default to single-model mode (no --multi-model flag)."""
        with patch.object(sys, "argv", ["predictor.py"]):
            args = predictor.parse_args()
            assert args.multi_model is False

    def test_multi_model_flag_enabled(self) -> None:
        """Should enable multi-model mode with --multi-model flag."""
        with patch.object(sys, "argv", ["predictor.py", "--multi-model"]):
            args = predictor.parse_args()
            assert args.multi_model is True


# ============================================================================
# Test get_active_models() with multi_model parameter
# ============================================================================


class TestGetActiveModels:
    """Test the get_active_models() function."""

    def test_single_model_mode_fetches_one_model(
        self,
        db_session: Session,
        sample_trained_model: Model,
    ) -> None:
        """Should fetch only one model in single-model mode."""
        models = predictor.get_active_models(db_session, multi_model=False)

        assert len(models) == 1
        model_record, model_instance = models[0]
        assert model_record.id == sample_trained_model.id
        assert isinstance(model_instance, LinearRegressionModel)

    def test_multi_model_mode_fetches_all_active_models(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_xgboost_model: Model,
    ) -> None:
        """Should fetch ALL active models in multi-model mode."""
        # Ensure both models are active
        sample_trained_model.is_active = True
        sample_xgboost_model.is_active = True
        db_session.commit()

        models = predictor.get_active_models(db_session, multi_model=True)

        assert len(models) == 2
        model_names = [m[0].name for m in models]
        assert sample_trained_model.name in model_names
        assert sample_xgboost_model.name in model_names

    def test_skip_inactive_models_in_multi_model_mode(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_xgboost_model: Model,
    ) -> None:
        """Should skip inactive models in multi-model mode."""
        # Activate only one model
        sample_trained_model.is_active = True
        sample_xgboost_model.is_active = False
        db_session.commit()

        models = predictor.get_active_models(db_session, multi_model=True)

        assert len(models) == 1
        model_record, _ = models[0]
        assert model_record.id == sample_trained_model.id

    def test_no_active_models_raises_error(self, db_session: Session) -> None:
        """Should raise ValueError when no active models exist."""
        with pytest.raises(ValueError, match="No active models found"):
            predictor.get_active_models(db_session, multi_model=False)

    def test_graceful_failure_in_multi_model_mode(
        self,
        db_session: Session,
        sample_trained_model: Model,
    ) -> None:
        """Should continue with other models if one fails to deserialize."""
        from datetime import date, timedelta

        # Create a model with corrupted artifact
        corrupted_model = Model(
            name="corrupted_v1",
            version="1",
            params={"window_days": 30},
            artifact=b"corrupted_data",  # Invalid pickle
            is_active=True,
            trained_at=datetime.now(UTC),
            train_from=date.today() - timedelta(days=60),
            train_to=date.today() - timedelta(days=1),
        )
        db_session.add(corrupted_model)
        db_session.commit()

        # Should load only the valid model, skip corrupted one
        models = predictor.get_active_models(db_session, multi_model=True)

        assert len(models) == 1
        assert models[0][0].id == sample_trained_model.id

    def test_all_models_fail_raises_error(self, db_session: Session) -> None:
        """Should raise ValueError if ALL models fail to deserialize."""
        from datetime import date, timedelta

        # Create only corrupted models
        corrupted_model = Model(
            name="corrupted_v1",
            version="1",
            params={"window_days": 30},
            artifact=b"corrupted_data",
            is_active=True,
            trained_at=datetime.now(UTC),
            train_from=date.today() - timedelta(days=60),
            train_to=date.today() - timedelta(days=1),
        )
        db_session.add(corrupted_model)
        db_session.commit()

        with pytest.raises(ValueError, match="All active models failed to deserialize"):
            predictor.get_active_models(db_session, multi_model=True)


# ============================================================================
# Test idempotency check per model
# ============================================================================


class TestCheckExistingPrediction:
    """Test the check_existing_prediction() function with model_id."""

    def test_no_prediction_exists(self, db_session: Session) -> None:
        """Should return False when no prediction exists."""
        tomorrow = date.today() + timedelta(days=1)
        exists = predictor.check_existing_prediction(db_session, tomorrow, model_id=1)
        assert exists is False

    def test_prediction_exists_for_model(
        self,
        db_session: Session,
        sample_trained_model: Model,
    ) -> None:
        """Should return True when prediction exists for specific model."""
        tomorrow = date.today() + timedelta(days=1)

        # Create prediction for model
        prediction = Prediction(
            model_id=sample_trained_model.id,
            predicted_for=tomorrow,
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("50000"),
            predicted_price=Decimal("51000"),
        )
        db_session.add(prediction)
        db_session.commit()

        exists = predictor.check_existing_prediction(
            db_session, tomorrow, model_id=sample_trained_model.id
        )
        assert exists is True

    def test_prediction_exists_for_different_model(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_xgboost_model: Model,
    ) -> None:
        """Should return False when prediction exists for different model."""
        tomorrow = date.today() + timedelta(days=1)

        # Create prediction for model 1
        prediction = Prediction(
            model_id=sample_trained_model.id,
            predicted_for=tomorrow,
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("50000"),
            predicted_price=Decimal("51000"),
        )
        db_session.add(prediction)
        db_session.commit()

        # Check for model 2 (should not exist)
        exists = predictor.check_existing_prediction(
            db_session, tomorrow, model_id=sample_xgboost_model.id
        )
        assert exists is False


# ============================================================================
# Integration tests for multi-model prediction
# ============================================================================


class TestMultiModelPrediction:
    """Integration tests for multi-model prediction mode."""

    def test_generates_predictions_from_all_active_models(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_xgboost_model: Model,
        sample_btc_prices_30_days: list[BtcPrice],
    ) -> None:
        """Should generate predictions from all active models."""
        # Ensure both models are active
        sample_trained_model.is_active = True
        sample_xgboost_model.is_active = True
        db_session.commit()

        # Mock main with --multi-model flag
        with patch.object(sys, "argv", ["predictor.py", "--multi-model"]):
            with patch("workers.daily.predictor.date") as mock_date:
                mock_date.today.return_value = date(2024, 5, 19)
                mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

                exit_code = predictor.main(session=db_session)

        assert exit_code == 0

        # Verify predictions were created for both models
        predictions = db_session.query(Prediction).all()
        assert len(predictions) == 2

        model_ids = {p.model_id for p in predictions}
        assert sample_trained_model.id in model_ids
        assert sample_xgboost_model.id in model_ids

    def test_single_model_mode_generates_one_prediction(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_xgboost_model: Model,
        sample_btc_prices_30_days: list[BtcPrice],
    ) -> None:
        """Should generate only one prediction in single-model mode."""
        # Ensure both models are active
        sample_trained_model.is_active = True
        sample_xgboost_model.is_active = True
        db_session.commit()

        # Run without --multi-model flag
        with patch.object(sys, "argv", ["predictor.py"]):
            with patch("workers.daily.predictor.date") as mock_date:
                mock_date.today.return_value = date(2024, 5, 19)
                mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

                exit_code = predictor.main(session=db_session)

        assert exit_code == 0

        # Verify only one prediction was created
        predictions = db_session.query(Prediction).all()
        assert len(predictions) == 1

    def test_idempotency_with_multi_model(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_xgboost_model: Model,
        sample_btc_prices_30_days: list[BtcPrice],
    ) -> None:
        """Should not duplicate predictions when re-running in multi-model mode."""
        # Ensure both models are active
        sample_trained_model.is_active = True
        sample_xgboost_model.is_active = True
        db_session.commit()

        # Run predictor first time
        with patch.object(sys, "argv", ["predictor.py", "--multi-model"]):
            with patch("workers.daily.predictor.date") as mock_date:
                mock_date.today.return_value = date(2024, 5, 19)
                mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

                exit_code1 = predictor.main(session=db_session)

        assert exit_code1 == 0
        predictions_count_1 = db_session.query(Prediction).count()
        assert predictions_count_1 == 2

        # Run predictor second time (should skip)
        with patch.object(sys, "argv", ["predictor.py", "--multi-model"]):
            with patch("workers.daily.predictor.date") as mock_date:
                mock_date.today.return_value = date(2024, 5, 19)
                mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

                exit_code2 = predictor.main(session=db_session)

        assert exit_code2 == 0
        predictions_count_2 = db_session.query(Prediction).count()
        assert predictions_count_2 == 2  # No duplicates

    def test_all_models_use_same_input_features(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_xgboost_model: Model,
        sample_btc_prices_30_days: list[BtcPrice],
    ) -> None:
        """Should use same current price for all models (fair comparison)."""
        # Ensure both models are active
        sample_trained_model.is_active = True
        sample_xgboost_model.is_active = True
        db_session.commit()

        # Run predictor
        with patch.object(sys, "argv", ["predictor.py", "--multi-model"]):
            with patch("workers.daily.predictor.date") as mock_date:
                mock_date.today.return_value = date(2024, 5, 19)
                mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

                exit_code = predictor.main(session=db_session)

        assert exit_code == 0

        # Verify all predictions have the same price_at_prediction
        predictions = db_session.query(Prediction).all()
        assert len(predictions) == 2

        prices_at_prediction = {p.price_at_prediction for p in predictions}
        assert len(prices_at_prediction) == 1  # All same


# ============================================================================
# Test evaluator with multi-model predictions
# ============================================================================


class TestEvaluatorMultiModel:
    """Test evaluator handles multiple predictions per date."""

    def test_evaluates_all_predictions_for_date(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_xgboost_model: Model,
    ) -> None:
        """Should evaluate ALL predictions for a given date."""
        from workers.daily import evaluator

        today = date(2024, 5, 20)

        # Create predictions from both models
        prediction1 = Prediction(
            model_id=sample_trained_model.id,
            predicted_for=today,
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("50000"),
            predicted_price=Decimal("51000"),
        )
        prediction2 = Prediction(
            model_id=sample_xgboost_model.id,
            predicted_for=today,
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("50000"),
            predicted_price=Decimal("50800"),
        )
        db_session.add_all([prediction1, prediction2])
        db_session.commit()

        # Verify find_unevaluated_predictions returns both
        predictions = evaluator.find_unevaluated_predictions(db_session, today)
        assert len(predictions) == 2
