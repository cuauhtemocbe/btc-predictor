"""
Tests for the walk-forward engine (#106).

Gherkin scenarios of "Walk-forward backtest with production parity" covered here:
no future data reaches training, production feature/model code is used, one result
per day, and a start without enough history fails clearly. The behaviours the
engine inherits from the previous backtest (four PnL strategies, unique run id,
skipped days, stored parameters, progress logging) keep their tests here too.
"""

import logging
from datetime import date, timedelta
from uuid import uuid4

import pytest

import scripts.backtest_engine as engine
import shared.features as features
from scripts.backtest_engine import (
    BacktestConfig,
    InsufficientHistoryError,
)
from shared.config import settings
from shared.db.models import BacktestResult
from shared.utils import calculate_pnl, calculate_pnl_long_short
from workers.daily.models import factory
from workers.daily.trainer import required_training_days

WINDOW = 5
FIRST_DAY = date(2023, 1, 1)


def config(start: date, end: date, **overrides) -> BacktestConfig:
    return BacktestConfig(
        model_name=overrides.pop("model_name", "linear"),
        window_days=overrides.pop("window_days", WINDOW),
        start_date=start,
        end_date=end,
        **overrides,
    )


def stored(db_session, run_id) -> list[BacktestResult]:
    return (
        db_session.query(BacktestResult)
        .filter_by(backtest_run_id=run_id)
        .order_by(BacktestResult.predicted_for)
        .all()
    )


# --- Scenario: No future data reaches training ---


def test_training_set_ends_before_predicted_day(db_session, seeded_prices, monkeypatch):
    # Given a backtest predicting 2024-06-10
    target = date(2024, 6, 10)
    by_day = {day: (close, volume) for day, close, volume in seeded_prices}
    seen: list[tuple[list, list]] = []
    real = engine.build_training_set

    def spy(closes, volumes, window_days, horizon_days=1):
        seen.append((list(closes), list(volumes)))
        return real(closes, volumes, window_days, horizon_days)

    monkeypatch.setattr(engine, "build_training_set", spy)

    # When the training set is built
    engine.run_walk_forward(db_session, config(target, target), uuid4())

    # Then its latest observation is dated 2024-06-09 or earlier
    ((closes, volumes),) = seen
    last_allowed = target - timedelta(days=1)
    assert closes[-1] == by_day[last_allowed][0]
    assert volumes[-1] == by_day[last_allowed][1]
    assert by_day[target][0] not in closes, "the predicted day's close leaked"
    assert len(closes) == (last_allowed - FIRST_DAY).days + 1


def test_every_prediction_uses_only_strictly_earlier_closes(
    db_session, seeded_prices, monkeypatch
):
    by_close = {close: day for day, close, _ in seeded_prices}
    calls: list[tuple[date, date]] = []
    real = engine.build_prediction_features

    def spy(closes, volumes, window_days):
        calls.append((by_close[closes[-1]], by_close[closes[0]]))
        return real(closes, volumes, window_days)

    monkeypatch.setattr(engine, "build_prediction_features", spy)
    start, end = date(2024, 3, 1), date(2024, 3, 10)

    engine.run_walk_forward(db_session, config(start, end), uuid4())

    assert [last for last, _ in calls] == [
        start + timedelta(days=i - 1) for i in range((end - start).days + 1)
    ]


# --- Scenario: The backtest uses the production feature and prediction code ---


def test_backtest_uses_the_production_builders_and_factory():
    assert engine.build_training_set is features.build_training_set
    assert engine.build_prediction_features is features.build_prediction_features
    assert engine.price_from_return is features.price_from_return
    assert engine.build_model is factory.build_model


def test_backtest_calls_production_builders_and_factory(
    db_session, seeded_prices, monkeypatch
):
    calls = {"training": 0, "prediction": 0, "factory": 0, "price": 0}

    def counted(name, real):
        def wrapper(*args, **kwargs):
            calls[name] += 1
            return real(*args, **kwargs)

        return wrapper

    for attribute, name in [
        ("build_training_set", "training"),
        ("build_prediction_features", "prediction"),
        ("build_model", "factory"),
        ("price_from_return", "price"),
    ]:
        monkeypatch.setattr(
            engine, attribute, counted(name, getattr(engine, attribute))
        )

    # When a backtest predicts a day
    engine.run_walk_forward(
        db_session, config(date(2024, 6, 10), date(2024, 6, 10)), uuid4()
    )

    # Then it calls the same feature builder and model classes as the daily worker
    assert calls == {"training": 1, "prediction": 1, "factory": 1, "price": 1}


