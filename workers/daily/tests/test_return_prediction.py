"""
Tests for the return-based daily prediction (#104).

Covers the Gherkin scenarios of "Return-based next-day prediction" that involve the
trainer and the predictor: the stored price comes from the predicted return, both
sides use the same feature builder with the same window, and the Linear model trains
on returns and predicts a finite next day. The builder-level scenarios are in
shared/tests/test_features.py.
"""

import math
from argparse import Namespace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import numpy as np
import pytest
from sqlalchemy.orm import Session

from shared import features
from shared.db.models import Model, Prediction, Price
from workers.daily import predictor, trainer
from workers.daily.models import LinearRegressionModel

THREE_YEARS = 3 * 365


def _add_random_walk(session: Session, days: int, last_close: float = 84000) -> None:
    """Daily BTCUSDT bars ending yesterday; the last close is ``last_close``."""
    rng = np.random.default_rng(11)
    closes = np.exp(np.cumsum(rng.normal(0, 0.02, days)))
    closes = last_close * closes / closes[-1]
    volumes = 1000 * np.exp(rng.normal(0, 0.2, days))
    first_day = date.today() - timedelta(days=days)
    session.add_all(
        Price(
            symbol="BTCUSDT",
            timestamp=datetime.combine(
                first_day + timedelta(days=i), time(0, 0), tzinfo=UTC
            ),
            open=Decimal(str(round(closes[i], 2))),
            high=Decimal(str(round(closes[i], 2))),
            low=Decimal(str(round(closes[i], 2))),
            close=Decimal(str(round(closes[i], 2))),
            volume=Decimal(str(round(volumes[i], 4))),
            source="test",
        )
        for i in range(days)
    )
    session.commit()


@pytest.fixture
def use_session(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    """The trainer and predictor open their own session; hand them the test one."""
    monkeypatch.setattr(trainer, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(predictor, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(predictor, "parse_args", lambda: Namespace(multi_model=False))
    return db_session


class TestLinearModelTrainsOnReturns:
    """Scenario: train the Linear model on 3 years of daily returns."""

    def test_trainer_then_predictor_gives_a_finite_prediction(
        self, use_session: Session
    ) -> None:
        _add_random_walk(use_session, THREE_YEARS)

        assert trainer.main() == 0
        assert predictor.main() == 0

        prediction = use_session.query(Prediction).one()
        assert math.isfinite(float(prediction.predicted_price))
        assert prediction.predicted_price > 0

    def test_the_stored_model_is_marked_as_a_log_return_model(
        self, use_session: Session
    ) -> None:
        _add_random_walk(use_session, THREE_YEARS)

        assert trainer.main() == 0

        model = use_session.query(Model).one()
        assert model.params["target"] == "log_return"
        assert model.params["window_days"] == 21
        assert model.params["horizon_days"] == 1
        restored = LinearRegressionModel.deserialize(model.artifact)
        assert restored.n_features == features.feature_count(21)

    def test_trainer_feeds_return_features_not_price_levels(
        self, use_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _add_random_walk(use_session, 300)
        seen: dict[str, np.ndarray] = {}
        original_train = LinearRegressionModel.train

        def spy(self, X, y):  # noqa: ANN001, ANN202
            seen["X"], seen["y"] = X, y
            return original_train(self, X, y)

        monkeypatch.setattr(LinearRegressionModel, "train", spy)

        assert trainer.main() == 0

        # Prices are around 84000; return features and targets are tiny
        assert np.abs(seen["X"]).max() < 5
        assert np.abs(seen["y"]).max() < 0.5


class TestStoredPriceComesFromThePredictedReturn:
    """Scenario: last close 84000, predicted return +1%."""

    def test_predicted_price_is_last_close_times_exp_of_the_return(
        self, use_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _add_random_walk(use_session, 300, last_close=84000)
        assert trainer.main() == 0
        monkeypatch.setattr(LinearRegressionModel, "predict", lambda self, X: 0.01)

        assert predictor.main() == 0

        prediction = use_session.query(Prediction).one()
        assert prediction.price_at_prediction == Decimal("84000")
        assert float(prediction.predicted_price) == pytest.approx(
            84000 * math.exp(0.01)
        )
        assert prediction.predicted_price > prediction.price_at_prediction  # up

    def test_a_negative_return_is_a_down_prediction(
        self, use_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _add_random_walk(use_session, 300, last_close=84000)
        assert trainer.main() == 0
        monkeypatch.setattr(LinearRegressionModel, "predict", lambda self, X: -0.02)

        assert predictor.main() == 0

        prediction = use_session.query(Prediction).one()
        assert float(prediction.predicted_price) == pytest.approx(
            84000 * math.exp(-0.02)
        )
        assert prediction.predicted_price < prediction.price_at_prediction  # down

    def test_a_price_level_model_is_rejected(self, use_session: Session) -> None:
        _add_random_walk(use_session, 300)
        assert trainer.main() == 0
        model = use_session.query(Model).one()
        model.params = {"window_days": 21}  # as stored before #104
        use_session.commit()

        assert predictor.main() == 1
        assert use_session.query(Prediction).count() == 0


class TestTrainingAndPredictionUseTheSameBuilder:
    """Scenario: both sides call the same feature builder with the same window."""

    def test_both_call_the_same_feature_core_with_the_same_window(
        self, use_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _add_random_walk(use_session, 300)
        windows: list[tuple[str, int]] = []
        original = features._feature_matrix
        stage = {"name": "train"}

        def spy(closes, volumes, window_days):  # noqa: ANN001, ANN202
            windows.append((stage["name"], window_days))
            return original(closes, volumes, window_days)

        monkeypatch.setattr(features, "_feature_matrix", spy)

        assert trainer.main() == 0
        stage["name"] = "predict"
        assert predictor.main() == 0

        assert windows == [("train", 21), ("predict", 21)]

    def test_prediction_features_equal_the_last_training_row(
        self, use_session: Session
    ) -> None:
        _add_random_walk(use_session, 300)
        series = trainer.fetch_training_data(use_session, window_days=21)

        # A series with one more day: its second-to-last training row is the
        # prediction row of the original series.
        extended_closes = [*series.closes, series.closes[-1]]
        extended_volumes = [*series.volumes, series.volumes[-1]]
        training = features.build_training_set(extended_closes, extended_volumes, 21)

        X = predictor.prepare_features(series, 21)

        assert np.array_equal(X[0], training.X[-1])
