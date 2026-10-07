"""
Model construction shared by the daily trainer and the walk-forward backtest.

One place knows how the model is built (it takes the window and the feature count),
so the backtest builds exactly the model the daily worker does. It stays with a
single model because the backtest CLI takes its ``--model`` choices from it.
"""

from workers.daily.models.base import BaseModel
from workers.daily.models.linear import LinearRegressionModel

MODEL_NAMES = ("linear",)


def model_class_for(name: str) -> type[BaseModel]:
    """
    Model class of a model family name (``linear``).

    Raises:
        ValueError: If ``name`` is not one of MODEL_NAMES.
    """
    if name == "linear":
        return LinearRegressionModel
    raise ValueError(f"Unknown model '{name}'; valid models: {', '.join(MODEL_NAMES)}")


def build_model(name: str, window_days: int, n_features: int) -> LinearRegressionModel:
    """
    Build an untrained model by family name, the way the trainer and the backtest do.

    Args:
        name: Model family name (``linear``).
        window_days: Sliding-window size.
        n_features: Feature columns of the training matrix.

    Raises:
        ValueError: If ``name`` is not one of MODEL_NAMES.
    """
    model_class_for(name)
    return LinearRegressionModel(window_days=window_days, n_features=n_features)
