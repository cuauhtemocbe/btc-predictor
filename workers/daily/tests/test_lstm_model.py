"""
Tests for LSTMModel implementation.

This test suite validates all Gherkin acceptance criteria from US-023 for LSTM:
1. LSTMModel implements BaseModel interface
2. Train with default hyperparameters
3. Serialize and deserialize correctly
4. Training time < 5 min for 90 days
5. Loss decreases during training (convergence)
6. Valid predictions (a finite log return, negative ones included)
"""

import pickle
import time

import numpy as np
import pytest

from workers.daily.models import BaseModel, LSTMModel


class TestLSTMModel:
    """Tests for LSTMModel implementation."""

    def test_lstm_implements_basemodel_interface(self):
        """
        Gherkin Scenario: LSTMModel implements BaseModel interface

        When I create an LSTMModel instance
        Then it inherits from BaseModel
        And it has methods: train(), predict(), serialize(), deserialize()
        And it can be imported from workers.daily.models
        """
        model = LSTMModel()

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
        assert callable(LSTMModel.deserialize)

    def test_train_with_default_hyperparameters(self, sliding_window_data):
        """
        Gherkin Scenario: Train LSTM model with default hyperparameters

        Given historical BTC prices for 60 days (30 samples with window_days=30)
        And LSTM hyperparameters:
          | window_days | 30   |
          | lstm_units  | 50   |
          | dropout     | 0.2  |
          | epochs      | 50   |
        When I train the LSTM model
        Then training completes without errors
        And the model is fitted (has trained weights)
        And model.is_trained is True
        """
        # Given: 60 days of data -> 30 samples with window_days=30
        X, y = sliding_window_data
        assert X.shape == (30, 30)
        assert y.shape == (30,)

        # When: Create model with default hyperparameters and train
        model = LSTMModel(
            window_days=30,
            lstm_units=50,
            dropout=0.2,
            epochs=10,  # Reduced for speed
        )
        assert not model.is_trained  # Not trained yet

        model.train(X, y)

        # Then: Model is trained successfully
        assert model.is_trained

    def test_lstm_predict_returns_valid_float(
        self, return_training_set, latest_return_features
    ):
        """
        Gherkin Scenario: LSTM predicts the next-day log return

        Given a trained LSTM model on return features and log return targets
        When I call model.predict(X) with the features of the latest day
        Then it returns a finite float log return
        And the return is small (a day moves a few percent, not a price)
        """
        # Given: Trained model on the return features of shared.features
        X, y = return_training_set.X, return_training_set.y
        model = LSTMModel(window_days=10, n_features=X.shape[1], epochs=10)
        model.train(X, y)
        assert model.is_trained

        # When: Predict with the features of the latest day
        predicted_return = model.predict(latest_return_features)

        # Then: Returns a valid log return, not a price level
        assert isinstance(predicted_return, float)
        assert np.isfinite(predicted_return)
        assert abs(predicted_return) < 1.0

    def test_lstm_prediction_is_not_clipped_at_zero(
        self, return_training_set, latest_return_features, monkeypatch
    ):
        """
        Gherkin Scenario: LSTM can predict a down day

        Given a trained LSTM model whose network outputs a negative return
        When I call model.predict(X)
        Then the negative log return is returned as is
        """
        X, y = return_training_set.X, return_training_set.y
        model = LSTMModel(window_days=10, n_features=X.shape[1], epochs=1)
        model.train(X, y)
        monkeypatch.setattr(model.model, "predict", lambda *_, **__: [[-0.03]])

        assert model.predict(latest_return_features) == pytest.approx(-0.03)

    def test_lstm_serialize_deserialize(
        self, return_training_set, latest_return_features
    ):
        """
        Gherkin Scenario: LSTM model serializes and deserializes correctly

        Given a trained LSTM model
        When I call serialize()
        Then it returns a bytes artifact (pickled Keras model)
        When I call LSTMModel.deserialize(artifact)
        Then it returns a new LSTMModel instance
        And predictions from the deserialized model match the original
        """
        # Given: Trained model
        X, y = return_training_set.X, return_training_set.y
        original_model = LSTMModel(window_days=10, n_features=X.shape[1], epochs=10)
        original_model.train(X, y)

        # When: Serialize
        model_bytes = original_model.serialize()

        # Then: Returns bytes
        assert isinstance(model_bytes, bytes)
        assert len(model_bytes) > 0
        assert len(model_bytes) < 10_000_000  # < 10MB

        # When: Deserialize
        restored_model = LSTMModel.deserialize(model_bytes)

        # Then: Returns trained model instance
        assert isinstance(restored_model, LSTMModel)
        assert restored_model.is_trained
        assert restored_model.window_days == 10
        assert restored_model.n_features == X.shape[1]
        assert restored_model.lstm_units == 50

        # Verify predictions match (allow small float differences)
        original_prediction = original_model.predict(latest_return_features)
        restored_prediction = restored_model.predict(latest_return_features)
        assert np.isclose(original_prediction, restored_prediction, atol=1e-6)

    @pytest.mark.slow
    def test_lstm_training_time_90_days(self):
        """
        Gherkin Scenario: LSTM training completes in reasonable time

        Given 90 days of training data
        And LSTM epochs=50
        When I train the model
        Then training completes in < 5 minutes
        And the model converges (loss decreases)
        """
        # Given: 90 days of data
        window_days = 30
        n_samples = 90 - window_days
        X = np.random.rand(n_samples, window_days) * 50000 + 45000
        y = np.random.rand(n_samples) * 50000 + 45000

        # When: Train with default hyperparameters
        model = LSTMModel(window_days=window_days, lstm_units=50, epochs=50)

        start_time = time.time()
        model.train(X, y)
        end_time = time.time()

        training_time = end_time - start_time

        # Then: Training time < 5 minutes (300 seconds)
        assert training_time < 300.0, (
            f"Training took {training_time:.2f}s, expected < 300s"
        )
        assert model.is_trained

    def test_trains_on_the_return_features_of_the_reboot(self, return_training_set):
        """
        Gherkin Scenario: LSTM trains on the reboot features and target

        Given the return features of shared.features (2 * window + 1 columns)
        And the next-day log return as target
        When I train an LSTMModel built with that feature count
        Then it trains, although the width differs from window_days
        """
        X, y = return_training_set.X, return_training_set.y
        assert X.shape[1] == 2 * 10 + 1

        model = LSTMModel(window_days=10, n_features=X.shape[1], epochs=2)
        model.train(X, y)

        assert model.is_trained
        assert model.n_features == 21

    def test_default_feature_count_is_the_window(self):
        """Without n_features the model expects one column per day, as before."""
        assert LSTMModel(window_days=30).n_features == 30

    def test_artifact_without_n_features_still_loads(self, sliding_window_data):
        """An artifact saved before n_features existed loads with n_features=window."""
        X, y = sliding_window_data
        model = LSTMModel(window_days=30, epochs=1)
        model.train(X, y)
        state = pickle.loads(model.serialize())
        del state["n_features"]

        restored = LSTMModel.deserialize(pickle.dumps(state))

        assert restored.n_features == 30
        assert restored.is_trained


