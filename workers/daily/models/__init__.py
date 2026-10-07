"""
ML Models package for BTC Predictor.

This package provides abstract base classes and concrete implementations
of machine learning models used for Bitcoin price prediction.

Available Models:
    - BaseModel: Abstract base class defining the interface
    - LinearRegressionModel: Sklearn-based linear regression implementation

Example:
    >>> from workers.daily.models import LinearRegressionModel
    >>> import numpy as np
    >>>
    >>> # Create and train model
    >>> model = LinearRegressionModel(window_days=30)
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
    >>> restored_model = LinearRegressionModel.deserialize(model_bytes)
"""

from workers.daily.models.base import BaseModel
from workers.daily.models.linear import LinearRegressionModel

__all__ = ["BaseModel", "LinearRegressionModel"]
