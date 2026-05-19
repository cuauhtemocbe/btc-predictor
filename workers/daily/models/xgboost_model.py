"""
XGBoost model for BTC price prediction.

This module implements a concrete ML model using XGBoost (Extreme Gradient Boosting)
with sliding window feature engineering. XGBoost excels at capturing non-linear
relationships and interactions between features.
"""

import pickle

import numpy as np
import numpy.typing as npt
import xgboost as xgb

from workers.daily.models.base import BaseModel


class XGBoostModel(BaseModel):
    """
    XGBoost model for predicting next-day BTC close price.

    Uses a sliding window approach where the last N days of close prices
    are used as features to predict the next day's close price. XGBoost
    builds an ensemble of decision trees using gradient boosting.

    Attributes:
        window_days: Number of historical days used as features (default: 30)
        n_estimators: Number of boosting rounds (trees) (default: 100)
        max_depth: Maximum tree depth (default: 5)
        learning_rate: Step size shrinkage (default: 0.1)
        model: xgboost.XGBRegressor instance
        _is_trained: Internal flag tracking if model has been trained

    Example:
        >>> import numpy as np
        >>> model = XGBoostModel(window_days=30)
        >>>
        >>> # Prepare training data (60 days -> 30 samples)
        >>> prices = np.random.rand(60) * 50000
        >>> X = np.array([prices[i:i+30] for i in range(30)])
        >>> y = np.array([prices[i+30] for i in range(30)])
        >>>
        >>> # Train and predict
        >>> model.train(X, y)
        >>> X_new = prices[-30:].reshape(1, -1)
        >>> predicted_price = model.predict(X_new)
        >>> print(f"Predicted: ${predicted_price:.2f}")
        >>>
        >>> # Serialize for storage
        >>> model_bytes = model.serialize()
        >>> restored = XGBoostModel.deserialize(model_bytes)
    """

    def __init__(
        self,
        window_days: int = 30,
        n_estimators: int = 100,
        max_depth: int = 5,
        learning_rate: float = 0.1,
    ):
        """
        Initialize a new XGBoostModel.

        Args:
            window_days: Number of historical days to use as features.
                        Must be >= 1. Default is 30 days.
            n_estimators: Number of boosting rounds (trees).
                         Must be >= 1. Default is 100.
            max_depth: Maximum tree depth. Must be >= 1. Default is 5.
            learning_rate: Step size shrinkage. Must be > 0. Default is 0.1.

        Raises:
            ValueError: If any hyperparameter is out of valid range.

        Example:
            >>> model = XGBoostModel()  # defaults
            >>> model = XGBoostModel(window_days=60, n_estimators=200)
        """
        if window_days < 1:
            raise ValueError("window_days must be >= 1")
        if n_estimators < 1:
            raise ValueError("n_estimators must be >= 1")
        if max_depth < 1:
            raise ValueError("max_depth must be >= 1")
        if learning_rate <= 0:
            raise ValueError("learning_rate must be > 0")

        self.window_days = window_days
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate

        self.model = xgb.XGBRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            random_state=42,  # For reproducibility
            verbosity=0,  # Suppress training output
        )
        self._is_trained = False

    def train(self, X: npt.NDArray[np.float64], y: npt.NDArray[np.float64]) -> None:
        """
        Train the model with historical price data.

        Args:
            X: Feature matrix of shape (n_samples, window_days).
               Each row contains window_days consecutive close prices.
            y: Target vector of shape (n_samples,).
               Each value is the next day's close price.

        Raises:
            ValueError: If X or y have invalid shapes.
            ValueError: If X contains NaN or infinite values.
            ValueError: If insufficient data (n_samples < window_days).

        Example:
            >>> model = XGBoostModel(window_days=30)
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

        if X.shape[1] != self.window_days:
            raise ValueError(
                f"X must have {self.window_days} features (window_days), "
                f"got {X.shape[1]}"
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

        # Train the model
        self.model.fit(X, y)
        self._is_trained = True

    def predict(self, X: npt.NDArray[np.float64]) -> float:
        """
        Predict the next day's BTC close price.

        Args:
            X: Feature vector of shape (1, window_days) or (window_days,).
               Contains the most recent window_days close prices.

        Returns:
            Predicted close price as a float (in USD).

        Raises:
            ValueError: If model is not trained yet.
            ValueError: If X has invalid shape.

        Example:
            >>> model = XGBoostModel(window_days=30)
            >>> # ... train model first ...
            >>> last_30_days = np.random.rand(1, 30) * 50000
            >>> predicted_price = model.predict(last_30_days)
            >>> assert predicted_price > 0
        """
        # Check if model is trained
        if not self._is_trained:
            raise ValueError("Model must be trained before making predictions")

        # Reshape if needed (accept both (window_days,) and (1, window_days))
        if X.ndim == 1:
            if X.shape[0] != self.window_days:
                raise ValueError(
                    f"X must have {self.window_days} features, got {X.shape[0]}"
                )
            X = X.reshape(1, -1)
        elif X.ndim == 2:
            if X.shape[0] != 1:
                raise ValueError(
                    f"X must have shape (1, {self.window_days}), got {X.shape}"
                )
            if X.shape[1] != self.window_days:
                raise ValueError(
                    f"X must have {self.window_days} features, got {X.shape[1]}"
                )
        else:
            raise ValueError(f"X must be 1D or 2D, got {X.ndim} dimensions")

        # Validate data quality
        if np.isnan(X).any():
            raise ValueError("X contains NaN values")

        if np.isinf(X).any():
            raise ValueError("X contains infinite values")

        # Make prediction
        prediction = self.model.predict(X)[0]
        return float(prediction)

    def serialize(self) -> bytes:
        """
        Serialize the model to bytes for database storage.

        Serializes both the XGBoost model and metadata (hyperparameters, is_trained)
        using pickle format.

        Returns:
            Serialized model as bytes.

        Raises:
            RuntimeError: If serialization fails.

        Example:
            >>> model = XGBoostModel(window_days=30)
            >>> # ... train model ...
            >>> model_bytes = model.serialize()
            >>> assert len(model_bytes) < 1_000_000  # < 1MB
        """
        try:
            # Package model state: XGBoost model + metadata
            state = {
                "xgboost_model": self.model,
                "window_days": self.window_days,
                "n_estimators": self.n_estimators,
                "max_depth": self.max_depth,
                "learning_rate": self.learning_rate,
                "is_trained": self._is_trained,
            }
            return pickle.dumps(state)
        except Exception as e:
            raise RuntimeError(f"Failed to serialize model: {e}") from e

    @classmethod
    def deserialize(cls, data: bytes) -> "XGBoostModel":
        """
        Deserialize bytes back to an XGBoostModel instance.

        Args:
            data: Serialized model bytes (from serialize() method).

        Returns:
            Reconstructed XGBoostModel instance.

        Raises:
            ValueError: If data is corrupted.
            pickle.UnpicklingError: If unpickling fails.

        Example:
            >>> model_bytes = model.serialize()
            >>> restored = XGBoostModel.deserialize(model_bytes)
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
            "xgboost_model",
            "window_days",
            "n_estimators",
            "max_depth",
            "learning_rate",
            "is_trained",
        }
        if not required_keys.issubset(state.keys()):
            missing = required_keys - state.keys()
            raise ValueError(f"Missing required keys in serialized data: {missing}")

        # Reconstruct model
        instance = cls(
            window_days=state["window_days"],
            n_estimators=state["n_estimators"],
            max_depth=state["max_depth"],
            learning_rate=state["learning_rate"],
        )
        instance.model = state["xgboost_model"]
        instance._is_trained = state["is_trained"]

        return instance

    @property
    def is_trained(self) -> bool:
        """
        Check if the model has been trained.

        Returns:
            True if model is trained and ready for predictions, False otherwise.

        Example:
            >>> model = XGBoostModel()
            >>> assert not model.is_trained
            >>> model.train(X, y)
            >>> assert model.is_trained
        """
        return self._is_trained
