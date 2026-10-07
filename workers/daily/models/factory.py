"""
Model construction shared by the daily trainer and the walk-forward backtest.

One place knows how the model class is built (it takes the window and the feature
count), so the backtest instantiates exactly the model the daily worker does.
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


def instantiate_model(
    model_class: type[BaseModel],
    window_days: int,
    n_features: int,
) -> BaseModel:
    """
    Build an untrained model the way the daily trainer does.

    Args:
        model_class: Class to instantiate.
        window_days: Sliding-window size.
        n_features: Feature columns of the training matrix.
    """
    return model_class(  # type: ignore[call-arg]
        window_days=window_days, n_features=n_features
    )


def build_model(name: str, window_days: int, n_features: int) -> BaseModel:
    """Build an untrained model by family name; see ``instantiate_model``."""
    return instantiate_model(model_class_for(name), window_days, n_features)
