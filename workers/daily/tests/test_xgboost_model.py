"""
Tests for XGBoostModel implementation.

This test suite validates all Gherkin acceptance criteria from US-023 for XGBoost:
1. XGBoostModel implements BaseModel interface
2. Train with default hyperparameters
3. Serialize and deserialize correctly
4. Training time < 30s for 365 days
5. Valid predictions (> 0, within sanity bounds)
"""

import pickle
import time

import numpy as np
import pytest

from workers.daily.models import BaseModel, XGBoostModel


class TestXGBoostModel:
    """Tests for XGBoostModel implementation."""

    def test_xgboost_implements_basemodel_interface(self):
        """
        Gherkin Scenario: XGBoostModel implements BaseModel interface

        When I create an XGBoostModel instance
        Then it inherits from BaseModel
        And it has methods: train(), predict(), serialize(), deserialize()
        """
        model = XGBoostModel()

        # Check inheritance
        assert isinstance(model, BaseModel)

        # Check required methods exist
        assert hasattr(model, "train")
        assert hasattr(model, "predict")
        assert hasattr(model, "serialize")
        assert hasattr(model, "deserialize")
        assert hasattr(model, "is_trained")

        assert callable(model.train)
        assert callable(model.predict)
        assert callable(model.serialize)
        assert callable(XGBoostModel.deserialize)

    def test_train_with_default_hyperparameters(self, sliding_window_data):
        """
        Gherkin Scenario: Train XGBoost model with default hyperparameters

        Given historical BTC prices for 60 days (30 samples with window_days=30)
        And XGBoost hyperparameters:
          | window_days   | 30  |
          | n_estimators  | 100 |
          | max_depth     | 5   |
          | learning_rate | 0.1 |
        When I train the XGBoost model
        Then training completes without errors
        And the model is fitted (has trained state)
        And model.is_trained is True
        """
        # Given: 60 days of data -> 30 samples with window_days=30
        X, y = sliding_window_data
        assert X.shape == (30, 30)
        assert y.shape == (30,)

        # When: Create model with default hyperparameters and train
        model = XGBoostModel(
            window_days=30, n_estimators=100, max_depth=5, learning_rate=0.1
        )
        assert not model.is_trained  # Not trained yet

        model.train(X, y)

        # Then: Model is trained successfully
        assert model.is_trained

    def test_xgboost_predict_returns_valid_float(
        self, sliding_window_data, last_30_days
    ):
        """
        Gherkin Scenario: XGBoost produces valid predictions

        Given a trained XGBoost model
        When I call model.predict(X) with shape (1, 30)
        Then it returns a float price prediction
        And prediction is > 0 (price cannot be negative)
        And prediction is within 50% of last known price (sanity check)
        """
        # Given: Trained model
        X, y = sliding_window_data
        model = XGBoostModel(window_days=30)
        model.train(X, y)
        assert model.is_trained

        # When: Predict with new data
        X_new = last_30_days
        assert X_new.shape == (1, 30)

        predicted_price = model.predict(X_new)

        # Then: Returns valid float
        assert isinstance(predicted_price, float)
        assert predicted_price > 0  # Price must be positive

        # Sanity check: prediction within 50% of last price
        last_price = X_new[0, -1]
        assert 0.5 * last_price <= predicted_price <= 1.5 * last_price

    def test_xgboost_serialize_deserialize(self, sliding_window_data, last_30_days):
        """
        Gherkin Scenario: XGBoost model serializes and deserializes correctly

        Given a trained XGBoost model
        When I call serialize()
        Then it returns a bytes artifact (pickled model)
        When I call XGBoostModel.deserialize(artifact)
        Then it returns a new XGBoostModel instance
        And predictions from the deserialized model match the original
        """
        # Given: Trained model
        X, y = sliding_window_data
        original_model = XGBoostModel(window_days=30)
        original_model.train(X, y)

        # When: Serialize
        model_bytes = original_model.serialize()

        # Then: Returns bytes
        assert isinstance(model_bytes, bytes)
        assert len(model_bytes) > 0
        assert len(model_bytes) < 5_000_000  # < 5MB

        # When: Deserialize
        restored_model = XGBoostModel.deserialize(model_bytes)

        # Then: Returns trained model instance
        assert isinstance(restored_model, XGBoostModel)
        assert restored_model.is_trained
        assert restored_model.window_days == 30
        assert restored_model.n_estimators == 100
        assert restored_model.max_depth == 5
        assert restored_model.learning_rate == 0.1

        # Verify predictions match
        X_new = last_30_days
        original_prediction = original_model.predict(X_new)
        restored_prediction = restored_model.predict(X_new)
        assert np.isclose(original_prediction, restored_prediction, rtol=1e-5)

    def test_xgboost_training_time_365_days(self):
        """
        Gherkin Scenario: XGBoost training completes in < 30 seconds

        Given 365 days of training data
        When I train XGBoost with n_estimators=100
        Then training completes in < 30 seconds
        And memory usage is reasonable
        """
        # Given: 365 days of data
        window_days = 30
        n_samples = 365 - window_days
        X = np.random.rand(n_samples, window_days) * 50000 + 45000
        y = np.random.rand(n_samples) * 50000 + 45000

        # When: Train with default hyperparameters
        model = XGBoostModel(window_days=window_days, n_estimators=100)

        start_time = time.time()
        model.train(X, y)
        end_time = time.time()

        training_time = end_time - start_time

        # Then: Training time < 30 seconds
        assert training_time < 30.0, f"Training took {training_time:.2f}s, expected < 30s"
        assert model.is_trained


