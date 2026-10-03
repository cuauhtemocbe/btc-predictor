"""
ARIMA model for BTC next-day return prediction.

This module implements a concrete ML model using ARIMA (AutoRegressive Integrated
Moving Average) from statsmodels, fitted on the daily log return series. ARIMA is
a classical time series model that captures autocorrelation patterns.
"""

import pickle
import warnings
from typing import Any

import numpy as np
import numpy.typing as npt

# Suppress statsmodels convergence warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

try:
    from statsmodels.tsa.arima.model import ARIMA
except ImportError as e:
    raise ImportError(
        "Statsmodels is required for ARIMAModel. "
        "Install it with: pip install statsmodels>=0.14.0"
    ) from e

from workers.daily.models.base import BaseModel  # noqa: E402


def _first_forecast(forecast: Any) -> float:
    """First value of an ARIMA forecast (a pandas Series or an array)."""
    if hasattr(forecast, "iloc"):
        return float(forecast.iloc[0])
    return float(forecast[0]) if len(forecast) > 0 else float(forecast)


class ARIMAModel(BaseModel):
    """
    ARIMA model for predicting the next-day BTC log return.

    Fits ARIMA (AutoRegressive Integrated Moving Average) to the series of daily
    log returns. ARIMA captures:
    - AR (p): Autoregressive terms (past values influence current)
    - I (d): Differencing order (0 by default: returns are already differenced)
    - MA (q): Moving average terms (past errors influence current)

    Unlike the other models it does not use every feature column. The training
    samples are consecutive days, so the series is the first ``window_days``
    columns of the first sample (the lagged returns of shared.features) followed by
    the targets ``y`` (the next-day returns). To predict, it forecasts one step
    from the first ``window_days`` columns of ``X`` (the latest returns) with the
    parameters fitted at training time; it does not refit.

    Attributes:
        order: ARIMA order (p, d, q) tuple (default: (5, 0, 0))
        seasonal_order: Seasonal order (P, D, Q, s) tuple (default: (0, 0, 0, 0))
        window_days: Number of latest returns that feed a forecast (default: 30)
        n_features: Number of feature columns of X (default: window_days)
        model: statsmodels ARIMA model instance
        fitted_model: Fitted ARIMA results object
        _is_trained: Internal flag tracking if model has been trained
        _training_data: Return series the model was fitted on

    Example:
        >>> import numpy as np
        >>> model = ARIMAModel(order=(5, 0, 0), window_days=10)
        >>>
        >>> # Daily log returns; X holds consecutive windows, y the next return
        >>> returns = np.random.normal(0, 0.02, 60)
        >>> X = np.array([returns[i:i+10] for i in range(50)])
        >>> y = returns[10:]
        >>>
        >>> # Train and predict the next return
        >>> model.train(X, y)
        >>> predicted_return = model.predict(returns[-10:].reshape(1, -1))
        >>>
        >>> # Serialize for storage
        >>> model_bytes = model.serialize()
        >>> restored = ARIMAModel.deserialize(model_bytes)
    """

    def __init__(
        self,
        order: tuple[int, int, int] = (5, 0, 0),
        seasonal_order: tuple[int, int, int, int] = (0, 0, 0, 0),
        window_days: int = 30,
        n_features: int | None = None,
    ):
        """
        Initialize a new ARIMAModel.

        Args:
            order: ARIMA order (p, d, q) where:
                   p = number of autoregressive terms (>= 0)
                   d = differencing order (>= 0)
                   q = number of moving average terms (>= 0)
                   Default is (5, 0, 0) - AR(5) on the return series.
            seasonal_order: Seasonal order (P, D, Q, s) where:
                           P, D, Q = seasonal equivalents of p, d, q
                           s = seasonal period
                           Default is (0, 0, 0, 0) - no seasonality.
            window_days: Number of latest returns that feed a forecast. They are
                         the first window_days columns of X. Must be >= 1.
            n_features: Number of feature columns of X. Defaults to window_days.
                        Models trained on the return features of shared.features
                        pass feature_count(window_days).

        Raises:
            ValueError: If order, seasonal_order or window_days are invalid, or
                        n_features is smaller than window_days.

        Example:
            >>> model = ARIMAModel()  # defaults
            >>> model = ARIMAModel(order=(7, 0, 1))  # ARIMA(7,0,1)
        """
        # Validate order
        if len(order) != 3:
            raise ValueError("order must be a 3-tuple (p, d, q)")
        p, d, q = order
        if p < 0 or d < 0 or q < 0:
            raise ValueError("order values (p, d, q) must be >= 0")

        # Validate seasonal_order
        if len(seasonal_order) != 4:
            raise ValueError("seasonal_order must be a 4-tuple (P, D, Q, s)")
        P, D, Q, s = seasonal_order
        if P < 0 or D < 0 or Q < 0 or s < 0:
            raise ValueError("seasonal_order values must be >= 0")

        if window_days < 1:
            raise ValueError("window_days must be >= 1")
        n_features = window_days if n_features is None else n_features
        if n_features < window_days:
            raise ValueError(
                f"n_features ({n_features}) must be >= window_days ({window_days})"
            )

        self.order = order
        self.seasonal_order = seasonal_order
        self.window_days = window_days
        self.n_features = n_features
        self.model = None
        self.fitted_model = None
        self._is_trained = False
        self._training_data = None  # Return series the model was fitted on

    def train(self, X: npt.NDArray[np.float64], y: npt.NDArray[np.float64]) -> None:
        """
        Train the model with the daily log return series.

        The samples are consecutive days, so the return series is rebuilt from the
        first ``window_days`` columns of the first sample (its lagged returns)
        followed by every target in ``y`` (the next-day returns), and ARIMA is
        fitted to it. The other feature columns are not used.

        Args:
            X: Feature matrix of shape (n_samples, n_features). Its first
               window_days columns are the lagged returns of the sample.
            y: Target vector of shape (n_samples,): the next-day log returns.

        Raises:
            ValueError: If X or y have invalid shapes.
            ValueError: If X contains NaN or infinite values.
            ValueError: If insufficient data.

        Example:
            >>> model = ARIMAModel(order=(5, 0, 0), window_days=30)
            >>> X = np.random.normal(0, 0.02, (50, 30))
            >>> y = np.random.normal(0, 0.02, 50)
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

        # Check for insufficient data (ARIMA needs enough history)
        min_samples = max(self.order[0] + self.order[2], 10)
        if X.shape[0] < min_samples:
            raise ValueError(
                f"Insufficient data: need at least {min_samples} samples, "
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

        # Rebuild the return series: the lagged returns of the first sample, then
        # the next-day return of every sample
        full_series = np.concatenate([X[0, : self.window_days], y])

        self._training_data = full_series

        # Fit ARIMA model
        try:
            self.model = ARIMA(
                full_series, order=self.order, seasonal_order=self.seasonal_order
            )
            self.fitted_model = self.model.fit()
            self._is_trained = True
        except Exception as e:
            raise ValueError(f"ARIMA model failed to converge: {e}") from e

    def predict(self, X: npt.NDArray[np.float64]) -> float:
        """
        Predict the next-day log return.

        Forecasts one step ahead from the latest returns in X (its first
        ``window_days`` columns) with the parameters fitted at training time.

        Args:
            X: Feature vector of shape (1, n_features) or (n_features,).

        Returns:
            Predicted next-day log return.

        Raises:
            ValueError: If model is not trained yet.
            ValueError: If X has invalid shape.

        Example:
            >>> model = ARIMAModel(order=(5, 0, 0), window_days=30)
            >>> # ... train model first ...
            >>> latest_returns = np.random.normal(0, 0.02, (1, 30))
            >>> predicted_return = model.predict(latest_returns)
        """
        # Check if model is trained
        if not self._is_trained:
            raise ValueError("Model must be trained before making predictions")

        X = self._validated_features(X)

        # Same parameters, new observations: no refit
        latest_returns = X[0, : self.window_days]
        extended = self.fitted_model.apply(latest_returns, refit=False)
        return _first_forecast(extended.forecast(steps=1))

    def _validated_features(
        self, X: npt.NDArray[np.float64]
    ) -> npt.NDArray[np.float64]:
        """
        Check the shape and content of a prediction input.

        Accepts ``(n_features,)`` and ``(1, n_features)`` and returns it as
        ``(1, n_features)``.

        Raises:
            ValueError: If X has the wrong shape or contains NaN or infinite values.
        """
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

        return X

    def serialize(self) -> bytes:
        """
        Serialize the model to bytes for database storage.

        Serializes the ARIMA fitted model and metadata using pickle format.

        Returns:
            Serialized model as bytes.

        Raises:
            RuntimeError: If serialization fails.

        Example:
            >>> model = ARIMAModel(order=(5, 0, 0))
            >>> # ... train model ...
            >>> model_bytes = model.serialize()
            >>> assert len(model_bytes) < 5_000_000  # < 5MB
        """
        try:
            # Package model state: fitted model + metadata
            state = {
                "fitted_model": self.fitted_model,
                "order": self.order,
                "seasonal_order": self.seasonal_order,
                "is_trained": self._is_trained,
                "training_data": self._training_data,
                "window_days": self.window_days,
                "n_features": self.n_features,
            }
            return pickle.dumps(state)
        except Exception as e:
            raise RuntimeError(f"Failed to serialize model: {e}") from e

    @classmethod
    def deserialize(cls, data: bytes) -> "ARIMAModel":
        """
        Deserialize bytes back to an ARIMAModel instance.

        Args:
            data: Serialized model bytes (from serialize() method).

        Returns:
            Reconstructed ARIMAModel instance.

        Raises:
            ValueError: If data is corrupted.
            pickle.UnpicklingError: If unpickling fails.

        Example:
            >>> model_bytes = model.serialize()
            >>> restored = ARIMAModel.deserialize(model_bytes)
            >>> assert restored.is_trained == model.is_trained
            >>> assert restored.order == model.order
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
            "fitted_model",
            "order",
            "seasonal_order",
            "is_trained",
            "training_data",
            "window_days",
        }
        if not required_keys.issubset(state.keys()):
            missing = required_keys - state.keys()
            raise ValueError(f"Missing required keys in serialized data: {missing}")

        # Reconstruct model
        instance = cls(
            order=state["order"],
            seasonal_order=state["seasonal_order"],
            window_days=state["window_days"],
            n_features=state.get("n_features"),
        )
        instance.fitted_model = state["fitted_model"]
        instance._is_trained = state["is_trained"]
        instance._training_data = state["training_data"]

        return instance

    @property
    def is_trained(self) -> bool:
        """
        Check if the model has been trained.

        Returns:
            True if model is trained and ready for predictions, False otherwise.

        Example:
            >>> model = ARIMAModel()
            >>> assert not model.is_trained
            >>> model.train(X, y)
            >>> assert model.is_trained
        """
        return self._is_trained