def test_stored_prediction_is_last_close_times_exp_of_the_predicted_return(
    db_session, seeded_prices
):
    import math

    run_id = uuid4()
    day = date(2024, 6, 10)
    by_day = {d: close for d, close, _ in seeded_prices}
    engine.run_walk_forward(db_session, config(day, day), run_id)

    (row,) = stored(db_session, run_id)

    implied_return = math.log(
        float(row.predicted_price) / float(by_day[day - timedelta(days=1)])
    )
    assert abs(implied_return) < 0.2, (
        "a return-based prediction stays near the last close"
    )
    assert row.price_at_prediction == by_day[day - timedelta(days=1)]
    assert row.actual_price == by_day[day]


# --- Scenario Outline: Every model type can be backtested (linear row) ---


def test_one_result_is_stored_per_day_for_linear(db_session, seeded_prices):
    # Given the "linear" model, when I backtest 2024-01-01 to 2024-03-31
    run_id = uuid4()
    start, end = date(2024, 1, 1), date(2024, 3, 31)

    stats = engine.run_walk_forward(db_session, config(start, end), run_id)

    # Then one result per day is stored in backtest_results
    rows = stored(db_session, run_id)
    assert [r.predicted_for for r in rows] == [
        start + timedelta(days=i) for i in range((end - start).days + 1)
    ]
    assert stats.predictions == 91
    assert stats.total_days == 91


# --- Scenario: A date range without enough history fails clearly ---


def test_start_before_enough_history_names_earliest_date(db_session, seeded_prices):
    needed = required_training_days(WINDOW)
    earliest = FIRST_DAY + timedelta(days=needed)

    # Given a start date earlier than the first loaded day plus the window
    too_early = earliest - timedelta(days=1)

    # When I run the backtest, then it fails with the earliest allowed start date
    with pytest.raises(InsufficientHistoryError) as error:
        engine.run_walk_forward(
            db_session, config(too_early, too_early + timedelta(days=5)), uuid4()
        )

    message = str(error.value)
    assert str(earliest) in message
    assert str(FIRST_DAY) in message
    assert f"window={WINDOW}d" in message
    assert db_session.query(BacktestResult).count() == 0


def test_the_earliest_allowed_start_date_works(db_session, seeded_prices):
    earliest = FIRST_DAY + timedelta(days=required_training_days(WINDOW))
    run_id = uuid4()

    engine.run_walk_forward(db_session, config(earliest, earliest), run_id)

    assert len(stored(db_session, run_id)) == 1


def test_empty_price_table_fails_clearly(db_session):
    with pytest.raises(InsufficientHistoryError, match="No BTCUSDT prices"):
        engine.run_walk_forward(
            db_session, config(date(2024, 1, 1), date(2024, 1, 2)), uuid4()
        )


# --- Behaviours inherited from the previous backtest ---


def test_all_four_pnl_strategies_are_stored(db_session, seeded_prices):
    run_id = uuid4()
    day = date(2024, 6, 10)
    engine.run_walk_forward(db_session, config(day, day), run_id)

    (row,) = stored(db_session, run_id)

    assert row.pnl_simple == calculate_pnl(
        row.predicted_price, row.price_at_prediction, row.actual_price
    )
    assert row.pnl_long_short == calculate_pnl_long_short(
        row.predicted_price, row.price_at_prediction, row.actual_price
    )
    assert row.pnl_threshold is not None
    assert row.pnl_realistic is not None


def test_each_run_has_its_own_id(db_session, seeded_prices):
    first, second = uuid4(), uuid4()
    day = date(2024, 6, 10)

    engine.run_walk_forward(db_session, config(day, day), first)
    engine.run_walk_forward(db_session, config(day, day), second)

    assert len(stored(db_session, first)) == 1
    assert len(stored(db_session, second)) == 1


