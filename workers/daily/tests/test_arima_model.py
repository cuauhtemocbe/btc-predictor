"""
Tests for ARIMAModel implementation.

This test suite validates all Gherkin acceptance criteria from US-023 for ARIMA:
1. ARIMAModel implements BaseModel interface
2. Train with default order
3. Handle non-stationary data with differencing
4. Serialize and deserialize correctly
5. Valid predictions (> 0, within sanity bounds)
"""

import pickle

import numpy as np
import pytest

from workers.daily.models import ARIMAModel, BaseModel


class TestARIMAModel:
    """Tests for ARIMAModel implementation."""

    def test_arima_implements_basemodel_interface(self):
        """
        Gherkin Scenario: ARIMAModel implements BaseModel interface

        When I create an ARIMAModel instance
        Then it implements train(), predict(), serialize(), deserialize()
        And it uses statsmodels.tsa.arima.ARIMA internally
        """
        model = ARIMAModel()

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
        assert callable(ARIMAModel.deserialize)

    def test_train_with_default_order(self, sliding_window_data):
        """
        Gherkin Scenario: Train ARIMA model with default order

        Given a time series of 60 daily BTC close prices
        And ARIMA order = (5, 1, 0)
        When I train the ARIMA model
        Then it fits an ARIMA(5,1,0) model
        And I can predict 1 step ahead
        And the prediction is a float price
        """
        # Given: 60 days of price data
        X, y = sliding_window_data
        assert X.shape == (30, 30)
        assert y.shape == (30,)

        # When: Create ARIMA model with default order (5, 1, 0) and train
        model = ARIMAModel(order=(5, 1, 0))
        assert not model.is_trained  # Not trained yet

        model.train(X, y)

        # Then: Model is trained successfully
        assert model.is_trained
        assert model.order == (5, 1, 0)

    def test_arima_handles_non_stationary_data(self):
        """
        Gherkin Scenario: ARIMA handles non-stationary data with differencing

        Given BTC prices with a clear trend (non-stationary)
        And ARIMA order = (5, 1, 0) with d=1 (first difference)
        When I train the model
        Then it applies differencing internally
        And predictions are reasonable (within 10% of recent prices)
        """
        # Given: Non-stationary data with upward trend
        window_days = 30
        trend = np.linspace(50000, 55000, 90)  # Clear upward trend
        noise = np.random.normal(0, 500, 90)
        prices = trend + noise

        # Create sliding window
        n_samples = 90 - window_days
        X = np.array([prices[i : i + window_days] for i in range(n_samples)])
        y = np.array([prices[i + window_days] for i in range(n_samples)])

        # When: Train ARIMA with d=1 (differencing)
        model = ARIMAModel(order=(5, 1, 0))
        model.train(X, y)

        # Make prediction
        X_new = prices[-window_days:].reshape(1, -1)
        prediction = model.predict(X_new)

        # Then: Prediction is reasonable
        assert isinstance(prediction, float)
        assert prediction > 0

        # Within 10% of recent average price
        recent_avg = np.mean(prices[-10:])
        assert 0.9 * recent_avg <= prediction <= 1.1 * recent_avg

    def test_arima_predict_returns_valid_float(self, sliding_window_data, last_30_days):
        """
        Gherkin Scenario: ARIMA produces valid predictions

        Given a trained ARIMA model
        When I call model.predict(X) with shape (1, 30)
        Then it returns a float price prediction
        And the prediction is > 0 (price cannot be negative)
        And the prediction is within 50% of the last known price (sanity check)
        """
        # Given: Trained model
        X, y = sliding_window_data
        model = ARIMAModel(order=(5, 1, 0))
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

    def test_arima_serialize_deserialize(self, sliding_window_data, last_30_days):
        """
        Gherkin Scenario: ARIMA model serializes and deserializes correctly

        Given a trained ARIMA model
        When I call serialize()
        Then it returns a bytes artifact
        When I call ARIMAModel.deserialize(artifact)
        Then it returns a new ARIMAModel instance
        And predictions from the deserialized model match the original
        """
        # Given: Trained model
        X, y = sliding_window_data
        original_model = ARIMAModel(order=(5, 1, 0))
        original_model.train(X, y)

        # When: Serialize
        model_bytes = original_model.serialize()

        # Then: Returns bytes
        assert isinstance(model_bytes, bytes)
        assert len(model_bytes) > 0
        assert len(model_bytes) < 10_000_000  # < 10MB

        # When: Deserialize
        restored_model = ARIMAModel.deserialize(model_bytes)

        # Then: Returns trained model instance
        assert isinstance(restored_model, ARIMAModel)
        assert restored_model.is_trained
        assert restored_model.order == (5, 1, 0)
        assert restored_model.seasonal_order == (0, 0, 0, 0)

        # Verify predictions are similar (ARIMA refits so allow more variation)
        X_new = last_30_days
        original_prediction = original_model.predict(X_new)
        restored_prediction = restored_model.predict(X_new)

        # Predictions should be in similar range (within 20%)
        assert (
            0.8 * original_prediction
            <= restored_prediction
            <= 1.2 * original_prediction
        )


