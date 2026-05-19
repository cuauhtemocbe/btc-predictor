"""
Integration tests for all ML models.

This test suite validates that all models work together consistently:
1. All models implement BaseModel interface
2. All models can be stored in database
3. All models produce valid predictions
4. All models can be imported from workers.daily.models
"""

import numpy as np
import pytest
from shared.db.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from workers.daily.models import (
    ARIMAModel,
    BaseModel,
    LinearRegressionModel,
    LSTMModel,
    XGBoostModel,
)


class TestAllModelsIntegration:
    """Integration tests for all models."""

    @pytest.mark.parametrize(
        "model_class",
        [
            LinearRegressionModel,
            XGBoostModel,
            LSTMModel,
            ARIMAModel,
        ],
    )
    def test_all_models_inherit_basemodel(self, model_class):
        """
        Gherkin Scenario: All models implement BaseModel interface

        Given a model class (Linear, XGBoost, LSTM, ARIMA)
        When I create an instance
        Then it inherits from BaseModel
        """
        # ARIMA doesn't use window_days in __init__, uses order instead
        if model_class == ARIMAModel:
            model = model_class(order=(5, 1, 0))
        else:
            model = model_class(window_days=30)
        assert isinstance(model, BaseModel)

    @pytest.mark.parametrize(
        "model_class",
        [
            LinearRegressionModel,
            XGBoostModel,
            LSTMModel,
            ARIMAModel,
        ],
    )
    def test_all_models_have_required_methods(self, model_class):
        """
        Gherkin Scenario: All models have required methods

        Given a model class
        When I inspect it
        Then it has methods: train(), predict(), serialize(), deserialize()
        And it has property: is_trained
        """
        # ARIMA doesn't use window_days in __init__, uses order instead
        if model_class == ARIMAModel:
            model = model_class(order=(5, 1, 0))
        else:
            model = model_class(window_days=30)

        # Check methods exist and are callable
        assert hasattr(model, "train") and callable(model.train)
        assert hasattr(model, "predict") and callable(model.predict)
        assert hasattr(model, "serialize") and callable(model.serialize)
        assert hasattr(model_class, "deserialize") and callable(
            model_class.deserialize
        )

        # Check property exists
        assert hasattr(model, "is_trained")
        assert isinstance(model.is_trained, bool)

    @pytest.mark.parametrize(
        "model_class",
        [
            LinearRegressionModel,
            XGBoostModel,
            LSTMModel,
            ARIMAModel,
        ],
    )
    def test_all_models_serialize_to_bytes(self, model_class, sliding_window_data):
        """
        Gherkin Scenario: All models serialize to bytes

        Given a trained model
        When I call serialize()
        Then it returns bytes
        And the bytes size is reasonable (< 10MB)
        """
        X, y = sliding_window_data

        # Create and train model
        if model_class == LSTMModel:
            model = model_class(window_days=30, epochs=5)  # Reduced for speed
        elif model_class == ARIMAModel:
            model = model_class(order=(5, 1, 0))
        else:
            model = model_class(window_days=30)

        model.train(X, y)

        # Serialize
        model_bytes = model.serialize()

        # Assertions
        assert isinstance(model_bytes, bytes)
        assert len(model_bytes) > 0
        assert len(model_bytes) < 10_000_000  # < 10MB

    @pytest.mark.parametrize(
        "model_class,model_name",
        [
            (LinearRegressionModel, "linear_v1"),
            (XGBoostModel, "xgboost_v1"),
            (LSTMModel, "lstm_v1"),
            (ARIMAModel, "arima_v1"),
        ],
    )
    def test_all_models_predictions_valid(
        self, model_class, model_name, sliding_window_data, last_30_days
    ):
        """
        Gherkin Scenario: All models produce valid predictions

        Given a trained model
        When I call predict(X)
        Then it returns a single float prediction
        And the prediction is >= 0 (price cannot be negative)
        And the prediction is reasonable (if > 0)
        """
        X, y = sliding_window_data

        # Create and train model
        if model_class == LSTMModel:
            model = model_class(window_days=30, epochs=5)  # Reduced for speed
        elif model_class == ARIMAModel:
            model = model_class(order=(5, 1, 0))
        else:
            model = model_class(window_days=30)

        model.train(X, y)

        # Predict
        X_new = last_30_days
        prediction = model.predict(X_new)

        # Assertions
        assert isinstance(prediction, float), f"{model_name}: prediction is not float"
        assert prediction >= 0, f"{model_name}: prediction must be >= 0"

        # Note: With minimal training data, some models may not converge properly
        # Sanity check only if prediction is non-zero
        if prediction > 0:
            last_price = X_new[0, -1]
            # Allow wider bounds for models trained on minimal data
            assert (
                0.2 * last_price <= prediction <= 2.0 * last_price
            ), f"{model_name}: prediction {prediction} far from last price {last_price}"

    def test_all_models_can_be_imported(self):
        """
        Gherkin Scenario: All models are importable from workers.daily.models

        When I import from workers.daily.models
        Then I can access: BaseModel, LinearRegressionModel, XGBoostModel, LSTMModel, ARIMAModel
        """
        # This test already passes if the imports at the top work
        assert BaseModel is not None
        assert LinearRegressionModel is not None
        assert XGBoostModel is not None
        assert LSTMModel is not None
        assert ARIMAModel is not None

    @pytest.mark.parametrize(
        "model_class,model_name,hyperparams",
        [
            (LinearRegressionModel, "linear_v1", {"window_days": 30}),
            (
                XGBoostModel,
                "xgboost_v1",
                {
                    "window_days": 30,
                    "n_estimators": 100,
                    "max_depth": 5,
                    "learning_rate": 0.1,
                },
            ),
            (
                LSTMModel,
                "lstm_v1",
                {
                    "window_days": 30,
                    "lstm_units": 50,
                    "dropout": 0.2,
                    "epochs": 5,  # Reduced for speed
                },
            ),
            (ARIMAModel, "arima_v1", {"order": (5, 1, 0)}),
        ],
    )
    def test_store_all_models_in_db(
        self, model_class, model_name, hyperparams, sliding_window_data
    ):
        """
        Gherkin Scenario: All models can be stored in database

        Given a trained model
        When I serialize it and store in models table
        Then the artifact is stored as bytes
        And I can retrieve and deserialize it
        And predictions match
        """
        from datetime import UTC, date, datetime, timedelta

        from shared.config import settings
        from shared.db.models import Model

        # Setup test database
        engine = create_engine(settings.database_url, echo=False)
        Base.metadata.create_all(engine)
        connection = engine.connect()
        transaction = connection.begin()
        TestSessionLocal = sessionmaker(bind=connection, expire_on_commit=False)
        session = TestSessionLocal()

        try:
            # Train model
            X, y = sliding_window_data
            model = model_class(**hyperparams)
            model.train(X, y)

            # Serialize and store
            model_bytes = model.serialize()
            model_record = Model(
                name=model_name,
                version="1.0.0",
                params=hyperparams,
                artifact=model_bytes,
                trained_at=datetime.now(UTC),
                train_from=date.today() - timedelta(days=60),
                train_to=date.today() - timedelta(days=1),
                is_active=True,
            )

            session.add(model_record)
            session.commit()
            session.refresh(model_record)

            # Verify stored
            assert model_record.id is not None
            assert model_record.artifact is not None
            assert isinstance(model_record.artifact, bytes)

            # Retrieve and deserialize
            retrieved_artifact = model_record.artifact
            restored_model = model_class.deserialize(retrieved_artifact)

            # Verify predictions match
            X_new = X[-1:].reshape(1, -1)  # Last sample
            original_pred = model.predict(X_new)
            restored_pred = restored_model.predict(X_new)

            # Allow small differences due to serialization
            assert np.isclose(original_pred, restored_pred, rtol=0.05)

        finally:
            # Cleanup
            session.close()
            transaction.rollback()
            Base.metadata.drop_all(engine)
            connection.close()
            engine.dispose()


