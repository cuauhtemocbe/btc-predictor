"""
Base abstract class for all ML prediction models.

This module defines the interface that all ML models must implement
to be compatible with the BTC Predictor training and prediction pipeline.
"""

from abc import ABC, abstractmethod

import numpy as np
import numpy.typing as npt


class BaseModel(ABC):
    """
    Abstract base class for ML prediction models.

    All concrete model implementations must inherit from this class
    and implement all abstract methods. This ensures a consistent
    interface for training, prediction, and serialization across
    different ML algorithms (Linear Regression, LSTM, XGBoost, etc.).

    Example:
        >>> class MyModel(BaseModel):
        ...     def train(
        ...         self, X: npt.NDArray[np.float64], y: npt.NDArray[np.float64]
        ...     ) -> None:
        ...         # Training logic here
        ...         pass
        ...
        ...     def predict(self, X: npt.NDArray[np.float64]) -> float:
        ...         # Prediction logic here
        ...         return 50000.0
        ...
        ...     def serialize(self) -> bytes:
        ...         # Serialization logic here
        ...         return b""
        ...
        ...     @classmethod
        ...     def deserialize(cls, data: bytes) -> "MyModel":
        ...         # Deserialization logic here
        ...         return cls()
        ...
        ...     @property
        ...     def is_trained(self) -> bool:
        ...         # Training status check
        ...         return True
    """

    @abstractmethod
    def train(self, X: npt.NDArray[np.float64], y: npt.NDArray[np.float64]) -> None:
        """
        Train the model with historical price data.

        Args:
            X: Feature matrix of shape (n_samples, n_features).
               Each row is a window of historical close prices.
            y: Target vector of shape (n_samples,).
               Each value is the next day's close price to predict.

        Raises:
            ValueError: If X or y have invalid shapes or contain NaN/inf values.

        Example:
            >>> model = LinearRegressionModel(window_days=30)
            >>> # 2 samples, 3 features
            >>> X = np.array([[100, 101, 102], [101, 102, 103]])
            >>> y = np.array([103, 104])  # 2 target values
            >>> model.train(X, y)
        """
        pass

    @abstractmethod
    def predict(self, X: npt.NDArray[np.float64]) -> float:
        """
        Predict the next day's BTC close price.

        Args:
            X: Feature vector of shape (1, n_features) or (n_features,).
               Contains the most recent n_features days of close prices.

        Returns:
            Predicted close price as a float (in USD).

        Raises:
            ValueError: If model is not trained yet.
            ValueError: If X has invalid shape.

        Example:
            >>> model = LinearRegressionModel(window_days=30)
            >>> # ... train model first ...
            >>> last_30_days = np.array([[50000, 50100, ..., 51000]])  # shape: (1, 30)
            >>> predicted_price = model.predict(last_30_days)
            >>> print(f"Predicted: ${predicted_price:.2f}")
        """
        pass

    @abstractmethod
    def serialize(self) -> bytes:
        """
        Serialize the model to bytes for storage in database.

        The serialized bytes should contain all necessary state to
        reconstruct the model, including:
        - Trained parameters/weights
        - Model configuration (e.g., window_days)
        - Training status

        Returns:
            Serialized model as bytes (typically pickle format).

        Raises:
            RuntimeError: If serialization fails.

        Example:
            >>> model = LinearRegressionModel(window_days=30)
            >>> # ... train model ...
            >>> model_bytes = model.serialize()
            >>> print(f"Model size: {len(model_bytes)} bytes")

        Note:
            The serialized bytes are stored in the database `models.artifact`
            column (BYTEA type). Size should be < 1MB for reasonable performance.
        """
        pass

    @classmethod
    @abstractmethod
    def deserialize(cls, data: bytes) -> "BaseModel":
        """
        Deserialize bytes back to a model instance.

        This is a class method that reconstructs a model from its
        serialized bytes representation. The restored model should
        be functionally identical to the original.

        Args:
            data: Serialized model bytes (from serialize() method).

        Returns:
            Reconstructed model instance, ready to make predictions.

        Raises:
            ValueError: If data is corrupted or invalid.
            pickle.UnpicklingError: If pickle deserialization fails.

        Example:
            >>> model_bytes = model.serialize()
            >>> restored_model = LinearRegressionModel.deserialize(model_bytes)
            >>> assert restored_model.is_trained == model.is_trained

        Note:
            The returned instance should preserve all state:
            - is_trained status
            - Model parameters
            - Configuration (window_days, etc.)
        """
        pass

    @property
    @abstractmethod
    def is_trained(self) -> bool:
        """
        Check if the model has been trained.

        Returns:
            True if model has been trained and is ready for predictions,
            False otherwise.

        Example:
            >>> model = LinearRegressionModel(window_days=30)
            >>> print(model.is_trained)  # False
            >>> model.train(X, y)
            >>> print(model.is_trained)  # True

        Note:
            Attempting to call predict() on an untrained model should
            raise a ValueError.
        """
        pass