def test_days_without_an_actual_price_are_skipped_and_counted(
    db_session, seeded_prices
):
    last_loaded = FIRST_DAY + timedelta(days=len(seeded_prices) - 1)
    run_id = uuid4()

    stats = engine.run_walk_forward(
        db_session,
        config(last_loaded - timedelta(days=2), last_loaded + timedelta(days=3)),
        run_id,
    )

    assert stats.predictions == 3
    assert stats.skipped_no_actual == 3
    assert stats.total_days == 6
    assert len(stored(db_session, run_id)) == 3


def test_model_parameters_are_stored_for_reproducibility(db_session, seeded_prices):
    run_id = uuid4()
    day = date(2024, 6, 10)
    engine.run_walk_forward(db_session, config(day, day), run_id)

    (row,) = stored(db_session, run_id)

    assert row.model_params["model_name"] == "linear"
    assert row.model_params["window_days"] == WINDOW
    assert row.model_params["target"] == features.LOG_RETURN_TARGET
    assert row.model_params["train_to"] == "2024-06-09"
    assert row.predicted_at.date() == date(2024, 6, 9)


def test_progress_is_logged_every_ten_days(db_session, seeded_prices, caplog):
    caplog.set_level(logging.INFO, logger="scripts.backtest_engine")

    engine.run_walk_forward(
        db_session, config(date(2024, 6, 1), date(2024, 6, 25)), uuid4()
    )

    progress = [r.message for r in caplog.records if "Backtesting day" in r.message]
    assert len(progress) == 2  # days 10 and 20


def test_default_window_is_the_production_window():
    assert BacktestConfig.default_window() == settings.training_window_days


def test_start_must_not_be_after_end(db_session, seeded_prices):
    with pytest.raises(ValueError, match="start.*before.*end"):
        engine.run_walk_forward(
            db_session, config(date(2024, 6, 10), date(2024, 6, 9)), uuid4()
        )


def test_unknown_model_name_fails_before_writing(db_session, seeded_prices):
    with pytest.raises(ValueError, match="Unknown model"):
        engine.run_walk_forward(
            db_session,
            config(date(2024, 6, 10), date(2024, 6, 10), model_name="prophet"),
            uuid4(),
        )
    assert db_session.query(BacktestResult).count() == 0


