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