class TestXGBoostModelEdgeCases:
    """ZOMBIES edge case tests for XGBoostModel."""

    # Z - Zero
    def test_train_with_zero_samples(self):
        """Train with 0 samples should raise error."""
        model = XGBoostModel(window_days=30)
        X = np.array([]).reshape(0, 30)
        y = np.array([])

        with pytest.raises(ValueError, match="Insufficient data"):
            model.train(X, y)

    # O - One
    def test_train_with_one_sample(self):
        """Train with 1 sample should raise error (insufficient for XGBoost)."""
        model = XGBoostModel(window_days=30)
        X = np.random.rand(1, 30) * 50000
        y = np.random.rand(1) * 50000

        # XGBoost needs at least window_days samples
        with pytest.raises(ValueError, match="Insufficient data"):
            model.train(X, y)

    # M - Many
    def test_train_with_many_samples(self):
        """Train with 365 days of data (335 samples)."""
        model = XGBoostModel(window_days=30)
        prices = np.linspace(50000, 55000, 365)

        # Create sliding window
        n_samples = 365 - 30
        X = np.array([prices[i : i + 30] for i in range(n_samples)])
        y = np.array([prices[i + 30] for i in range(n_samples)])

        model.train(X, y)
        assert model.is_trained

    # B - Boundaries
    def test_window_days_boundary_minimum(self):
        """Window size of 1 day (minimum)."""
        model = XGBoostModel(window_days=1)
        X = np.random.rand(10, 1) * 50000
        y = np.random.rand(10) * 50000

        model.train(X, y)
        assert model.is_trained

    def test_window_days_boundary_zero(self):
        """Window size of 0 should raise error."""
        with pytest.raises(ValueError, match="window_days must be >= 1"):
            XGBoostModel(window_days=0)

    def test_n_estimators_boundary_zero(self):
        """n_estimators of 0 should raise error."""
        with pytest.raises(ValueError, match="n_estimators must be >= 1"):
            XGBoostModel(n_estimators=0)

    def test_max_depth_boundary_zero(self):
        """max_depth of 0 should raise error."""
        with pytest.raises(ValueError, match="max_depth must be >= 1"):
            XGBoostModel(max_depth=0)

    def test_learning_rate_boundary_zero(self):
        """learning_rate of 0 should raise error."""
        with pytest.raises(ValueError, match="learning_rate must be > 0"):
            XGBoostModel(learning_rate=0.0)

    def test_learning_rate_boundary_negative(self):
        """Negative learning_rate should raise error."""
        with pytest.raises(ValueError, match="learning_rate must be > 0"):
            XGBoostModel(learning_rate=-0.1)

    # I - Interfaces
    def test_predict_accepts_1d_array(self, sliding_window_data):
        """Predict should accept 1D array (window_days,)."""
        X, y = sliding_window_data
        model = XGBoostModel(window_days=30)
        model.train(X, y)

        # 1D array
        X_new_1d = np.random.rand(30) * 50000
        prediction = model.predict(X_new_1d)
        assert isinstance(prediction, float)

    def test_predict_accepts_2d_array(self, sliding_window_data):
        """Predict should accept 2D array (1, window_days)."""
        X, y = sliding_window_data
        model = XGBoostModel(window_days=30)
        model.train(X, y)

        # 2D array
        X_new_2d = np.random.rand(1, 30) * 50000
        prediction = model.predict(X_new_2d)
        assert isinstance(prediction, float)

    # E - Exceptions
    def test_predict_before_training_raises_error(self):
        """Predict on untrained model should raise error."""
        model = XGBoostModel(window_days=30)
        X = np.random.rand(1, 30) * 50000

        with pytest.raises(ValueError, match="Model must be trained"):
            model.predict(X)

    def test_train_with_mismatched_shapes_raises_error(self):
        """Train with mismatched X and y shapes should raise error."""
        model = XGBoostModel(window_days=30)
        X = np.random.rand(50, 30) * 50000
        y = np.random.rand(25) * 50000  # Different number of samples

        with pytest.raises(ValueError, match="same number of samples"):
            model.train(X, y)

    def test_train_with_wrong_feature_count_raises_error(self):
        """Train with wrong number of features should raise error."""
        model = XGBoostModel(window_days=30)
        X = np.random.rand(50, 20) * 50000  # 20 features instead of 30
        y = np.random.rand(50) * 50000

        with pytest.raises(ValueError, match="must have 30 features"):
            model.train(X, y)

    def test_train_with_nan_values_raises_error(self):
        """Train with NaN values should raise error."""
        model = XGBoostModel(window_days=30)
        X = np.random.rand(50, 30) * 50000
        X[0, 0] = np.nan
        y = np.random.rand(50) * 50000

        with pytest.raises(ValueError, match="contains NaN"):
            model.train(X, y)

    def test_train_with_inf_values_raises_error(self):
        """Train with infinite values should raise error."""
        model = XGBoostModel(window_days=30)
        X = np.random.rand(50, 30) * 50000
        X[0, 0] = np.inf
        y = np.random.rand(50) * 50000

        with pytest.raises(ValueError, match="contains infinite"):
            model.train(X, y)

    def test_deserialize_corrupted_bytes_raises_error(self):
        """Deserialize corrupted bytes should raise error."""
        corrupted_bytes = b"not a valid pickle"

        with pytest.raises((pickle.UnpicklingError, ValueError)):
            XGBoostModel.deserialize(corrupted_bytes)

    def test_deserialize_invalid_structure_raises_error(self):
        """Deserialize bytes with invalid structure should raise error."""
        # Pickle a simple dict instead of model state
        invalid_data = pickle.dumps({"wrong": "structure"})

        with pytest.raises(ValueError, match="Missing required keys"):
            XGBoostModel.deserialize(invalid_data)

    # S - Serialization
    def test_serialize_untrained_model_works(self):
        """Serialize untrained model should work."""
        model = XGBoostModel(window_days=30)
        model_bytes = model.serialize()

        assert isinstance(model_bytes, bytes)
        assert len(model_bytes) > 0

        # Should be able to restore
        restored = XGBoostModel.deserialize(model_bytes)
        assert not restored.is_trained
        assert restored.window_days == 30
