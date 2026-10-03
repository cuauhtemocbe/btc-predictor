"""
Tests for ARIMAModel implementation.

This test suite validates all Gherkin acceptance criteria from US-023 for ARIMA:
1. ARIMAModel implements BaseModel interface
2. Train with default order
3. Fit the daily log return series, not price levels
4. Serialize and deserialize correctly
5. Valid predictions (a finite log return)
"""

import pickle
from typing import cast

import numpy as np
import pytest

from shared.features import FeatureSet
from workers.daily.models import ARIMAModel, BaseModel


class TestARIMAModel:
    """Tests for ARIMAModel implementation."""

    def test_arima_implements_basemodel_interface(self) -> None:
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

    def test_train_with_default_order(self, return_training_set: FeatureSet) -> None:
        """
        Gherkin Scenario: Train ARIMA model with default order

        Given the daily log return series of 120 days
        And ARIMA order = (5, 0, 0) (returns are already differenced)
        When I train the ARIMA model
        Then it fits an ARIMA(5,0,0) model
        And I can predict 1 step ahead
        """
        # Given: return features and next-day log return targets
        X, y = return_training_set.X, return_training_set.y

        # When: Create ARIMA model with default order and train
        model = ARIMAModel(window_days=10, n_features=X.shape[1])
        assert not model.is_trained  # Not trained yet

        model.train(X, y)

        # Then: Model is trained successfully
        assert model.is_trained
        assert model.order == (5, 0, 0)

    def test_arima_is_fitted_on_the_return_series(
        self, return_training_set: FeatureSet
    ) -> None:
        """
        Gherkin Scenario: ARIMA is fitted on log returns, not on price levels

        Given return features and next-day log return targets of consecutive days
        When I train the model
        Then it fits the series: lagged returns of the first sample, then the targets
        And the other feature columns (volatility, volume changes) are not used
        """
        X, y = return_training_set.X, return_training_set.y
        model = ARIMAModel(window_days=10, n_features=X.shape[1])

        model.train(X, y)

        training_data = model._training_data
        assert training_data is not None
        assert np.allclose(training_data[:10], X[0, :10])
        assert np.allclose(training_data[10:], y)
        assert len(training_data) == 10 + len(y)

    def test_arima_predict_returns_valid_float(
        self, return_training_set: FeatureSet, latest_return_features: np.ndarray
    ) -> None:
        """
        Gherkin Scenario: ARIMA predicts the next-day log return

        Given a trained ARIMA model
        When I call model.predict(X) with the features of the latest day
        Then it returns a finite float log return
        And the return is small (a day moves a few percent, not a price)
        """
        # Given: Trained model
        X, y = return_training_set.X, return_training_set.y
        model = ARIMAModel(window_days=10, n_features=X.shape[1])
        model.train(X, y)
        assert model.is_trained

        # When: Predict with the features of the latest day
        predicted_return = model.predict(latest_return_features)

        # Then: Returns a valid log return, not a price level
        assert isinstance(predicted_return, float)
        assert np.isfinite(predicted_return)
        assert abs(predicted_return) < 1.0

    def test_arima_predict_uses_the_latest_returns_without_refitting(
        self, return_training_set: FeatureSet, latest_return_features: np.ndarray
    ) -> None:
        """
        Gherkin Scenario: ARIMA forecasts from the latest returns

        Given a trained ARIMA model
        When I predict from two different windows of latest returns
        Then the forecasts differ (the input matters)
        And the fitted parameters do not change (no refit per prediction)
        """
        X, y = return_training_set.X, return_training_set.y
        model = ARIMAModel(window_days=10, n_features=X.shape[1])
        model.train(X, y)
        params_before = np.array(model.fitted_model.params)

        first = model.predict(latest_return_features)
        second = model.predict(X[0:1])

        assert first != second
        assert np.array_equal(params_before, model.fitted_model.params)

    def test_arima_serialize_deserialize(
        self, return_training_set: FeatureSet, latest_return_features: np.ndarray
    ) -> None:
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
        X, y = return_training_set.X, return_training_set.y
        original_model = ARIMAModel(window_days=10, n_features=X.shape[1])
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
        assert restored_model.order == (5, 0, 0)
        assert restored_model.seasonal_order == (0, 0, 0, 0)
        assert restored_model.window_days == 10
        assert restored_model.n_features == X.shape[1]

        # The forecast does not refit, so both models agree exactly
        original_prediction = original_model.predict(latest_return_features)
        restored_prediction = restored_model.predict(latest_return_features)
        assert np.isclose(original_prediction, restored_prediction)

    def test_train_rejects_a_feature_width_other_than_n_features(
        self, return_training_set: FeatureSet
    ) -> None:
        """
        Gherkin Scenario: ARIMA rejects features of another width

        Given an ARIMAModel built for the return features (21 columns)
        When I train it with a matrix of another width
        Then it raises a ValueError naming the expected feature count
        """
        X, y = return_training_set.X, return_training_set.y
        model = ARIMAModel(window_days=10, n_features=X.shape[1])

        with pytest.raises(ValueError, match="must have 21 features"):
            model.train(X[:, :20], y)

    def test_n_features_must_cover_the_window(self) -> None:
        """The returns ARIMA reads are columns of X, so X cannot be narrower."""
        with pytest.raises(ValueError, match="n_features .* must be >= window_days"):
            ARIMAModel(window_days=10, n_features=5)

    def test_window_days_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="window_days must be >= 1"):
            ARIMAModel(window_days=0)

    def test_artifact_without_n_features_still_loads(
        self, sliding_window_data: tuple[np.ndarray, np.ndarray]
    ) -> None:
        """An artifact saved before n_features existed loads with n_features=window."""
        X, y = sliding_window_data
        model = ARIMAModel(window_days=30)
        model.train(X, y)
        state = pickle.loads(model.serialize())
        del state["n_features"]

        restored = ARIMAModel.deserialize(pickle.dumps(state))

        assert restored.n_features == 30
        assert restored.is_trained


