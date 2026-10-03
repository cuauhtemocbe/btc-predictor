"""
LSTM model for BTC next-day return prediction.

This module implements a concrete ML model using LSTM (Long Short-Term Memory)
neural networks with Keras/TensorFlow, over the return features of
``shared.features``. LSTM excels at capturing temporal patterns and dependencies
in sequential data like time series.
"""

import pickle
import warnings

import numpy as np
import numpy.typing as npt

# Suppress TensorFlow warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

try:
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras import layers

    # Suppress TensorFlow logging
    tf.get_logger().setLevel("ERROR")
except ImportError as e:
    raise ImportError(
        "TensorFlow is required for LSTMModel. "
        "Install it with: pip install tensorflow-cpu>=2.13.0"
    ) from e

from workers.daily.models.base import BaseModel  # noqa: E402


class LSTMModel(BaseModel):
    """
    LSTM model over a sliding window of features.

    Like ``LinearRegressionModel`` it is agnostic to what the columns mean: the
    feature columns are fed to the LSTM as a sequence of ``n_features`` steps with
    one channel. The trainers give it the return features of shared.features and a
    log-return target, so predict() returns a log return (it is not clipped at
    zero, because returns can be negative); the predictor turns it into a price
    with shared.features.price_from_return().

    Attributes:
        window_days: Number of historical days used as features (default: 30)
        n_features: Number of feature columns (default: window_days)
        lstm_units: Number of LSTM units in the layer (default: 50)
        dropout: Dropout rate for regularization (default: 0.2)
        epochs: Number of training epochs (default: 50)
        batch_size: Batch size for training (default: 32)
        model: Keras Sequential model instance
        _is_trained: Internal flag tracking if model has been trained

    Example:
        >>> import numpy as np
        >>> model = LSTMModel(window_days=30)
        >>>
        >>> # Prepare training data (60 days -> 30 samples)
        >>> prices = np.random.rand(60) * 50000
        >>> X = np.array([prices[i:i+30] for i in range(30)])
        >>> y = np.array([prices[i+30] for i in range(30)])
        >>>
        >>> # Train and predict (with raw windows and a price target the
        >>> # prediction is a price; with shared.features it is a log return)
        >>> model.train(X, y)
        >>> X_new = prices[-30:].reshape(1, -1)
        >>> prediction = model.predict(X_new)
        >>>
        >>> # Serialize for storage
        >>> model_bytes = model.serialize()
        >>> restored = LSTMModel.deserialize(model_bytes)
    """

    def __init__(
        self,
        window_days: int = 30,
        lstm_units: int = 50,
        dropout: float = 0.2,
        epochs: int = 50,
        batch_size: int = 32,
        n_features: int | None = None,
    ):
        """
        Initialize a new LSTMModel.

        Args:
            window_days: Number of historical days to use as features.
                        Must be >= 1. Default is 30 days.
            lstm_units: Number of LSTM units. Must be >= 1. Default is 50.
            dropout: Dropout rate (0.0 to 0.9). Default is 0.2.
            epochs: Number of training epochs. Must be >= 1. Default is 50.
            batch_size: Batch size for training. Must be >= 1. Default is 32.
            n_features: Number of feature columns. Defaults to window_days (one
                        column per day). Models trained on the return features of
                        shared.features pass feature_count(window_days).

        Raises:
            ValueError: If any hyperparameter is out of valid range.

        Example:
            >>> model = LSTMModel()  # defaults
            >>> model = LSTMModel(window_days=60, lstm_units=100, epochs=100)
        """
        if window_days < 1:
            raise ValueError("window_days must be >= 1")
        if lstm_units < 1:
            raise ValueError("lstm_units must be >= 1")
        if not 0.0 <= dropout < 1.0:
            raise ValueError("dropout must be in range [0.0, 1.0)")
        if epochs < 1:
            raise ValueError("epochs must be >= 1")
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")

        self.window_days = window_days
        self.n_features = window_days if n_features is None else n_features
        self.lstm_units = lstm_units
        self.dropout = dropout
        self.epochs = epochs
        self.batch_size = batch_size

        self.model = self._build_model()
        self._is_trained = False

    def _build_model(self) -> keras.Sequential:
        """
        Build the LSTM neural network architecture.

        Returns:
            Keras Sequential model with LSTM layer.
        """
        model = keras.Sequential(
            [
                # Input layer: (batch_size, n_features, 1) for time series
                layers.Input(shape=(self.n_features, 1)),
                # LSTM layer with dropout for regularization
                layers.LSTM(units=self.lstm_units, dropout=self.dropout),
                # Output layer: single neuron for regression
                layers.Dense(1),
            ]
        )

        # Compile model with Adam optimizer and MSE loss
        model.compile(optimizer="adam", loss="mse", metrics=["mae"])

        return model

    def train(self, X: npt.NDArray[np.float64], y: npt.NDArray[np.float64]) -> None:
        """
        Train the model with historical price data.

        Args:
            X: Feature matrix of shape (n_samples, n_features).
            y: Target vector of shape (n_samples,): the next day's log return
               (or price, with raw close windows).

        Raises:
            ValueError: If X or y have invalid shapes.
            ValueError: If X contains NaN or infinite values.
            ValueError: If insufficient data (n_samples < window_days).

        Example:
            >>> model = LSTMModel(window_days=30)
            >>> X = np.random.rand(50, 30) * 50000
            >>> y = np.random.rand(50) * 50000
            >>> model.train(X, y)
            >>> assert model.is_trained
        """
        # Validate shapes
        if X.ndim != 2:
            raise ValueError(f"X must be 2-dimensional, got {X.ndim} dimensions")

        if y.ndim != 1:
            raise ValueError(f"y must be 1-dimensional, got {y.ndim} dimensions")

        if X.shape[0] != y.shape[0]:
            raise ValueError(
                f"X and y must have same number of samples. "
                f"Got X.shape[0]={X.shape[0]}, y.shape[0]={y.shape[0]}"
            )

        if X.shape[1] != self.n_features:
            raise ValueError(
                f"X must have {self.n_features} features, got {X.shape[1]}"
            )

        # Check for insufficient data
        if X.shape[0] < self.window_days:
            raise ValueError(
                f"Insufficient data: need at least {self.window_days} samples, "
                f"have {X.shape[0]}"
            )

        # Validate data quality
        if np.isnan(X).any():
            raise ValueError("X contains NaN values")

        if np.isinf(X).any():
            raise ValueError("X contains infinite values")

        if np.isnan(y).any():
            raise ValueError("y contains NaN values")

        if np.isinf(y).any():
            raise ValueError("y contains infinite values")

        # Reshape X for LSTM: (n_samples, n_features) -> (n_samples, n_features, 1)
        X_reshaped = X.reshape(X.shape[0], X.shape[1], 1)

        # Train the model (verbose=0 to suppress output)
        self.model.fit(
            X_reshaped,
            y,
            epochs=self.epochs,
            batch_size=self.batch_size,
            verbose=0,  # Silent training
            validation_split=0.2,  # Use 20% for validation
        )

        self._is_trained = True

    def predict(self, X: npt.NDArray[np.float64]) -> float:
        """
        Predict the target of the next day.

        Args:
            X: Feature vector of shape (1, n_features) or (n_features,).

        Returns:
            Predicted next-day log return (a price with raw close windows).

        Raises:
            ValueError: If model is not trained yet.
            ValueError: If X has invalid shape.

        Example:
            >>> model = LSTMModel(window_days=30)
            >>> # ... train model first ...
            >>> last_30_days = np.random.rand(1, 30) * 50000
            >>> prediction = model.predict(last_30_days)
        """
        # Check if model is trained
        if not self._is_trained:
            raise ValueError("Model must be trained before making predictions")

        # Reshape if needed (accept both (n_features,) and (1, n_features))
        if X.ndim == 1:
            if X.shape[0] != self.n_features:
                raise ValueError(
                    f"X must have {self.n_features} features, got {X.shape[0]}"
                )
            X = X.reshape(1, -1)
        elif X.ndim == 2:
            if X.shape[0] != 1:
                raise ValueError(
                    f"X must have shape (1, {self.n_features}), got {X.shape}"
                )
            if X.shape[1] != self.n_features:
                raise ValueError(
                    f"X must have {self.n_features} features, got {X.shape[1]}"
                )
        else:
            raise ValueError(f"X must be 1D or 2D, got {X.ndim} dimensions")

        # Validate data quality
        if np.isnan(X).any():
            raise ValueError("X contains NaN values")

        if np.isinf(X).any():
            raise ValueError("X contains infinite values")

        # Reshape for LSTM: (1, n_features) -> (1, n_features, 1)
        X_reshaped = X.reshape(1, self.n_features, 1)

        # Make prediction (verbose=0 to suppress output). Not clipped: a log
        # return is negative on a down day.
        return float(self.model.predict(X_reshaped, verbose=0)[0][0])

    def serialize(self) -> bytes:
        """
        Serialize the model to bytes for database storage.

        Serializes the Keras model weights and metadata (hyperparameters, is_trained)
        using pickle format. The Keras model is saved to a temporary HDF5 format,
        then pickled along with metadata.

        Returns:
            Serialized model as bytes.

        Raises:
            RuntimeError: If serialization fails.

        Example:
            >>> model = LSTMModel(window_days=30)
            >>> # ... train model ...
            >>> model_bytes = model.serialize()
            >>> assert len(model_bytes) < 10_000_000  # < 10MB
        """
        try:
            # Get model weights instead of saving to file
            # This is more efficient for database storage
            weights = self.model.get_weights()

            # Package model state: weights + metadata
            state = {
                "weights": weights,
                "window_days": self.window_days,
                "n_features": self.n_features,
                "lstm_units": self.lstm_units,
                "dropout": self.dropout,
                "epochs": self.epochs,
                "batch_size": self.batch_size,
                "is_trained": self._is_trained,
            }
            return pickle.dumps(state)
        except Exception as e:
            raise RuntimeError(f"Failed to serialize model: {e}") from e

    @classmethod
    def deserialize(cls, data: bytes) -> "LSTMModel":
        """
        Deserialize bytes back to an LSTMModel instance.

        Args:
            data: Serialized model bytes (from serialize() method).

        Returns:
            Reconstructed LSTMModel instance.

        Raises:
            ValueError: If data is corrupted.
            pickle.UnpicklingError: If unpickling fails.

        Example:
            >>> model_bytes = model.serialize()
            >>> restored = LSTMModel.deserialize(model_bytes)
            >>> assert restored.is_trained == model.is_trained
            >>> assert restored.window_days == model.window_days
        """
        try:
            state = pickle.loads(data)
        except pickle.UnpicklingError as e:
            raise pickle.UnpicklingError(f"Failed to unpickle model: {e}") from e
        except Exception as e:
            raise ValueError(f"Data is corrupted or invalid: {e}") from e

        # Validate state structure
        if not isinstance(state, dict):
            raise ValueError("Deserialized state must be a dictionary")

        required_keys = {
            "weights",
            "window_days",
            "lstm_units",
            "dropout",
            "epochs",
            "batch_size",
            "is_trained",
        }
        if not required_keys.issubset(state.keys()):
            missing = required_keys - state.keys()
            raise ValueError(f"Missing required keys in serialized data: {missing}")

        # Reconstruct model
        instance = cls(
            window_days=state["window_days"],
            lstm_units=state["lstm_units"],
            dropout=state["dropout"],
            epochs=state["epochs"],
            batch_size=state["batch_size"],
            n_features=state.get("n_features"),
        )

        # Restore weights
        instance.model.set_weights(state["weights"])
        instance._is_trained = state["is_trained"]

        return instance

    @property
    def is_trained(self) -> bool:
        """
        Check if the model has been trained.

        Returns:
            True if model is trained and ready for predictions, False otherwise.

        Example:
            >>> model = LSTMModel()
            >>> assert not model.is_trained
            >>> model.train(X, y)
            >>> assert model.is_trained
        """
        return self._is_trained
