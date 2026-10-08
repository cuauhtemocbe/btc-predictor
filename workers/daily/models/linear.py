"""Linear regression model over the return features of ``shared.features``."""

import pickle

import numpy as np
import numpy.typing as npt
from sklearn.linear_model import LinearRegression

from workers.daily.models.base import BaseModel


class LinearRegressionModel(BaseModel):
    """sklearn linear regression, agnostic to what its columns mean.

    The trainer and the predictor feed it ``shared.features`` columns (lagged log
    returns, their volatility and log volume changes) and a next-day log return as
    target, so ``predict`` returns a log return; ``shared.features.price_from_return``
    turns it into a price.

    Attributes:
        window_days: Days of history per sample.
        n_features: Feature columns; ``feature_count(window_days)`` for the return
            features, ``window_days`` by default.
    """

    def __init__(self, window_days: int = 30, n_features: int | None = None):
        """Create an untrained model.

        Args:
            window_days: Days of history per sample, at least 1.
            n_features: Feature columns; defaults to ``window_days``.

        Raises:
            ValueError: If ``window_days`` < 1.
        """
        if window_days < 1:
            raise ValueError("window_days must be >= 1")

        self.window_days = window_days
        self.n_features = window_days if n_features is None else n_features
        self.model = LinearRegression()
        self._is_trained = False

    def train(self, X: npt.NDArray[np.float64], y: npt.NDArray[np.float64]) -> None:
        """Fit the model.

        Args:
            X: Features of shape (n_samples, n_features): lagged log returns,
                volatility and log volume changes.
            y: Next-day log return, shape (n_samples,).

        Raises:
            ValueError: If the shapes do not match or X or y hold NaN or inf.
        """
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
                f"X must have {self.n_features} features (window_days), "
                f"got {X.shape[1]}"
            )

        if np.isnan(X).any():
            raise ValueError("X contains NaN values")

        if np.isinf(X).any():
            raise ValueError("X contains infinite values")

        if np.isnan(y).any():
            raise ValueError("y contains NaN values")

        if np.isinf(y).any():
            raise ValueError("y contains infinite values")

        self.model.fit(X, y)
        self._is_trained = True

    def predict(self, X: npt.NDArray[np.float64]) -> float:
        """Predict the next-day log return.

        Args:
            X: One sample, shape (n_features,) or (1, n_features).

        Raises:
            ValueError: If the model is untrained, or X has the wrong shape or holds
                NaN or infinite values.
        """
        if not self._is_trained:
            raise ValueError("Model must be trained before making predictions")

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

        if np.isnan(X).any():
            raise ValueError("X contains NaN values")

        if np.isinf(X).any():
            raise ValueError("X contains infinite values")

        prediction = self.model.predict(X)[0]
        return float(prediction)

    def serialize(self) -> bytes:
        """Pickle the sklearn model with its configuration and trained flag.

        Raises:
            RuntimeError: If pickling fails.
        """
        try:
            state = {
                "sklearn_model": self.model,
                "window_days": self.window_days,
                "n_features": self.n_features,
                "is_trained": self._is_trained,
            }
            return pickle.dumps(state)
        except Exception as e:
            raise RuntimeError(f"Failed to serialize model: {e}") from e

    @classmethod
    def deserialize(cls, data: bytes) -> "LinearRegressionModel":
        """Rebuild a model from the bytes ``serialize`` returned.

        Raises:
            pickle.UnpicklingError: If unpickling fails.
            ValueError: If the data is corrupted or lacks required keys.
        """
        try:
            state = pickle.loads(data)
        except pickle.UnpicklingError as e:
            raise pickle.UnpicklingError(f"Failed to unpickle model: {e}") from e
        except Exception as e:
            raise ValueError(f"Data is corrupted or invalid: {e}") from e

        if not isinstance(state, dict):
            raise ValueError("Deserialized state must be a dictionary")

        required_keys = {"sklearn_model", "window_days", "is_trained"}
        if not required_keys.issubset(state.keys()):
            missing = required_keys - state.keys()
            raise ValueError(f"Missing required keys in serialized data: {missing}")

        instance = cls(
            window_days=state["window_days"],
            n_features=state.get("n_features"),
        )
        instance.model = state["sklearn_model"]
        instance._is_trained = state["is_trained"]

        return instance

    @property
    def is_trained(self) -> bool:
        """True once ``train`` has run."""
        return self._is_trained
