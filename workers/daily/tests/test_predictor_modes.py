"""Tests for the single-model and multi-model paths of the predictor job."""

import logging
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.orm import Session

from shared.db.models import Model
from workers.daily import predictor
from workers.daily.models import BaseModel
from workers.daily.predictor import (
    PredictionOutcome,
    _exit_code,
    _log_prediction_summary,
    _predict_multi_model,
    _predict_single_model,
)

TOMORROW = date(2026, 1, 2)
PRICE = Decimal("50000")
# The fakes below never touch the session, so a missing one stands in for it.
NO_SESSION = cast(Session, None)

type ModelPairs = list[tuple[Model, BaseModel]]


def _models(*names: str) -> ModelPairs:
    return cast(ModelPairs, [(SimpleNamespace(name=name), object()) for name in names])


@pytest.fixture
def fake_predict_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the per-model work: models named 'bad*' fail, 'skip*' are skipped."""

    def fake(
        session: Session,
        model_record: Model,
        model_instance: BaseModel,
        tomorrow: date,
        current_price: Decimal,
        outcome: PredictionOutcome,
    ) -> None:
        name = model_record.name
        if name.startswith("bad"):
            raise ValueError(f"{name} exploded")
        if name.startswith("skip"):
            outcome.skipped.append(name)
            return
        outcome.generated.append((name, 51000.0))

    monkeypatch.setattr(predictor, "_predict_one", fake)


class TestPredictSingleModel:
    def test_records_the_generated_prediction(self, fake_predict_one: None) -> None:
        outcome = PredictionOutcome()

        _predict_single_model(
            NO_SESSION, _models("linear_v1"), TOMORROW, PRICE, outcome
        )

        assert outcome.generated == [("linear_v1", 51000.0)]
        assert outcome.failed == []

    def test_failure_is_recorded_logged_and_reraised(
        self, fake_predict_one: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        outcome = PredictionOutcome()
        models = _models("bad_v1")

        with (
            caplog.at_level(logging.ERROR),
            pytest.raises(ValueError, match="exploded"),
        ):
            _predict_single_model(NO_SESSION, models, TOMORROW, PRICE, outcome)

        assert outcome.failed == [("bad_v1", "bad_v1 exploded")]
        assert "Failed to generate prediction for bad_v1" in caplog.text


class TestPredictMultiModel:
    def test_failure_does_not_stop_the_other_models(
        self, fake_predict_one: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        outcome = PredictionOutcome()
        models = _models("linear_v1", "bad_v1", "skip_v1", "xgboost_v1")

        with caplog.at_level(logging.ERROR):
            _predict_multi_model(NO_SESSION, models, TOMORROW, PRICE, outcome)

        assert outcome.generated == [("linear_v1", 51000.0), ("xgboost_v1", 51000.0)]
        assert outcome.skipped == ["skip_v1"]
        assert outcome.failed == [("bad_v1", "bad_v1 exploded")]
        assert "Failed to generate prediction for bad_v1" in caplog.text


class TestExitCode:
    def test_zero_when_a_prediction_was_generated(self) -> None:
        outcome = PredictionOutcome(generated=[("linear_v1", 1.0)], failed=[("x", "e")])

        assert _exit_code(outcome) == 0

    def test_zero_when_every_prediction_already_existed(self) -> None:
        assert _exit_code(PredictionOutcome(skipped=["linear_v1"])) == 0

    def test_one_when_every_model_failed(self) -> None:
        assert _exit_code(PredictionOutcome(failed=[("linear_v1", "boom")])) == 1


def test_summary_lists_generated_skipped_and_failed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outcome = PredictionOutcome(
        generated=[("linear_v1", 51000.0)],
        skipped=["xgboost_v1"],
        failed=[("lstm_v1", "boom")],
    )

    with caplog.at_level(logging.INFO):
        _log_prediction_summary(TOMORROW, outcome)

    assert "Predictions for 2026-01-02" in caplog.text
    assert "linear_v1: $51,000.00" in caplog.text
    assert "Skipped (already exist): xgboost_v1" in caplog.text
    assert "Failed: 1 model(s)" in caplog.text
    assert "lstm_v1: boom" in caplog.text
