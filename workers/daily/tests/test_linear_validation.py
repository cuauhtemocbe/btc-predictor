"""Validation and failure paths of ``LinearRegressionModel``.

The linear model is the only one the crons run in production, so every input
check and every serialization failure has its own test (#68).
"""

import pickle

import numpy as np
import pytest

from workers.daily.models import LinearRegressionModel

WINDOW = 5


@pytest.fixture
def trained_model():
    rng = np.random.default_rng(7)
    model = LinearRegressionModel(window_days=WINDOW)
    model.train(rng.random((20, WINDOW)), rng.random(20))
    return model


@pytest.fixture
def untrained_model():
    return LinearRegressionModel(window_days=WINDOW)


def _x(rows: int = 10) -> np.ndarray:
    return np.random.default_rng(1).random((rows, WINDOW))


def test_train_rejects_a_one_dimensional_x(untrained_model):
    x = np.ones(WINDOW)
    y = np.ones(WINDOW)

    with pytest.raises(ValueError, match="X must be 2-dimensional"):
        untrained_model.train(x, y)


def test_train_rejects_a_two_dimensional_y(untrained_model):
    x = _x()
    y = np.ones((10, 1))

    with pytest.raises(ValueError, match="y must be 1-dimensional"):
        untrained_model.train(x, y)


@pytest.mark.parametrize(
    ("bad_value", "message"),
    [(np.nan, "y contains NaN"), (np.inf, "y contains infinite")],
)
def test_train_rejects_non_finite_targets(untrained_model, bad_value, message):
    x = _x()
    y = np.ones(10)
    y[3] = bad_value

    with pytest.raises(ValueError, match=message):
        untrained_model.train(x, y)


def test_predict_rejects_a_one_dimensional_x_of_the_wrong_length(trained_model):
    x = np.ones(3)

    with pytest.raises(ValueError, match=f"must have {WINDOW} features, got 3"):
        trained_model.predict(x)


def test_predict_rejects_a_three_dimensional_x(trained_model):
    x = np.ones((1, 1, WINDOW))

    with pytest.raises(ValueError, match="X must be 1D or 2D"):
        trained_model.predict(x)


@pytest.mark.parametrize(
    ("bad_value", "message"),
    [(np.nan, "X contains NaN"), (np.inf, "X contains infinite")],
)
def test_predict_rejects_non_finite_features(trained_model, bad_value, message):
    x = np.ones(WINDOW)
    x[0] = bad_value

    with pytest.raises(ValueError, match=message):
        trained_model.predict(x)


def test_serialize_wraps_a_pickling_failure(trained_model, monkeypatch):
    def broken_dumps(*_args, **_kwargs):
        raise TypeError("cannot pickle")

    monkeypatch.setattr(pickle, "dumps", broken_dumps)

    with pytest.raises(RuntimeError, match="Failed to serialize model"):
        trained_model.serialize()


def test_deserialize_turns_a_truncated_payload_into_a_value_error():
    with pytest.raises(ValueError, match="Data is corrupted or invalid"):
        LinearRegressionModel.deserialize(b"")


def test_deserialize_rejects_a_payload_that_is_not_a_dict():
    payload = pickle.dumps([1, 2, 3])

    with pytest.raises(ValueError, match="must be a dictionary"):
        LinearRegressionModel.deserialize(payload)
