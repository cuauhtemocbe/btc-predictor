"""
Tests for the model factory shared by the trainer and the backtest (#106).

The factory is the single place that knows how each model class is constructed,
so a backtest builds exactly the models the daily worker builds.
"""

import subprocess
import sys

import pytest

from shared.features import feature_count
from workers.daily.models import LinearRegressionModel
from workers.daily.models.factory import (
    MODEL_NAMES,
    build_model,
    model_class_for,
)


def test_the_linear_model_is_the_only_model_family() -> None:
    assert MODEL_NAMES == ("linear",)


@pytest.mark.parametrize("name", ["xgboost", "lstm", "arima"])
def test_removed_model_families_are_rejected(name: str) -> None:
    features = feature_count(21)

    with pytest.raises(ValueError, match=f"Unknown model '{name}'"):
        build_model(name, 21, features)


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


def test_linear_name_resolves_to_the_linear_class() -> None:
    model = build_model("linear", 21, feature_count(21))

    assert type(model) is model_class_for("linear")


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