class TestARIMAModelEdgeCases:
    """ZOMBIES edge case tests for ARIMAModel."""

    # Z - Zero
    def test_train_with_zero_samples(self) -> None:
        """Train with 0 samples should raise error."""
        model = ARIMAModel(order=(5, 1, 0))
        X = np.array([]).reshape(0, 30)
        y = np.array([])

        with pytest.raises(ValueError, match="Insufficient data"):
            model.train(X, y)

    # O - One
    def test_train_with_one_sample(self) -> None:
        """Train with 1 sample should raise error (insufficient for ARIMA)."""
        model = ARIMAModel(order=(5, 1, 0))
        X = np.random.rand(1, 30) * 50000
        y = np.random.rand(1) * 50000

        # ARIMA needs at least max(p+q, 10) samples
        with pytest.raises(ValueError, match="Insufficient data"):
            model.train(X, y)

    # M - Many
    def test_train_with_many_samples(self) -> None:
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
    def test_order_p_zero_is_valid(self) -> None:
        """ARIMA order with p=0 is valid (pure MA model)."""
        model = ARIMAModel(order=(0, 1, 5))
        assert model.order == (0, 1, 5)

    def test_order_d_zero_is_valid(self) -> None:
        """ARIMA order with d=0 is valid (no differencing)."""
        model = ARIMAModel(order=(5, 0, 0))
        assert model.order == (5, 0, 0)

    def test_order_q_zero_is_valid(self) -> None:
        """ARIMA order with q=0 is valid (pure AR model)."""
        model = ARIMAModel(order=(5, 1, 0))
        assert model.order == (5, 1, 0)

    def test_order_negative_p_raises_error(self) -> None:
        """Negative p value should raise error."""
        with pytest.raises(ValueError, match="order values.*must be >= 0"):
            ARIMAModel(order=(-1, 1, 0))

    def test_order_negative_d_raises_error(self) -> None:
        """Negative d value should raise error."""
        with pytest.raises(ValueError, match="order values.*must be >= 0"):
            ARIMAModel(order=(5, -1, 0))

    def test_order_wrong_length_raises_error(self) -> None:
        """Order with wrong number of elements should raise error."""
        with pytest.raises(ValueError, match="order must be a 3-tuple"):
            ARIMAModel(order=cast("tuple[int, int, int]", (5, 1)))

    def test_seasonal_order_all_zeros_is_valid(self) -> None:
        """Seasonal order with all zeros (no seasonality) is valid."""
        model = ARIMAModel(order=(5, 1, 0), seasonal_order=(0, 0, 0, 0))
        assert model.seasonal_order == (0, 0, 0, 0)

    def test_seasonal_order_wrong_length_raises_error(self) -> None:
        """Seasonal order with wrong number of elements should raise error."""
        with pytest.raises(ValueError, match="seasonal_order must be a 4-tuple"):
            ARIMAModel(seasonal_order=cast("tuple[int, int, int, int]", (0, 0, 0)))

    # I - Interfaces
    def test_predict_accepts_1d_array(
        self, sliding_window_data: tuple[np.ndarray, np.ndarray]
    ) -> None:
        """Predict should accept 1D array (window_days,)."""
        X, y = sliding_window_data
        model = ARIMAModel(order=(5, 1, 0))
        model.train(X, y)

        # 1D array
        X_new_1d = np.random.rand(30) * 50000
        prediction = model.predict(X_new_1d)
        assert isinstance(prediction, float)

    def test_predict_accepts_2d_array(
        self, sliding_window_data: tuple[np.ndarray, np.ndarray]
    ) -> None:
        """Predict should accept 2D array (1, window_days)."""
        X, y = sliding_window_data
        model = ARIMAModel(order=(5, 1, 0))
        model.train(X, y)

        # 2D array
        X_new_2d = np.random.rand(1, 30) * 50000
        prediction = model.predict(X_new_2d)
        assert isinstance(prediction, float)

    # E - Exceptions
    def test_predict_before_training_raises_error(self) -> None:
        """Predict on untrained model should raise error."""
        model = ARIMAModel(order=(5, 1, 0))
        X = np.random.rand(1, 30) * 50000

        with pytest.raises(ValueError, match="Model must be trained"):
            model.predict(X)

    def test_train_with_mismatched_shapes_raises_error(self) -> None:
        """Train with mismatched X and y shapes should raise error."""
        model = ARIMAModel(order=(5, 1, 0))
        X = np.random.rand(50, 30) * 50000
        y = np.random.rand(25) * 50000  # Different number of samples

        with pytest.raises(ValueError, match="same number of samples"):
            model.train(X, y)

    def test_train_with_nan_values_raises_error(self) -> None:
        """Train with NaN values should raise error."""
        model = ARIMAModel(order=(5, 1, 0))
        X = np.random.rand(50, 30) * 50000
        X[0, 0] = np.nan
        y = np.random.rand(50) * 50000

        with pytest.raises(ValueError, match="contains NaN"):
            model.train(X, y)

    def test_train_with_inf_values_raises_error(self) -> None:
        """Train with infinite values should raise error."""
        model = ARIMAModel(order=(5, 1, 0))
        X = np.random.rand(50, 30) * 50000
        X[0, 0] = np.inf
        y = np.random.rand(50) * 50000

        with pytest.raises(ValueError, match="contains infinite"):
            model.train(X, y)

    def test_deserialize_corrupted_bytes_raises_error(self) -> None:
        """Deserialize corrupted bytes should raise error."""
        corrupted_bytes = b"not a valid pickle"

        with pytest.raises((pickle.UnpicklingError, ValueError)):
            ARIMAModel.deserialize(corrupted_bytes)

    def test_deserialize_invalid_structure_raises_error(self) -> None:
        """Deserialize bytes with invalid structure should raise error."""
        # Pickle a simple dict instead of model state
        invalid_data = pickle.dumps({"wrong": "structure"})

        with pytest.raises(ValueError, match="Missing required keys"):
            ARIMAModel.deserialize(invalid_data)

    # S - Serialization
    def test_serialize_untrained_model_works(self) -> None:
        """Serialize untrained model should work."""
        model = ARIMAModel(order=(5, 1, 0))
        model_bytes = model.serialize()

        assert isinstance(model_bytes, bytes)
        assert len(model_bytes) > 0

        # Should be able to restore
        restored = ARIMAModel.deserialize(model_bytes)
        assert not restored.is_trained
        assert restored.order == (5, 1, 0)
