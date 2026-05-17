"""
Tests for ML models (BaseModel and concrete implementations).

This test suite validates all Gherkin acceptance criteria from US-006:
1. BaseModel cannot be instantiated
2. Train LinearRegressionModel with valid data
3. Predict next price
4. Serialize model to bytes
5. Deserialize model from bytes
"""

import pickle

import numpy as np
import pytest

from workers.daily.models import BaseModel, LinearRegressionModel


class TestBaseModel:
    """Tests for BaseModel abstract class."""

    def test_cannot_instantiate_abstract_base_model(self):
        """
        Gherkin Scenario: BaseModel cannot be instantiated

        When I attempt to instantiate BaseModel()
        Then a TypeError is raised with message "Cannot instantiate abstract class"
        """
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseModel()


class TestLinearRegressionModel:
    """Tests for LinearRegressionModel implementation."""

    def test_train_with_valid_data(self, sliding_window_data):
        """
        Gherkin Scenario: Train LinearRegressionModel with valid data

        Given I have 60 days of BTC close prices
        When I create features with window_days=30
        And I call model.train(X, y) with 30 samples
        Then the model trains successfully
        And model.is_trained is True
        """
        # Given: 60 days of data -> 30 samples with window_days=30
        X, y = sliding_window_data
        assert X.shape == (30, 30)
        assert y.shape == (30,)

        # When: Create model and train
        model = LinearRegressionModel(window_days=30)
        assert not model.is_trained  # Not trained yet

        model.train(X, y)

        # Then: Model is trained successfully
        assert model.is_trained

    def test_predict_next_price(self, sliding_window_data, last_30_days):
        """
        Gherkin Scenario: Predict next price

        Given a trained LinearRegressionModel
        When I call model.predict(X_new) with the last 30 close prices
        Then the model returns a float predicted_price
        And predicted_price is > 0
        """
        # Given: Trained model
        X, y = sliding_window_data
        model = LinearRegressionModel(window_days=30)
        model.train(X, y)
        assert model.is_trained

        # When: Predict with new data
        X_new = last_30_days
        assert X_new.shape == (1, 30)

        predicted_price = model.predict(X_new)

        # Then: Returns positive float
        assert isinstance(predicted_price, float)
        assert predicted_price > 0

    def test_serialize_model_to_bytes(self, sliding_window_data):
        """
        Gherkin Scenario: Serialize model to bytes

        Given a trained LinearRegressionModel
        When I call model.serialize()
        Then it returns a bytes object (pickled model)
        And the bytes size is < 1MB
        """
        # Given: Trained model
        X, y = sliding_window_data
        model = LinearRegressionModel(window_days=30)
        model.train(X, y)

        # When: Serialize
        model_bytes = model.serialize()

        # Then: Returns bytes < 1MB
        assert isinstance(model_bytes, bytes)
        assert len(model_bytes) > 0
        assert len(model_bytes) < 1_000_000  # < 1MB

    def test_deserialize_model_from_bytes(self, sliding_window_data, last_30_days):
        """
        Gherkin Scenario: Deserialize model from bytes

        Given a serialized model as bytes
        When I call LinearRegressionModel.deserialize(bytes)
        Then it returns a trained LinearRegressionModel instance
        And model.is_trained is True
        """
        # Given: Trained and serialized model
        X, y = sliding_window_data
        original_model = LinearRegressionModel(window_days=30)
        original_model.train(X, y)
        model_bytes = original_model.serialize()

        # When: Deserialize
        restored_model = LinearRegressionModel.deserialize(model_bytes)

        # Then: Returns trained model instance
        assert isinstance(restored_model, LinearRegressionModel)
        assert restored_model.is_trained
        assert restored_model.window_days == 30

        # Verify predictions match
        X_new = last_30_days
        original_prediction = original_model.predict(X_new)
        restored_prediction = restored_model.predict(X_new)
        assert np.isclose(original_prediction, restored_prediction)