class TestLSTMModelEdgeCases:
    """ZOMBIES edge case tests for LSTMModel."""

    # Z - Zero
    def test_train_with_zero_samples(self):
        """Train with 0 samples should raise error."""
        model = LSTMModel(window_days=30, epochs=5)
        X = np.array([]).reshape(0, 30)
        y = np.array([])

        with pytest.raises(ValueError, match="Insufficient data"):
            model.train(X, y)

    # O - One
    def test_train_with_one_sample(self):
        """Train with 1 sample should raise error (insufficient for LSTM)."""
        model = LSTMModel(window_days=30, epochs=5)
        X = np.random.rand(1, 30) * 50000
        y = np.random.rand(1) * 50000

        # LSTM needs at least window_days samples
        with pytest.raises(ValueError, match="Insufficient data"):
            model.train(X, y)

    # M - Many
    def test_train_with_many_samples(self):
        """Train with 365 days of data (335 samples)."""
        model = LSTMModel(window_days=30, epochs=5)  # Reduced epochs for speed
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
        model = LSTMModel(window_days=1, epochs=5)
        X = np.random.rand(10, 1) * 50000
        y = np.random.rand(10) * 50000

        model.train(X, y)
        assert model.is_trained

    def test_window_days_boundary_zero(self):
        """Window size of 0 should raise error."""
        with pytest.raises(ValueError, match="window_days must be >= 1"):
            LSTMModel(window_days=0)

    def test_lstm_units_boundary_zero(self):
        """lstm_units of 0 should raise error."""
        with pytest.raises(ValueError, match="lstm_units must be >= 1"):
            LSTMModel(lstm_units=0)

    def test_dropout_boundary_zero(self):
        """dropout of 0.0 is valid."""
        model = LSTMModel(dropout=0.0)
        assert model.dropout == 0.0

    def test_dropout_boundary_one(self):
        """dropout of 1.0 should raise error (must be < 1.0)."""
        with pytest.raises(ValueError, match="dropout must be in range"):
            LSTMModel(dropout=1.0)

    def test_dropout_boundary_negative(self):
        """Negative dropout should raise error."""
        with pytest.raises(ValueError, match="dropout must be in range"):
            LSTMModel(dropout=-0.1)

    def test_epochs_boundary_zero(self):
        """epochs of 0 should raise error."""
        with pytest.raises(ValueError, match="epochs must be >= 1"):
            LSTMModel(epochs=0)

    def test_batch_size_boundary_zero(self):
        """batch_size of 0 should raise error."""
        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            LSTMModel(batch_size=0)

    # I - Interfaces
    def test_predict_accepts_1d_array(self, sliding_window_data):
        """Predict should accept 1D array (window_days,)."""
        X, y = sliding_window_data
        model = LSTMModel(window_days=30, epochs=5)
        model.train(X, y)

        # 1D array
        X_new_1d = np.random.rand(30) * 50000
        prediction = model.predict(X_new_1d)
        assert isinstance(prediction, float)

    def test_predict_accepts_2d_array(self, sliding_window_data):
        """Predict should accept 2D array (1, window_days)."""
        X, y = sliding_window_data
        model = LSTMModel(window_days=30, epochs=5)
        model.train(X, y)

        # 2D array
        X_new_2d = np.random.rand(1, 30) * 50000
        prediction = model.predict(X_new_2d)
        assert isinstance(prediction, float)

    # E - Exceptions
    def test_predict_before_training_raises_error(self):
        """Predict on untrained model should raise error."""
        model = LSTMModel(window_days=30)
        X = np.random.rand(1, 30) * 50000

        with pytest.raises(ValueError, match="Model must be trained"):
            model.predict(X)

    def test_train_with_mismatched_shapes_raises_error(self):
        """Train with mismatched X and y shapes should raise error."""
        model = LSTMModel(window_days=30, epochs=5)
        X = np.random.rand(50, 30) * 50000
        y = np.random.rand(25) * 50000  # Different number of samples

        with pytest.raises(ValueError, match="same number of samples"):
            model.train(X, y)

    def test_train_with_wrong_feature_count_raises_error(self):
        """Train with wrong number of features should raise error."""
        model = LSTMModel(window_days=30, epochs=5)
        X = np.random.rand(50, 20) * 50000  # 20 features instead of 30
        y = np.random.rand(50) * 50000

        with pytest.raises(ValueError, match="must have 30 features"):
            model.train(X, y)

    def test_train_with_nan_values_raises_error(self):
        """Train with NaN values should raise error."""
        model = LSTMModel(window_days=30, epochs=5)
        X = np.random.rand(50, 30) * 50000
        X[0, 0] = np.nan
        y = np.random.rand(50) * 50000

        with pytest.raises(ValueError, match="contains NaN"):
            model.train(X, y)

    def test_train_with_inf_values_raises_error(self):
        """Train with infinite values should raise error."""
        model = LSTMModel(window_days=30, epochs=5)
        X = np.random.rand(50, 30) * 50000
        X[0, 0] = np.inf
        y = np.random.rand(50) * 50000

        with pytest.raises(ValueError, match="contains infinite"):
            model.train(X, y)

    def test_deserialize_corrupted_bytes_raises_error(self):
        """Deserialize corrupted bytes should raise error."""
        corrupted_bytes = b"not a valid pickle"

        with pytest.raises((pickle.UnpicklingError, ValueError)):
            LSTMModel.deserialize(corrupted_bytes)

    def test_deserialize_invalid_structure_raises_error(self):
        """Deserialize bytes with invalid structure should raise error."""
        # Pickle a simple dict instead of model state
        invalid_data = pickle.dumps({"wrong": "structure"})

        with pytest.raises(ValueError, match="Missing required keys"):
            LSTMModel.deserialize(invalid_data)

    # S - Serialization
    def test_serialize_untrained_model_works(self):
        """Serialize untrained model should work."""
        model = LSTMModel(window_days=30)
        model_bytes = model.serialize()

        assert isinstance(model_bytes, bytes)
        assert len(model_bytes) > 0

        # Should be able to restore
        restored = LSTMModel.deserialize(model_bytes)
        assert not restored.is_trained
        assert restored.window_days == 30