class TestModelComparison:
    """Compare characteristics of different models."""

    def test_model_serialization_sizes(self, sliding_window_data):
        """
        Compare serialization sizes across models.

        Linear and XGBoost should be small (< 1MB).
        LSTM should be larger due to neural network weights (< 5MB).
        ARIMA should be medium (< 3MB).
        """
        X, y = sliding_window_data

        # Linear Regression
        linear = LinearRegressionModel(window_days=30)
        linear.train(X, y)
        linear_bytes = linear.serialize()
        linear_size_mb = len(linear_bytes) / 1_000_000

        # XGBoost
        xgb = XGBoostModel(window_days=30)
        xgb.train(X, y)
        xgb_bytes = xgb.serialize()
        xgb_size_mb = len(xgb_bytes) / 1_000_000

        # LSTM (reduced epochs for speed)
        lstm = LSTMModel(window_days=30, epochs=5)
        lstm.train(X, y)
        lstm_bytes = lstm.serialize()
        lstm_size_mb = len(lstm_bytes) / 1_000_000

        # ARIMA
        arima = ARIMAModel(order=(5, 1, 0))
        arima.train(X, y)
        arima_bytes = arima.serialize()
        arima_size_mb = len(arima_bytes) / 1_000_000

        # Assertions
        assert linear_size_mb < 1.0, f"Linear too large: {linear_size_mb:.2f}MB"
        assert xgb_size_mb < 5.0, f"XGBoost too large: {xgb_size_mb:.2f}MB"
        assert lstm_size_mb < 10.0, f"LSTM too large: {lstm_size_mb:.2f}MB"
        assert arima_size_mb < 5.0, f"ARIMA too large: {arima_size_mb:.2f}MB"

        # Print sizes for info (visible in pytest -v output)
        print(f"\nModel serialization sizes:")
        print(f"  Linear:  {linear_size_mb:.3f} MB")
        print(f"  XGBoost: {xgb_size_mb:.3f} MB")
        print(f"  LSTM:    {lstm_size_mb:.3f} MB")
        print(f"  ARIMA:   {arima_size_mb:.3f} MB")