class TestLinearRegressionModelEdgeCases:
    """ZOMBIES edge case tests for LinearRegressionModel."""

    # Z - Zero
    def test_train_with_zero_samples(self):
        """Train with 0 samples should raise error."""
        model = LinearRegressionModel(window_days=30)
        X = np.array([]).reshape(0, 30)
        y = np.array([])

        with pytest.raises(ValueError):
            model.train(X, y)

    # O - One
    def test_train_with_one_sample(self):
        """Train with 1 sample should work (minimum valid)."""
        model = LinearRegressionModel(window_days=30)
        X = np.random.rand(1, 30)
        y = np.random.rand(1)

        model.train(X, y)
        assert model.is_trained

    # M - Many
    def test_train_with_many_samples(self):
        """Train with 365 days of data (335 samples)."""
        model = LinearRegressionModel(window_days=30)
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
        model = LinearRegressionModel(window_days=1)
        X = np.random.rand(10, 1)
        y = np.random.rand(10)

        model.train(X, y)
        assert model.is_trained

    def test_window_days_boundary_zero(self):
        """Window size of 0 should raise error."""
        with pytest.raises(ValueError, match="window_days must be >= 1"):
            LinearRegressionModel(window_days=0)

    def test_window_days_boundary_negative(self):
        """Negative window size should raise error."""
        with pytest.raises(ValueError, match="window_days must be >= 1"):
            LinearRegressionModel(window_days=-1)

    # I - Interfaces
    def test_predict_accepts_1d_array(self, sliding_window_data):
        """Predict should accept 1D array (window_days,)."""
        X, y = sliding_window_data
        model = LinearRegressionModel(window_days=30)
        model.train(X, y)

        # 1D array
        X_new_1d = np.random.rand(30)
        prediction = model.predict(X_new_1d)
        assert isinstance(prediction, float)

    def test_predict_accepts_2d_array(self, sliding_window_data):
        """Predict should accept 2D array (1, window_days)."""
        X, y = sliding_window_data
        model = LinearRegressionModel(window_days=30)
        model.train(X, y)

        # 2D array
        X_new_2d = np.random.rand(1, 30)
        prediction = model.predict(X_new_2d)
        assert isinstance(prediction, float)

    # E - Exceptions
    def test_predict_before_training_raises_error(self):
        """Predict on untrained model should raise error."""
        model = LinearRegressionModel(window_days=30)
        X = np.random.rand(1, 30)

        with pytest.raises(ValueError, match="Model must be trained"):
            model.predict(X)

    def test_train_with_mismatched_shapes_raises_error(self):
        """Train with mismatched X and y shapes should raise error."""
        model = LinearRegressionModel(window_days=30)
        X = np.random.rand(10, 30)
        y = np.random.rand(5)  # Different number of samples

        with pytest.raises(ValueError, match="same number of samples"):
            model.train(X, y)

    def test_train_with_wrong_feature_count_raises_error(self):
        """Train with wrong number of features should raise error."""
        model = LinearRegressionModel(window_days=30)
        X = np.random.rand(10, 20)  # 20 features instead of 30
        y = np.random.rand(10)

        with pytest.raises(ValueError, match="must have 30 features"):
            model.train(X, y)

    def test_train_with_nan_values_raises_error(self):
        """Train with NaN values should raise error."""
        model = LinearRegressionModel(window_days=30)
        X = np.random.rand(10, 30)
        X[0, 0] = np.nan
        y = np.random.rand(10)

        with pytest.raises(ValueError, match="contains NaN"):
            model.train(X, y)

    def test_train_with_inf_values_raises_error(self):
        """Train with infinite values should raise error."""
        model = LinearRegressionModel(window_days=30)
        X = np.random.rand(10, 30)
        X[0, 0] = np.inf
        y = np.random.rand(10)

        with pytest.raises(ValueError, match="contains infinite"):
            model.train(X, y)

    def test_predict_with_wrong_shape_raises_error(self, sliding_window_data):
        """Predict with wrong shape should raise error."""
        X, y = sliding_window_data
        model = LinearRegressionModel(window_days=30)
        model.train(X, y)

        # Wrong number of features
        X_wrong = np.random.rand(1, 20)
        with pytest.raises(ValueError, match="must have 30 features"):
            model.predict(X_wrong)

    def test_predict_with_multiple_samples_raises_error(self, sliding_window_data):
        """Predict with multiple samples should raise error."""
        X, y = sliding_window_data
        model = LinearRegressionModel(window_days=30)
        model.train(X, y)

        # Multiple samples (should be 1)
        X_multiple = np.random.rand(5, 30)
        with pytest.raises(ValueError, match="must have shape"):
            model.predict(X_multiple)

    def test_deserialize_corrupted_bytes_raises_error(self):
        """Deserialize corrupted bytes should raise error."""
        corrupted_bytes = b"not a valid pickle"

        with pytest.raises((pickle.UnpicklingError, ValueError)):
            LinearRegressionModel.deserialize(corrupted_bytes)

    def test_deserialize_invalid_structure_raises_error(self):
        """Deserialize bytes with invalid structure should raise error."""
        # Pickle a simple dict instead of model state
        invalid_data = pickle.dumps({"wrong": "structure"})

        with pytest.raises(ValueError, match="Missing required keys"):
            LinearRegressionModel.deserialize(invalid_data)

    def test_serialize_untrained_model_works(self):
        """Serialize untrained model should work."""
        model = LinearRegressionModel(window_days=30)
        model_bytes = model.serialize()

        assert isinstance(model_bytes, bytes)
        assert len(model_bytes) > 0

        # Should be able to restore
        restored = LinearRegressionModel.deserialize(model_bytes)
        assert not restored.is_trained
        assert restored.window_days == 30
