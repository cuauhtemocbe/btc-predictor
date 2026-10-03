"""Validation and failure paths shared by ARIMA, XGBoost and LSTM (#159).

The three non-linear models repeat the same input checks and the same
serialization code, so each branch has one test parametrized over the classes
(``test_linear_validation.py`` does the same for the linear model). Nothing here
trains a model: the checks raise before any fit, and the corrupt-bytes cases
need no model at all, so the tests add no TensorFlow or statsmodels fit time.
"""

import pickle
from collections.abc import Callable

import numpy as np
import numpy.typing as npt
import pytest

from workers.daily.models.arima_model import ARIMAModel
from workers.daily.models.lstm_model import LSTMModel
from workers.daily.models.xgboost_model import XGBoostModel

WINDOW = 5
ROWS = 12

NonLinearModel = ARIMAModel | XGBoostModel | LSTMModel

FACTORIES: list[tuple[str, Callable[[], NonLinearModel], str]] = [
    # (id, constructor, attribute the pickled state holds the fitted object in)
    ("arima", lambda: ARIMAModel(order=(1, 0, 0), window_days=WINDOW), "fitted_model"),
    ("xgboost", lambda: XGBoostModel(window_days=WINDOW, n_estimators=2), "model"),
    ("lstm", lambda: LSTMModel(window_days=WINDOW, lstm_units=2, epochs=1), "model"),
]
MODEL_CLASSES: list[type[NonLinearModel]] = [ARIMAModel, XGBoostModel, LSTMModel]

on_every_model = pytest.mark.parametrize(
    "make_model", [pytest.param(f[1], id=f[0]) for f in FACTORIES]
)
on_every_class = pytest.mark.parametrize(
    "model_class", [pytest.param(c, id=c.__name__) for c in MODEL_CLASSES]
)


def _x(rows: int = ROWS) -> npt.NDArray[np.float64]:
    return np.random.default_rng(1).random((rows, WINDOW))


def _y(rows: int = ROWS) -> npt.NDArray[np.float64]:
    return np.random.default_rng(2).random(rows)


def _trained_flag(make_model: Callable[[], NonLinearModel]) -> NonLinearModel:
    """A model that passes the "is trained" check without being fitted."""
    model = make_model()
    model._is_trained = True
    return model


# ---- train ----------------------------------------------------------------


@on_every_model
def test_train_rejects_a_one_dimensional_x(
    make_model: Callable[[], NonLinearModel],
) -> None:
    with pytest.raises(ValueError, match="X must be 2-dimensional"):
        make_model().train(np.ones(ROWS), _y())


@on_every_model
def test_train_rejects_a_two_dimensional_y(
    make_model: Callable[[], NonLinearModel],
) -> None:
    with pytest.raises(ValueError, match="y must be 1-dimensional"):
        make_model().train(_x(), _y().reshape(-1, 1))


@on_every_model
@pytest.mark.parametrize(
    ("bad_value", "message"),
    [(np.nan, "y contains NaN"), (np.inf, "y contains infinite")],
)
def test_train_rejects_a_non_finite_y(
    make_model: Callable[[], NonLinearModel], bad_value: float, message: str
) -> None:
    y = _y()
    y[3] = bad_value

    with pytest.raises(ValueError, match=message):
        make_model().train(_x(), y)


# ---- predict --------------------------------------------------------------


@on_every_model
@pytest.mark.parametrize(
    ("shape", "message"),
    [
        ((WINDOW + 1,), "X must have 5 features, got 6"),
        ((2, WINDOW), r"X must have shape \(1, 5\)"),
        ((1, WINDOW + 1), "X must have 5 features, got 6"),
        ((1, WINDOW, 1), "X must be 1D or 2D, got 3 dimensions"),
    ],
)
def test_predict_rejects_the_wrong_shape(
    make_model: Callable[[], NonLinearModel], shape: tuple[int, ...], message: str
) -> None:
    model = _trained_flag(make_model)

    with pytest.raises(ValueError, match=message):
        model.predict(np.ones(shape))


@on_every_model
@pytest.mark.parametrize(
    ("bad_value", "message"),
    [(np.nan, "X contains NaN"), (np.inf, "X contains infinite")],
)
def test_predict_rejects_a_non_finite_x(
    make_model: Callable[[], NonLinearModel], bad_value: float, message: str
) -> None:
    model = _trained_flag(make_model)
    x = np.ones(WINDOW)
    x[0] = bad_value

    with pytest.raises(ValueError, match=message):
        model.predict(x)


# ---- serialize / deserialize ------------------------------------------------


@pytest.mark.parametrize(
    ("make_model", "state_attribute"),
    [pytest.param(f[1], f[2], id=f[0]) for f in FACTORIES],
)
def test_serialize_wraps_a_failure_in_a_runtime_error(
    make_model: Callable[[], NonLinearModel],
    state_attribute: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = make_model()
    # A lambda can neither be pickled nor asked for Keras weights
    monkeypatch.setattr(model, state_attribute, lambda: None)

    with pytest.raises(RuntimeError, match="Failed to serialize model"):
        model.serialize()


@on_every_class
def test_deserialize_rejects_bytes_that_are_not_a_pickle(
    model_class: type[NonLinearModel],
) -> None:
    with pytest.raises(pickle.UnpicklingError, match="Failed to unpickle model"):
        model_class.deserialize(b"definitely not a pickle")


@on_every_class
def test_deserialize_rejects_truncated_bytes(
    model_class: type[NonLinearModel],
) -> None:
    with pytest.raises(ValueError, match="Data is corrupted or invalid"):
        model_class.deserialize(b"")


@on_every_class
def test_deserialize_rejects_a_state_that_is_not_a_dict(
    model_class: type[NonLinearModel],
) -> None:
    with pytest.raises(ValueError, match="must be a dictionary"):
        model_class.deserialize(pickle.dumps([1, 2, 3]))


@on_every_class
def test_deserialize_rejects_a_state_with_missing_keys(
    model_class: type[NonLinearModel],
) -> None:
    with pytest.raises(ValueError, match="Missing required keys"):
        model_class.deserialize(pickle.dumps({"window_days": WINDOW}))
