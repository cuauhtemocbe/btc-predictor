"""
Tests for the model factory shared by the trainer and the backtest (#106).

The factory is the single place that knows how each model class is constructed,
so a backtest builds exactly the models the daily worker builds.
"""

import subprocess
import sys

import numpy as np
import pytest

from shared.features import feature_count
from workers.daily.models import (
    ARIMAModel,
    BaseModel,
    LinearRegressionModel,
    LSTMModel,
    XGBoostModel,
)
from workers.daily.models.factory import (
    MODEL_NAMES,
    build_model,
    instantiate_model,
    model_class_for,
)


def test_model_names_are_the_four_model_families() -> None:
    assert MODEL_NAMES == ("linear", "xgboost", "lstm", "arima")


def test_linear_is_built_with_the_return_feature_count() -> None:
    window = 21

    model = build_model("linear", window, feature_count(window))

    assert isinstance(model, LinearRegressionModel)
    assert model.window_days == window
    assert model.n_features == feature_count(window)


def test_unknown_model_name_is_rejected_with_the_valid_names() -> None:
    with pytest.raises(ValueError, match="Unknown model 'prophet'.*linear"):
        build_model("prophet", 21, 43)


def test_model_name_matching_is_exact_not_by_prefix() -> None:
    # production names carry a version ("linear_v1"); the factory takes the family
    with pytest.raises(ValueError, match="Unknown model"):
        build_model("linear_v1", 21, 43)


def test_instantiate_model_matches_what_the_trainer_does_for_each_class() -> None:
    class Plain(BaseModel):
        def __init__(self, window_days: int, n_features: int) -> None:
            self.window_days = window_days
            self.n_features = n_features

        # The stubs below only satisfy the abstract interface; they are never called.
        def train(self, X: np.ndarray, y: np.ndarray) -> None:  # pragma: no cover
            raise NotImplementedError

        def predict(self, X: np.ndarray) -> float:  # pragma: no cover
            raise NotImplementedError

        def serialize(self) -> bytes:  # pragma: no cover
            raise NotImplementedError

        @classmethod
        def deserialize(cls, data: bytes) -> BaseModel:  # pragma: no cover
            raise NotImplementedError

        @property
        def is_trained(self) -> bool:  # pragma: no cover
            raise NotImplementedError

    plain = instantiate_model(Plain, "custom", 30, 61)
    assert isinstance(plain, Plain)
    assert (plain.window_days, plain.n_features) == (30, 61)
    linear = instantiate_model(LinearRegressionModel, "linear", 30, 61)
    assert isinstance(linear, LinearRegressionModel)
    assert (linear.window_days, linear.n_features) == (30, 61)


@pytest.mark.parametrize("name", ["xgboost", "lstm", "arima"])
def test_every_model_name_resolves_to_a_base_model(name: str) -> None:
    model = build_model(name, 21, feature_count(21))

    assert isinstance(model, BaseModel)
    assert type(model) is model_class_for(name)


def test_arima_is_built_with_the_return_order_and_the_feature_count() -> None:
    model = build_model("arima", 21, feature_count(21))

    assert isinstance(model, ARIMAModel)
    assert model.order == (5, 0, 0)
    assert (model.window_days, model.n_features) == (21, feature_count(21))


@pytest.mark.parametrize("name", ["xgboost", "lstm"])
def test_xgboost_and_lstm_are_built_with_the_feature_count(name: str) -> None:
    model = build_model(name, 21, feature_count(21))

    assert isinstance(model, XGBoostModel | LSTMModel)
    assert (model.window_days, model.n_features) == (21, feature_count(21))


def test_building_linear_does_not_import_the_heavy_libraries() -> None:
    code = (
        "import sys; "
        "from workers.daily.models.factory import build_model; "
        "build_model('linear', 21, 43); "
        "heavy = {'tensorflow', 'xgboost', 'statsmodels'} & set(sys.modules); "
        "sys.exit(1 if heavy else 0)"
    )

    result = subprocess.run([sys.executable, "-c", code], capture_output=True)

    assert result.returncode == 0, result.stderr.decode()
