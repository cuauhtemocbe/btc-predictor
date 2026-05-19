"""
ARIMA model for BTC price prediction.

This module implements a concrete ML model using ARIMA (AutoRegressive Integrated
Moving Average) from statsmodels. ARIMA is a classical time series model that
captures trends, seasonality, and autocorrelation patterns.
"""

import pickle
import warnings

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

from workers.daily.models.base import BaseModel


class ARIMAModel(BaseModel):
    """
    ARIMA model for predicting next-day BTC close price.

    Uses ARIMA (AutoRegressive Integrated Moving Average) to model time series
    patterns in BTC prices. ARIMA captures:
    - AR (p): Autoregressive terms (past values influence current)
    - I (d): Differencing order (removes trends)
    - MA (q): Moving average terms (past errors influence current)

    Note: ARIMA works directly on the time series without sliding windows.
    It uses the entire price history to predict the next value.

    Attributes:
        order: ARIMA order (p, d, q) tuple (default: (5, 1, 0))
        seasonal_order: Seasonal order (P, D, Q, s) tuple (default: (0, 0, 0, 0))
        model: statsmodels ARIMA model instance
        fitted_model: Fitted ARIMA results object
        _is_trained: Internal flag tracking if model has been trained
        _training_data: Store training data for forecasting

    Example:
        >>> import numpy as np
        >>> model = ARIMAModel(order=(5, 1, 0))
        >>>
        >>> # Prepare training data: time series of prices
        >>> prices = np.random.rand(60) * 50000 + 50000
        >>> X = prices[:-1].reshape(-1, 1)  # All but last
        >>> y = prices[1:]  # All but first (shifted by 1)
        >>>
        >>> # Train and predict
        >>> model.train(X, y)
        >>> X_new = prices[-30:].reshape(1, -1)
        >>> predicted_price = model.predict(X_new)
        >>> print(f"Predicted: ${predicted_price:.2f}")
        >>>
        >>> # Serialize for storage
        >>> model_bytes = model.serialize()
        >>> restored = ARIMAModel.deserialize(model_bytes)
    """

    def __init__(
        self,
        order: tuple[int, int, int] = (5, 1, 0),
        seasonal_order: tuple[int, int, int, int] = (0, 0, 0, 0),
    ):
        """
        Initialize a new ARIMAModel.

        Args:
            order: ARIMA order (p, d, q) where:
                   p = number of autoregressive terms (>= 0)
                   d = differencing order (>= 0)
                   q = number of moving average terms (>= 0)
                   Default is (5, 1, 0) - AR(5) with first differencing.
            seasonal_order: Seasonal order (P, D, Q, s) where:
                           P, D, Q = seasonal equivalents of p, d, q
                           s = seasonal period
                           Default is (0, 0, 0, 0) - no seasonality.

        Raises:
            ValueError: If order or seasonal_order have invalid values.

        Example:
            >>> model = ARIMAModel()  # defaults
            >>> model = ARIMAModel(order=(7, 1, 1))  # ARIMA(7,1,1)
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

        self.order = order
        self.seasonal_order = seasonal_order
        self.model = None
        self.fitted_model = None
        self._is_trained = False
        self._training_data = None  # Store last seen prices for forecasting
        self.window_days = 30  # For interface compatibility

    def train(self, X: npt.NDArray[np.float64], y: npt.NDArray[np.float64]) -> None:
        """
        Train the model with historical price data.

        For ARIMA, we reconstruct the full time series from X and y.
        X contains sliding windows, y contains next-day prices.
        We extract the complete price history and fit ARIMA to it.

        Args:
            X: Feature matrix of shape (n_samples, window_days).
               Each row contains window_days consecutive close prices.
            y: Target vector of shape (n_samples,).
               Each value is the next day's close price.

        Raises:
            ValueError: If X or y have invalid shapes.
            ValueError: If X contains NaN or infinite values.
            ValueError: If insufficient data.

        Example:
            >>> model = ARIMAModel(order=(5, 1, 0))
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

        # Reconstruct full time series from X and y
        # X[0] contains the first window_days prices
        # y contains the next-day prices for each window
        # Full series: X[0] (all features) + y (all targets)
        first_window = X[0]  # First window of prices
        remaining_prices = y  # All next-day predictions

        # Combine into full series
        full_series = np.concatenate([first_window, remaining_prices])

        # Store for later forecasting
        self._training_data = full_series
        self.window_days = X.shape[1]  # Store window size

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
        Predict the next day's BTC close price.

        For ARIMA, we use the fitted model to forecast 1 step ahead
        from the current data.

        Args:
            X: Feature vector of shape (1, window_days) or (window_days,).
               Contains the most recent window_days close prices.

        Returns:
            Predicted close price as a float (in USD).

        Raises:
            ValueError: If model is not trained yet.
            ValueError: If X has invalid shape.

        Example:
            >>> model = ARIMAModel(order=(5, 1, 0))
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

        # For ARIMA, we append the new data to the training series
        # and forecast 1 step ahead
        new_data = X.flatten()

        # Create a new series with recent data
        # Use last (window_days) points from training + new data
        recent_series = np.concatenate(
            [self._training_data[-self.window_days :], new_data]
        )

        # Fit ARIMA on recent data and forecast
        try:
            # Refit model on recent data for better predictions
            temp_model = ARIMA(
                recent_series, order=self.order, seasonal_order=self.seasonal_order
            )
            temp_fitted = temp_model.fit()

            # Forecast 1 step ahead
            forecast = temp_fitted.forecast(steps=1)
            # forecast is a pandas Series, get the first value
            if hasattr(forecast, 'iloc'):
                prediction = float(forecast.iloc[0])
            else:
                # If it's an array, get first element
                prediction = float(forecast[0]) if len(forecast) > 0 else float(forecast)

            return prediction
        except Exception:
            # Fallback: use original fitted model
            forecast = self.fitted_model.forecast(steps=1)
            # forecast is a pandas Series, get the first value
            if hasattr(forecast, 'iloc'):
                prediction = float(forecast.iloc[0])
            else:
                # If it's an array, get first element
                prediction = float(forecast[0]) if len(forecast) > 0 else float(forecast)
            return prediction

    def serialize(self) -> bytes:
        """
        Serialize the model to bytes for database storage.

        Serializes the ARIMA fitted model and metadata using pickle format.

        Returns:
            Serialized model as bytes.

        Raises:
            RuntimeError: If serialization fails.

        Example:
            >>> model = ARIMAModel(order=(5, 1, 0))
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
        )
        instance.fitted_model = state["fitted_model"]
        instance._is_trained = state["is_trained"]
        instance._training_data = state["training_data"]
        instance.window_days = state["window_days"]

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
