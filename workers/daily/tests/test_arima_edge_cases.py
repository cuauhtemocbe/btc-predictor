"""ARIMA-only branches that the shared non-linear tests do not reach (#159)."""

import importlib
import sys

import numpy as np
import pandas as pd
import pytest

from workers.daily.models import arima_model
from workers.daily.models.arima_model import ARIMAModel, _first_forecast


def test_seasonal_order_rejects_a_negative_value() -> None:
    with pytest.raises(ValueError, match="seasonal_order values must be >= 0"):
        ARIMAModel(seasonal_order=(0, 0, 0, -1))


def test_train_turns_a_convergence_failure_into_a_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_arima(*args: object, **kwargs: object) -> None:
        raise RuntimeError("did not converge")

    monkeypatch.setattr(arima_model, "ARIMA", failing_arima)
    model = ARIMAModel(order=(1, 0, 0), window_days=5)
    rng = np.random.default_rng(3)

    with pytest.raises(ValueError, match="ARIMA model failed to converge"):
        model.train(rng.random((12, 5)), rng.random(12))

    assert not model.is_trained


def test_first_forecast_reads_a_series_by_position() -> None:
    series = pd.Series([0.25, 0.5], index=[10, 11])

    assert _first_forecast(series) == 0.25


def test_first_forecast_reads_the_first_item_of_an_array() -> None:
    assert _first_forecast(np.array([0.75, 1.0])) == 0.75


def test_a_missing_statsmodels_raises_an_actionable_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A None entry makes the import fail. The reload stops at the guard, before
    # the module body redefines ARIMAModel, so the classes other tests hold stay
    # valid.
    monkeypatch.setitem(sys.modules, "statsmodels.tsa.arima.model", None)

    with pytest.raises(ImportError, match="Statsmodels is required for ARIMAModel"):
        importlib.reload(arima_model)