def test_nothing_is_written_when_a_day_fails_midway(
    db_session, seeded_prices, monkeypatch
):
    calls = {"n": 0}
    real = engine.build_prediction_features

    def explode_on_third_day(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(engine, "build_prediction_features", explode_on_third_day)

    with pytest.raises(RuntimeError):
        engine.run_walk_forward(
            db_session, config(date(2024, 6, 1), date(2024, 6, 10)), uuid4()
        )

    assert db_session.query(BacktestResult).count() == 0


def test_a_day_whose_training_fails_is_skipped_and_counted(
    db_session, seeded_prices, monkeypatch
):
    real = engine.build_training_set

    def fail_on_one_day(closes, volumes, window_days, horizon_days=1):
        if len(closes) == (date(2024, 6, 3) - FIRST_DAY).days:  # predicting 06-03
            raise ValueError("bad data")
        return real(closes, volumes, window_days, horizon_days)

    monkeypatch.setattr(engine, "build_training_set", fail_on_one_day)
    run_id = uuid4()

    stats = engine.run_walk_forward(
        db_session, config(date(2024, 6, 1), date(2024, 6, 5)), run_id
    )

    assert stats.skipped_training_failed == 1
    assert stats.predictions == 4
    assert date(2024, 6, 3) not in [r.predicted_for for r in stored(db_session, run_id)]


# --- Scenario: Results are reproducible ---


class NoisyModel:
    """A model whose output depends on the global RNGs, to prove the engine seeds."""

    def train(self, X, y):
        import random

        import numpy as np

        self.offset = float(np.random.normal(0, 0.01)) + random.random() * 0.01

    def predict(self, X):
        return self.offset


def predicted_prices(db_session, run_id) -> list:
    return [row.predicted_price for row in stored(db_session, run_id)]


def test_same_seed_same_predictions(db_session, seeded_prices, monkeypatch):
    # Given a fixed random seed, when I run the same backtest twice
    monkeypatch.setattr(engine, "build_model", lambda *args: NoisyModel())
    first, second = uuid4(), uuid4()
    days = (date(2024, 6, 1), date(2024, 6, 10))

    engine.run_walk_forward(db_session, config(*days, seed=7), first)
    engine.run_walk_forward(db_session, config(*days, seed=7), second)

    # Then both runs store identical predictions
    assert predicted_prices(db_session, first) == predicted_prices(db_session, second)
    assert len(set(predicted_prices(db_session, first))) > 1


def test_a_different_seed_changes_a_seed_dependent_model(
    db_session, seeded_prices, monkeypatch
):
    monkeypatch.setattr(engine, "build_model", lambda *args: NoisyModel())
    first, second = uuid4(), uuid4()
    days = (date(2024, 6, 1), date(2024, 6, 10))

    engine.run_walk_forward(db_session, config(*days, seed=7), first)
    engine.run_walk_forward(db_session, config(*days, seed=8), second)

    assert predicted_prices(db_session, first) != predicted_prices(db_session, second)


def test_linear_runs_are_identical_with_the_default_seed(db_session, seeded_prices):
    first, second = uuid4(), uuid4()
    days = (date(2024, 6, 1), date(2024, 6, 20))

    engine.run_walk_forward(db_session, config(*days), first)
    engine.run_walk_forward(db_session, config(*days), second)

    assert predicted_prices(db_session, first) == predicted_prices(db_session, second)


def test_the_seed_is_stored_with_every_result(db_session, seeded_prices):
    run_id = uuid4()
    engine.run_walk_forward(
        db_session, config(date(2024, 6, 1), date(2024, 6, 3), seed=123), run_id
    )

    assert {r.model_params["seed"] for r in stored(db_session, run_id)} == {123}


def test_the_default_seed_is_42():
    assert config(date(2024, 6, 1), date(2024, 6, 2)).seed == 42


# --- Retrain frequency ---


def count_trainings(monkeypatch) -> list[int]:
    trained_on: list[int] = []
    real = engine.build_training_set

    def spy(closes, volumes, window_days, horizon_days=1):
        trained_on.append(len(closes))
        return real(closes, volumes, window_days, horizon_days)

    monkeypatch.setattr(engine, "build_training_set", spy)
    return trained_on


def test_retrain_every_n_days_trains_on_day_0_n_2n(
    db_session, seeded_prices, monkeypatch
):
    trained_on = count_trainings(monkeypatch)
    start = date(2024, 6, 1)

    engine.run_walk_forward(
        db_session, config(start, date(2024, 6, 10), retrain_every=3), uuid4()
    )

    first = (start - FIRST_DAY).days  # rows before the first predicted day
    assert trained_on == [first, first + 3, first + 6, first + 9]


def test_retrain_every_defaults_to_every_day(db_session, seeded_prices, monkeypatch):
    trained_on = count_trainings(monkeypatch)

    engine.run_walk_forward(
        db_session, config(date(2024, 6, 1), date(2024, 6, 5)), uuid4()
    )

    assert len(trained_on) == 5


def test_reused_model_still_predicts_from_data_before_each_day(
    db_session, seeded_prices, monkeypatch
):
    by_close = {close: day for day, close, _ in seeded_prices}
    last_closes: list[date] = []
    real = engine.build_prediction_features

    def spy(closes, volumes, window_days):
        last_closes.append(by_close[closes[-1]])
        return real(closes, volumes, window_days)

    monkeypatch.setattr(engine, "build_prediction_features", spy)
    start = date(2024, 6, 1)

    engine.run_walk_forward(
        db_session, config(start, date(2024, 6, 8), retrain_every=5), uuid4()
    )

    assert last_closes == [start + timedelta(days=i - 1) for i in range(8)]


def test_stored_params_say_how_often_the_model_was_retrained_and_on_what_data(
    db_session, seeded_prices
):
    run_id = uuid4()
    start = date(2024, 6, 1)

    engine.run_walk_forward(
        db_session, config(start, date(2024, 6, 7), retrain_every=3), run_id
    )

    rows = stored(db_session, run_id)
    assert {r.model_params["retrain_every"] for r in rows} == {3}
    train_to = [r.model_params["train_to"] for r in rows]
    assert train_to == ["2024-05-31"] * 3 + ["2024-06-03"] * 3 + ["2024-06-06"]
    for row in rows:  # a reused model never saw the day it predicts
        assert date.fromisoformat(row.model_params["train_to"]) < row.predicted_for


def test_a_failed_training_is_retried_the_next_day(
    db_session, seeded_prices, monkeypatch
):
    real = engine.build_training_set
    calls = {"n": 0}

    def fail_first(closes, volumes, window_days, horizon_days=1):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("bad data")
        return real(closes, volumes, window_days, horizon_days)

    monkeypatch.setattr(engine, "build_training_set", fail_first)

    stats = engine.run_walk_forward(
        db_session,
        config(date(2024, 6, 1), date(2024, 6, 4), retrain_every=10),
        uuid4(),
    )

    assert stats.skipped_training_failed == 1
    assert stats.predictions == 3


@pytest.mark.parametrize("retrain_every", [0, -1])
def test_retrain_every_must_be_positive(db_session, seeded_prices, retrain_every):
    with pytest.raises(ValueError, match="retrain_every must be >= 1"):
        engine.run_walk_forward(
            db_session,
            config(date(2024, 6, 1), date(2024, 6, 2), retrain_every=retrain_every),
            uuid4(),
        )


# --- Validation / test split ---


def slices(db_session, run_id) -> dict[date, str | None]:
    return {r.predicted_for: r.evaluation_slice for r in stored(db_session, run_id)}


def test_the_last_30_percent_of_the_range_is_the_default_test_slice(
    db_session, seeded_prices
):
    run_id = uuid4()

    engine.run_walk_forward(
        db_session, config(date(2024, 6, 1), date(2024, 6, 10)), run_id
    )

    labels = slices(db_session, run_id)
    assert [d.day for d, s in labels.items() if s == "validation"] == list(range(1, 8))
    assert [d.day for d, s in labels.items() if s == "test"] == [8, 9, 10]


def test_an_explicit_test_start_date_splits_the_range(db_session, seeded_prices):
    run_id = uuid4()

    engine.run_walk_forward(
        db_session,
        config(date(2024, 6, 1), date(2024, 6, 10), test_start_date=date(2024, 6, 5)),
        run_id,
    )

    labels = slices(db_session, run_id)
    assert {d: s for d, s in labels.items() if d < date(2024, 6, 5)} == {
        date(2024, 6, d): "validation" for d in range(1, 5)
    }
    assert {s for d, s in labels.items() if d >= date(2024, 6, 5)} == {"test"}


def test_a_test_start_on_the_first_day_leaves_no_validation_rows(
    db_session, seeded_prices
):
    run_id = uuid4()

    engine.run_walk_forward(
        db_session,
        config(date(2024, 6, 1), date(2024, 6, 5), test_start_date=date(2024, 6, 1)),
        run_id,
    )

    assert set(slices(db_session, run_id).values()) == {"test"}


def test_a_one_day_range_is_all_test(db_session, seeded_prices):
    run_id = uuid4()

    engine.run_walk_forward(
        db_session, config(date(2024, 6, 10), date(2024, 6, 10)), run_id
    )

    assert set(slices(db_session, run_id).values()) == {"test"}


@pytest.mark.parametrize("test_start", [date(2024, 5, 31), date(2024, 6, 11)])
def test_a_test_start_outside_the_range_is_rejected_before_writing(
    db_session, seeded_prices, test_start
):
    with pytest.raises(ValueError, match="test start date.*within"):
        engine.run_walk_forward(
            db_session,
            config(date(2024, 6, 1), date(2024, 6, 10), test_start_date=test_start),
            uuid4(),
        )
    assert db_session.query(BacktestResult).count() == 0


def test_the_test_start_date_is_stored_with_every_result(db_session, seeded_prices):
    run_id = uuid4()

    engine.run_walk_forward(
        db_session, config(date(2024, 6, 1), date(2024, 6, 10)), run_id
    )

    assert {r.model_params["test_start_date"] for r in stored(db_session, run_id)} == {
        "2024-06-08"
    }
