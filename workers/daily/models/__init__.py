"""
ML Models package for BTC Predictor.

This package provides abstract base classes and concrete implementations
of machine learning models used for Bitcoin price prediction.

Available Models:
    - BaseModel: Abstract base class defining the interface
    - LinearRegressionModel: Sklearn-based linear regression implementation
    - XGBoostModel: XGBoost gradient boosting implementation
    - LSTMModel: LSTM neural network implementation (Keras/TensorFlow)
    - ARIMAModel: ARIMA time series implementation (statsmodels)

Example:
    >>> from workers.daily.models import LinearRegressionModel, XGBoostModel
    >>> import numpy as np
    >>>
    >>> # Create and train model
    >>> model = XGBoostModel(window_days=30)
    >>> X = np.random.rand(50, 30)  # 50 samples, 30 features
    >>> y = np.random.rand(50)      # 50 target values
    >>> model.train(X, y)
    >>>
    >>> # Make prediction
    >>> X_new = np.random.rand(1, 30)
    >>> predicted_price = model.predict(X_new)
    >>>
    >>> # Serialize for storage
    >>> model_bytes = model.serialize()
    >>> restored_model = XGBoostModel.deserialize(model_bytes)
"""

from typing import TYPE_CHECKING, Any

from workers.daily.models.base import BaseModel
from workers.daily.models.linear import LinearRegressionModel

if TYPE_CHECKING:
    from workers.daily.models.arima_model import ARIMAModel
    from workers.daily.models.lstm_model import LSTMModel
    from workers.daily.models.xgboost_model import XGBoostModel

__all__ = [
    "BaseModel",
    "LinearRegressionModel",
    "XGBoostModel",
    "LSTMModel",
    "ARIMAModel",
]

# Importing these modules pulls in TensorFlow, XGBoost or statsmodels, which
# cost ~20 s. They are loaded on first access so a process (or a pytest xdist
# worker) that only uses the linear model never pays for them.
_LAZY_MODELS = {
    "ARIMAModel": "workers.daily.models.arima_model",
    "LSTMModel": "workers.daily.models.lstm_model",
    "XGBoostModel": "workers.daily.models.xgboost_model",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_MODELS:
        import importlib

        return getattr(importlib.import_module(_LAZY_MODELS[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
