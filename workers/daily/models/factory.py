"""
Model construction shared by the daily trainer and the walk-forward backtest.

One place knows how each model class is built (ARIMA takes an ``order``, Linear
takes the feature count, the rest take the window), so the backtest instantiates
exactly the models the daily worker does. LSTM, XGBoost and ARIMA are imported on
demand: loading them pulls in TensorFlow, XGBoost and statsmodels.
"""

from workers.daily.models.base import BaseModel
from workers.daily.models.linear import LinearRegressionModel

MODEL_NAMES = ("linear", "xgboost", "lstm", "arima")

ARIMA_ORDER = (5, 1, 0)


def model_class_for(name: str) -> type[BaseModel]:
    """
    Model class of a model family name (``linear``, ``xgboost``, ``lstm``, ``arima``).

    Raises:
        ValueError: If ``name`` is not one of MODEL_NAMES.
    """
    if name == "linear":
        return LinearRegressionModel
    if name == "xgboost":
        from workers.daily.models.xgboost_model import XGBoostModel

        return XGBoostModel
    if name == "lstm":
        from workers.daily.models.lstm_model import LSTMModel

        return LSTMModel
    if name == "arima":
        from workers.daily.models.arima_model import ARIMAModel

        return ARIMAModel
    raise ValueError(f"Unknown model '{name}'; valid models: {', '.join(MODEL_NAMES)}")


def instantiate_model(
    model_class: type[BaseModel],
    model_name: str,
    window_days: int,
    n_features: int,
) -> BaseModel:
    """
    Build an untrained model the way the daily trainer does.

    Args:
        model_class: Class to instantiate.
        model_name: Model family name; ``arima`` is built with ARIMA_ORDER.
        window_days: Sliding-window size.
        n_features: Feature columns of the training matrix (used by Linear).
    """
    if model_name == "arima":
        return model_class(order=ARIMA_ORDER)  # type: ignore[call-arg]
    if issubclass(model_class, LinearRegressionModel):
        return model_class(window_days=window_days, n_features=n_features)
    return model_class(window_days=window_days)  # type: ignore[call-arg]


def build_model(name: str, window_days: int, n_features: int) -> BaseModel:
    """Build an untrained model by family name; see ``instantiate_model``."""
    return instantiate_model(model_class_for(name), name, window_days, n_features)
