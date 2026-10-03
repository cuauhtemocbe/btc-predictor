"""
Tests for scripts/simulate_history.py, the replay of the daily job over past days.

Covered: one settled daily prediction per run date built only from earlier bars,
the simulated mark on the models, the default range, and the refusals (existing
predictions, a range past the stored bars, too little history).
"""

import math
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

import scripts.simulate_history as simulate
from scripts.simulate_history import SimulationError, simulate_range
from shared.config import settings
from shared.db.models import Model, Prediction, Price

WINDOW = 5
FIRST_DAY = date(2023, 1, 1)
N_DAYS = 160


def close_of(index: int) -> Decimal:
    return Decimal(20000 + index * 10 + round(300 * math.sin(index)))


@pytest.fixture(autouse=True)
def small_window(monkeypatch):
    monkeypatch.setattr(settings, "training_window_days", WINDOW)


@pytest.fixture
def daily_prices(db_session):
    """N_DAYS closed daily bars starting at FIRST_DAY, stored at 00:00 UTC."""
    for index in range(N_DAYS):
        close = close_of(index)
        db_session.add(
            Price(
                timestamp=datetime.combine(
                    FIRST_DAY + timedelta(days=index), time(0, 0), tzinfo=UTC
                ),
                open=close,
                high=close + 50,
                low=close - 50,
                close=close,
                volume=Decimal(1000 + round(100 * math.cos(index))),
            )
        )
    db_session.commit()


def day_index(day: date) -> int:
    return (day - FIRST_DAY).days


LAST_DAY = FIRST_DAY + timedelta(days=N_DAYS - 1)


def stored_predictions(db_session) -> list[Prediction]:
    return db_session.query(Prediction).order_by(Prediction.predicted_for).all()


def test_stores_one_settled_prediction_per_run_date(db_session, daily_prices):
    start, end = LAST_DAY - timedelta(days=9), LAST_DAY

    stored = simulate_range(db_session, start, end)

    predictions = stored_predictions(db_session)
    assert stored == len(predictions) == 10
    assert [p.predicted_for for p in predictions] == [
        start + timedelta(days=offset + 1) for offset in range(10)
    ]
    assert all(p.timeframe == "1d" for p in predictions)
    assert all(p.actual_price is not None for p in predictions)
    assert all(p.direction_correct is not None for p in predictions)
    assert all(p.pnl_realistic is not None for p in predictions)


def test_a_run_date_only_sees_bars_before_it(db_session, daily_prices):
    run_date = LAST_DAY - timedelta(days=3)

    simulate_range(db_session, run_date, run_date)

    (prediction,) = stored_predictions(db_session)
    assert prediction.price_at_prediction == close_of(day_index(run_date) - 1)
    assert prediction.actual_price == close_of(day_index(run_date))
    assert prediction.predicted_for == run_date + timedelta(days=1)
    assert prediction.predicted_at == datetime.combine(
        run_date, time(simulate.PREDICTOR_HOUR_UTC, 0), tzinfo=UTC
    )


def test_models_are_marked_simulated_and_the_last_one_is_active(
    db_session, daily_prices
):
    simulate_range(db_session, LAST_DAY - timedelta(days=2), LAST_DAY)

    models = db_session.query(Model).order_by(Model.trained_at).all()
    assert len(models) == 3
    assert all(m.params["simulated"] is True for m in models)
    assert [m.is_active for m in models] == [False, False, True]
    assert models[-1].train_to == LAST_DAY - timedelta(days=1)


def test_keep_active_leaves_the_current_active_model_alone(db_session, daily_prices):
    real = Model(
        name=simulate.MODEL_NAME,
        version="real",
        params={"window_days": WINDOW},
        artifact=b"x",
        trained_at=datetime(2023, 1, 1, tzinfo=UTC),
        train_from=FIRST_DAY,
        train_to=FIRST_DAY,
        timeframe="1d",
        is_active=True,
    )
    db_session.add(real)
    db_session.commit()

    simulate_range(db_session, LAST_DAY - timedelta(days=2), LAST_DAY, keep_active=True)

    active = db_session.query(Model).filter(Model.is_active).all()
    assert [m.version for m in active] == ["real"]
    simulated = db_session.query(Model).filter(Model.version != "real").all()
    assert len(simulated) == 3
    assert all(m.params["simulated"] is True for m in simulated)


def test_default_range_is_the_last_31_stored_bars(db_session, daily_prices):
    stored = simulate_range(db_session)

    predictions = stored_predictions(db_session)
    assert stored == 31
    assert predictions[0].predicted_for == LAST_DAY - timedelta(days=30) + timedelta(
        days=1
    )
    assert predictions[-1].predicted_for == LAST_DAY + timedelta(days=1)


def test_refuses_a_range_that_already_has_predictions(db_session, daily_prices):
    start, end = LAST_DAY - timedelta(days=4), LAST_DAY
    simulate_range(db_session, start, end)
    before = len(stored_predictions(db_session))

    with pytest.raises(SimulationError, match="already exist"):
        simulate_range(db_session, start, end)

    assert len(stored_predictions(db_session)) == before


def test_refuses_an_end_past_the_last_stored_bar(db_session, daily_prices):
    with pytest.raises(SimulationError, match="past the last stored bar"):
        simulate_range(db_session, LAST_DAY, LAST_DAY + timedelta(days=1))

    assert stored_predictions(db_session) == []


def test_refuses_a_start_without_enough_history(db_session, daily_prices):
    with pytest.raises(SimulationError, match="daily rows before it"):
        simulate_range(db_session, FIRST_DAY + timedelta(days=10), LAST_DAY)

    assert stored_predictions(db_session) == []
    assert db_session.query(Model).count() == 0


def test_refuses_when_no_prices_are_loaded(db_session):
    with pytest.raises(SimulationError, match="No BTCUSDT prices"):
        simulate_range(db_session)


def test_main_returns_1_on_a_refusal(db_session, daily_prices, monkeypatch):
    monkeypatch.setattr(simulate, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    assert simulate.main(["--end", (LAST_DAY + timedelta(days=5)).isoformat()]) == 1
    assert simulate.main(["--start", (LAST_DAY - timedelta(days=2)).isoformat()]) == 0