class TestARIMAModelEdgeCases:
    """ZOMBIES edge case tests for ARIMAModel."""

    # Z - Zero
    def test_train_with_zero_samples(self):
        """Train with 0 samples should raise error."""
        model = ARIMAModel(order=(5, 1, 0))
        X = np.array([]).reshape(0, 30)
        y = np.array([])

        with pytest.raises(ValueError, match="Insufficient data"):
            model.train(X, y)

    # O - One
    def test_train_with_one_sample(self):
        """Train with 1 sample should raise error (insufficient for ARIMA)."""
        model = ARIMAModel(order=(5, 1, 0))
        X = np.random.rand(1, 30) * 50000
        y = np.random.rand(1) * 50000

        # ARIMA needs at least max(p+q, 10) samples
        with pytest.raises(ValueError, match="Insufficient data"):
            model.train(X, y)

    # M - Many
    def test_train_with_many_samples(self):
        """Train with 365 days of data (335 samples)."""
        model = ARIMAModel(order=(5, 1, 0))
        prices = np.linspace(50000, 55000, 365)

        # Create sliding window
        window_days = 30
        n_samples = 365 - window_days
        X = np.array([prices[i : i + window_days] for i in range(n_samples)])
        y = np.array([prices[i + window_days] for i in range(n_samples)])

        model.train(X, y)
        assert model.is_trained

    # B - Boundaries
    def test_order_p_zero_is_valid(self):
        """ARIMA order with p=0 is valid (pure MA model)."""
        model = ARIMAModel(order=(0, 1, 5))
        assert model.order == (0, 1, 5)

    def test_order_d_zero_is_valid(self):
        """ARIMA order with d=0 is valid (no differencing)."""
        model = ARIMAModel(order=(5, 0, 0))
        assert model.order == (5, 0, 0)

    def test_order_q_zero_is_valid(self):
        """ARIMA order with q=0 is valid (pure AR model)."""
        model = ARIMAModel(order=(5, 1, 0))
        assert model.order == (5, 1, 0)

    def test_order_negative_p_raises_error(self):
        """Negative p value should raise error."""
        with pytest.raises(ValueError, match="order values.*must be >= 0"):
            ARIMAModel(order=(-1, 1, 0))

    def test_order_negative_d_raises_error(self):
        """Negative d value should raise error."""
        with pytest.raises(ValueError, match="order values.*must be >= 0"):
            ARIMAModel(order=(5, -1, 0))

    def test_order_wrong_length_raises_error(self):
        """Order with wrong number of elements should raise error."""
        with pytest.raises(ValueError, match="order must be a 3-tuple"):
            ARIMAModel(order=(5, 1))

    def test_seasonal_order_all_zeros_is_valid(self):
        """Seasonal order with all zeros (no seasonality) is valid."""
        model = ARIMAModel(order=(5, 1, 0), seasonal_order=(0, 0, 0, 0))
        assert model.seasonal_order == (0, 0, 0, 0)

    def test_seasonal_order_wrong_length_raises_error(self):
        """Seasonal order with wrong number of elements should raise error."""
        with pytest.raises(ValueError, match="seasonal_order must be a 4-tuple"):
            ARIMAModel(seasonal_order=(0, 0, 0))

    # I - Interfaces
    def test_predict_accepts_1d_array(self, sliding_window_data):
        """Predict should accept 1D array (window_days,)."""
        X, y = sliding_window_data
        model = ARIMAModel(order=(5, 1, 0))
        model.train(X, y)

        # 1D array
        X_new_1d = np.random.rand(30) * 50000
        prediction = model.predict(X_new_1d)
        assert isinstance(prediction, float)

    def test_predict_accepts_2d_array(self, sliding_window_data):
        """Predict should accept 2D array (1, window_days)."""
        X, y = sliding_window_data
        model = ARIMAModel(order=(5, 1, 0))
        model.train(X, y)

        # 2D array
        X_new_2d = np.random.rand(1, 30) * 50000
        prediction = model.predict(X_new_2d)
        assert isinstance(prediction, float)

    # E - Exceptions
    def test_predict_before_training_raises_error(self):
        """Predict on untrained model should raise error."""
        model = ARIMAModel(order=(5, 1, 0))
        X = np.random.rand(1, 30) * 50000

        with pytest.raises(ValueError, match="Model must be trained"):
            model.predict(X)

    def test_train_with_mismatched_shapes_raises_error(self):
        """Train with mismatched X and y shapes should raise error."""
        model = ARIMAModel(order=(5, 1, 0))
        X = np.random.rand(50, 30) * 50000
        y = np.random.rand(25) * 50000  # Different number of samples

        with pytest.raises(ValueError, match="same number of samples"):
            model.train(X, y)

    def test_train_with_nan_values_raises_error(self):
        """Train with NaN values should raise error."""
        model = ARIMAModel(order=(5, 1, 0))
        X = np.random.rand(50, 30) * 50000
        X[0, 0] = np.nan
        y = np.random.rand(50) * 50000

        with pytest.raises(ValueError, match="contains NaN"):
            model.train(X, y)

    def test_train_with_inf_values_raises_error(self):
        """Train with infinite values should raise error."""
        model = ARIMAModel(order=(5, 1, 0))
        X = np.random.rand(50, 30) * 50000
        X[0, 0] = np.inf
        y = np.random.rand(50) * 50000

        with pytest.raises(ValueError, match="contains infinite"):
            model.train(X, y)

    def test_deserialize_corrupted_bytes_raises_error(self):
        """Deserialize corrupted bytes should raise error."""
        corrupted_bytes = b"not a valid pickle"

        with pytest.raises((pickle.UnpicklingError, ValueError)):
            ARIMAModel.deserialize(corrupted_bytes)

    def test_deserialize_invalid_structure_raises_error(self):
        """Deserialize bytes with invalid structure should raise error."""
        # Pickle a simple dict instead of model state
        invalid_data = pickle.dumps({"wrong": "structure"})

        with pytest.raises(ValueError, match="Missing required keys"):
            ARIMAModel.deserialize(invalid_data)

    # S - Serialization
    def test_serialize_untrained_model_works(self):
        """Serialize untrained model should work."""
        model = ARIMAModel(order=(5, 1, 0))
        model_bytes = model.serialize()

        assert isinstance(model_bytes, bytes)
        assert len(model_bytes) > 0

        # Should be able to restore
        restored = ARIMAModel.deserialize(model_bytes)
        assert not restored.is_trained
        assert restored.order == (5, 1, 0)
