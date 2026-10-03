"""
Integration tests for all ML models.

This test suite validates that all models work together consistently on the data
of the reboot (return features of shared.features, next-day log return target):
1. All models implement BaseModel interface
2. All models can be stored in database
3. All models produce valid predictions
4. All models can be imported from workers.daily.models
"""

from typing import Any

import numpy as np
import pytest
from sqlalchemy.orm import Session

from shared.features import FeatureSet
from workers.daily.models import (
    ARIMAModel,
    BaseModel,
    LinearRegressionModel,
    LSTMModel,
    XGBoostModel,
)

WINDOW_DAYS = 10
N_FEATURES = 2 * WINDOW_DAYS + 1

# Constructor arguments of each model for the return features. LSTM trains for a
# few epochs only, to keep the suite fast.
MODEL_KWARGS: dict[type[BaseModel], dict[str, Any]] = {
    LinearRegressionModel: {},
    XGBoostModel: {},
    LSTMModel: {"epochs": 5},
    ARIMAModel: {"order": (5, 0, 0)},
}
MODEL_CLASSES = list(MODEL_KWARGS)
MODEL_NAMES = {
    LinearRegressionModel: "linear_v1",
    XGBoostModel: "xgboost_v1",
    LSTMModel: "lstm_v1",
    ARIMAModel: "arima_v1",
}


def build(model_class: type[BaseModel]) -> BaseModel:
    """Model of the class for the return features, with its test hyperparameters."""
    return model_class(  # type: ignore[call-arg]
        window_days=WINDOW_DAYS,
        n_features=N_FEATURES,
        **MODEL_KWARGS[model_class],
    )


class TestAllModelsIntegration:
    """Integration tests for all models."""

    @pytest.mark.parametrize("model_class", MODEL_CLASSES)
    def test_all_models_inherit_basemodel(self, model_class: type[BaseModel]) -> None:
        """
        Gherkin Scenario: All models implement BaseModel interface

        Given a model class (Linear, XGBoost, LSTM, ARIMA)
        When I create an instance for the return features
        Then it inherits from BaseModel
        """
        assert isinstance(build(model_class), BaseModel)

    @pytest.mark.parametrize("model_class", MODEL_CLASSES)
    def test_all_models_have_required_methods(
        self, model_class: type[BaseModel]
    ) -> None:
        """
        Gherkin Scenario: All models have required methods

        Given a model class
        When I inspect it
        Then it has methods: train(), predict(), serialize(), deserialize()
        And it has property: is_trained
        """
        model = build(model_class)

        # Check methods exist and are callable
        assert callable(model.train)
        assert callable(model.predict)
        assert callable(model.serialize)
        assert callable(model_class.deserialize)

        # Check property exists
        assert isinstance(model.is_trained, bool)

    @pytest.mark.parametrize("model_class", MODEL_CLASSES)
    def test_all_models_expose_the_window_and_feature_count(
        self, model_class: type[BaseModel]
    ) -> None:
        """
        Gherkin Scenario: All models are built from the window and feature count

        Given a model class
        When I create it with the window of the trainer and the return feature count
        Then it keeps both, so the trainer can build every model the same way
        """
        model = build(model_class)

        assert isinstance(
            model, LinearRegressionModel | XGBoostModel | LSTMModel | ARIMAModel
        )
        assert model.window_days == WINDOW_DAYS
        assert model.n_features == N_FEATURES

    @pytest.mark.parametrize("model_class", MODEL_CLASSES)
    def test_all_models_serialize_to_bytes(
        self, model_class: type[BaseModel], return_training_set: FeatureSet
    ) -> None:
        """
        Gherkin Scenario: All models serialize to bytes

        Given a trained model
        When I call serialize()
        Then it returns bytes
        And the bytes size is reasonable (< 10MB)
        """
        model = build(model_class)
        model.train(return_training_set.X, return_training_set.y)

        model_bytes = model.serialize()

        assert isinstance(model_bytes, bytes)
        assert len(model_bytes) > 0
        assert len(model_bytes) < 10_000_000  # < 10MB

    @pytest.mark.parametrize("model_class", MODEL_CLASSES)
    def test_all_models_predictions_valid(
        self,
        model_class: type[BaseModel],
        return_training_set: FeatureSet,
        latest_return_features: np.ndarray,
    ) -> None:
        """
        Gherkin Scenario: All models produce valid predictions

        Given a trained model
        When I call predict(X) with the features of the latest day
        Then it returns a single float prediction
        And the prediction is a finite log return (a day moves a few percent)
        """
        model = build(model_class)
        model.train(return_training_set.X, return_training_set.y)

        prediction = model.predict(latest_return_features)

        name = MODEL_NAMES[model_class]
        assert isinstance(prediction, float), f"{name}: prediction is not float"
        assert np.isfinite(prediction), f"{name}: prediction is not finite"
        assert abs(prediction) < 1.0, f"{name}: {prediction} is not a daily return"

    def test_all_models_can_be_imported(self) -> None:
        """
        Gherkin Scenario: All models are importable from workers.daily.models

        When I import from workers.daily.models
        Then I can access: BaseModel, LinearRegressionModel, XGBoostModel,
        LSTMModel, ARIMAModel
        """
        # This test already passes if the imports at the top work
        assert BaseModel is not None
        assert LinearRegressionModel is not None
        assert XGBoostModel is not None
        assert LSTMModel is not None
        assert ARIMAModel is not None

    @pytest.mark.parametrize("model_class", MODEL_CLASSES)
    def test_store_all_models_in_db(
        self,
        model_class: type[BaseModel],
        return_training_set: FeatureSet,
        latest_return_features: np.ndarray,
        db_session: Session,
    ) -> None:
        """
        Gherkin Scenario: All models can be stored in database

        Given a trained model
        When I serialize it and store in models table
        Then the artifact is stored as bytes
        And I can retrieve and deserialize it
        And predictions match
        """
        from datetime import UTC, date, datetime, timedelta

        from shared.db.models import Model
        from shared.features import LOG_RETURN_TARGET

        # Train model
        model = build(model_class)
        model.train(return_training_set.X, return_training_set.y)

        # Serialize and store
        model_record = Model(
            name=MODEL_NAMES[model_class],
            version="1.0.0",
            params={"window_days": WINDOW_DAYS, "target": LOG_RETURN_TARGET},
            artifact=model.serialize(),
            trained_at=datetime.now(UTC),
            train_from=date.today() - timedelta(days=120),
            train_to=date.today() - timedelta(days=1),
            is_active=True,
        )

        db_session.add(model_record)
        db_session.commit()
        db_session.refresh(model_record)

        # Verify stored
        assert model_record.id is not None
        assert isinstance(model_record.artifact, bytes)

        # Retrieve and deserialize
        restored_model = model_class.deserialize(model_record.artifact)

        # Verify predictions match
        original_pred = model.predict(latest_return_features)
        restored_pred = restored_model.predict(latest_return_features)
        assert np.isclose(original_pred, restored_pred, atol=1e-6)


class TestModelComparison:
    """Compare characteristics of different models."""

    def test_model_serialization_sizes(self, return_training_set: FeatureSet) -> None:
        """
        Compare serialization sizes across models.

        Linear and XGBoost should be small (< 1MB for Linear, < 5MB for XGBoost).
        LSTM should be larger due to neural network weights (< 10MB).
        ARIMA should be medium (< 5MB).
        """
        sizes_mb = {}
        for model_class in MODEL_CLASSES:
            model = build(model_class)
            model.train(return_training_set.X, return_training_set.y)
            sizes_mb[model_class] = len(model.serialize()) / 1_000_000

        assert sizes_mb[LinearRegressionModel] < 1.0
        assert sizes_mb[XGBoostModel] < 5.0
        assert sizes_mb[LSTMModel] < 10.0
        assert sizes_mb[ARIMAModel] < 5.0
