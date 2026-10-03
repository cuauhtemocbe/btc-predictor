"""
Baselines of stored models and the symbol filter of the shared metric queries (#107).
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from btc_shared.strategies import get_all_strategies_metrics
from shared.baselines import BaselineReport
from shared.db.crud import get_evaluated_predictions
from shared.db.models import Model, Prediction, Price
from shared.model_baselines import (
    BEATS,
    INCONCLUSIVE,
    NOT_BEATING,
    daily_closes,
    get_model_baseline,
    verdict,
)
from shared.utils import get_all_models_metrics

FIRST_DAY = date(2026, 1, 1)


def _at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _model(db: Session, symbol: str) -> Model:
    model = Model(
        symbol=symbol,
        name="linear_v1",
        version="1.0.0",
        params={},
        artifact=b"x",
        trained_at=_at(FIRST_DAY),
        train_from=FIRST_DAY,
        train_to=FIRST_DAY,
        is_active=True,
    )
    db.add(model)
    db.flush()
    return model


def _prices(
    db: Session, symbol: str, closes: list[float], start_index: int = 0
) -> None:
    for index, close in enumerate(closes, start=start_index):
        value = Decimal(str(close))
        db.add(
            Price(
                symbol=symbol,
                timestamp=_at(FIRST_DAY + timedelta(days=index)),
                open=value,
                high=value,
                low=value,
                close=value,
                volume=Decimal("1"),
                source="test",
            )
        )
    db.flush()


def _evaluate(
    db: Session,
    model: Model,
    closes: list[float],
    predicts_up: list[bool],
    start_index: int = 2,
    timeframe: str = "1d",
) -> None:
    for offset, index in enumerate(range(start_index, len(closes))):
        price_at = Decimal(str(closes[index - 1]))
        actual = Decimal(str(closes[index]))
        up = predicts_up[offset]
        day = FIRST_DAY + timedelta(days=index)
        db.add(
            Prediction(
                model_id=model.id,
                predicted_for=day,
                timeframe=timeframe,
                predicted_at=_at(day),
                price_at_prediction=price_at,
                predicted_price=price_at + (1 if up else -1),
                actual_price=actual,
                evaluated_at=_at(day),
                error_abs=Decimal("1"),
                error_pct=Decimal("1"),
                direction_correct=(up == (actual >= price_at)),
                pnl_simulated=Decimal("1"),
            )
        )
    db.flush()


def _report(edge: float | None, significant: bool | None) -> BaselineReport:
    return BaselineReport(
        n_days=10,
        always_up_accuracy=0.5,
        persistence_accuracy=0.5,
        persistence_n_days=10,
        always_up_pnl=None,
        persistence_pnl=None,
        buy_and_hold_pnl=None,
        best_baseline="always_up",
        model_accuracy=None,
        edge=edge,
        p_value=None,
        significant=significant,
    )


@pytest.mark.parametrize(
    ("edge", "significant", "expected"),
    [
        (0.3, True, BEATS),
        (0.3, False, INCONCLUSIVE),
        (0.0, False, NOT_BEATING),
        (-0.2, False, NOT_BEATING),
        (None, None, None),
    ],
)
def test_verdict(
    edge: float | None, significant: bool | None, expected: str | None
) -> None:
    assert verdict(_report(edge, significant)) == expected


def test_equal_to_the_baseline_is_not_beating_it() -> None:
    """Even a 'significant' tie (impossible by construction) is not a win."""
    assert verdict(_report(0.0, True)) == NOT_BEATING


def test_baseline_covers_exactly_the_models_evaluated_days(db_session: Session) -> None:
    """Alternating 100/110 closes: always-up 50%, persistence 0%, model 100%."""
    closes = [100.0 if i % 2 == 0 else 110.0 for i in range(12)]
    model = _model(db_session, "BTCUSDT")
    _prices(db_session, "BTCUSDT", closes)
    _evaluate(db_session, model, closes, [i % 2 == 1 for i in range(2, 12)])

    baseline = get_model_baseline(db_session, model.id, "BTCUSDT", timeframe="1d")

    assert baseline is not None
    assert baseline["n_days"] == 10
    assert baseline["always_up_accuracy"] == 0.5
    assert baseline["persistence_accuracy"] == 0.0
    assert baseline["persistence_n_days"] == 10
    assert baseline["edge"] == pytest.approx(0.5)
    assert baseline["verdict"] == BEATS


def test_baseline_respects_the_date_filters(db_session: Session) -> None:
    closes = [100.0 + i for i in range(12)]
    model = _model(db_session, "BTCUSDT")
    _prices(db_session, "BTCUSDT", closes)
    _evaluate(db_session, model, closes, [True] * 10)

    baseline = get_model_baseline(
        db_session,
        model.id,
        "BTCUSDT",
        start_date=FIRST_DAY + timedelta(days=4),
        end_date=FIRST_DAY + timedelta(days=7),
        timeframe="1d",
    )

    assert baseline is not None
    assert baseline["n_days"] == 4


def test_persistence_skips_days_without_a_stored_previous_close(
    db_session: Session,
) -> None:
    """Prices only exist from day 5: earlier days score always-up, not persistence."""
    closes = [100.0 + i for i in range(12)]
    model = _model(db_session, "BTCUSDT")
    _evaluate(db_session, model, closes, [True] * 10)
    _prices(db_session, "BTCUSDT", closes[5:], start_index=5)  # last 7 closes only

    baseline = get_model_baseline(db_session, model.id, "BTCUSDT", timeframe="1d")

    assert baseline is not None
    assert baseline["n_days"] == 10
    assert baseline["persistence_n_days"] == 5  # days 7..11 have a stored D-2


def test_previous_close_comes_from_the_models_own_symbol(db_session: Session) -> None:
    """Gold prices must not feed the BTC persistence baseline."""
    btc_closes = [100.0 + i for i in range(6)]  # rising: persistence is right
    gold_closes = [200.0 - i for i in range(6)]  # falling: persistence would be wrong
    model = _model(db_session, "BTCUSDT")
    _prices(db_session, "BTCUSDT", btc_closes)
    _prices(db_session, "PAXGUSDT", gold_closes)
    _evaluate(db_session, model, btc_closes, [True] * 4)

    baseline = get_model_baseline(db_session, model.id, "BTCUSDT", timeframe="1d")

    assert baseline is not None
    assert baseline["persistence_accuracy"] == 1.0


@pytest.mark.parametrize("timeframe", ["1w", "1h", None])
def test_baseline_is_unavailable_outside_the_daily_timeframe(
    db_session: Session, timeframe: str | None
) -> None:
    closes = [100.0 + i for i in range(8)]
    model = _model(db_session, "BTCUSDT")
    _prices(db_session, "BTCUSDT", closes)
    _evaluate(db_session, model, closes, [True] * 6)

    assert (
        get_model_baseline(db_session, model.id, "BTCUSDT", timeframe=timeframe) is None
    )


def test_baseline_is_none_for_a_model_without_evaluated_predictions(
    db_session: Session,
) -> None:
    model = _model(db_session, "BTCUSDT")

    assert get_model_baseline(db_session, model.id, "BTCUSDT", timeframe="1d") is None


def test_daily_closes_takes_the_latest_row_of_each_day(db_session: Session) -> None:
    day = _at(FIRST_DAY)
    for hour, close in [(1, "10"), (23, "30"), (12, "20")]:
        value = Decimal(close)
        db_session.add(
            Price(
                symbol="BTCUSDT",
                timestamp=day + timedelta(hours=hour),
                open=value,
                high=value,
                low=value,
                close=value,
                volume=Decimal("1"),
                source="test",
            )
        )
    db_session.flush()

    assert daily_closes(db_session, "BTCUSDT", FIRST_DAY) == {FIRST_DAY: Decimal("30")}


def test_symbol_filter_scopes_every_shared_query(db_session: Session) -> None:
    closes = [100.0 + i for i in range(6)]
    btc = _model(db_session, "BTCUSDT")
    gold = _model(db_session, "PAXGUSDT")
    _evaluate(db_session, btc, closes, [True] * 4)
    _evaluate(db_session, gold, closes[:5], [True] * 3)

    assert len(get_evaluated_predictions(db_session, symbol="BTCUSDT")) == 4
    assert len(get_evaluated_predictions(db_session, symbol="PAXGUSDT")) == 3
    assert len(get_evaluated_predictions(db_session)) == 7

    gold_models = get_all_models_metrics(db_session, symbol="PAXGUSDT")
    assert [m["symbol"] for m in gold_models] == ["PAXGUSDT"]
    assert gold_models[0]["predictions_count"] == 3
    assert len(get_all_models_metrics(db_session)) == 2

    gold_strategies = get_all_strategies_metrics(db_session, symbol="PAXGUSDT")
    assert gold_strategies[0]["trade_count"] == 3
    assert get_all_strategies_metrics(db_session)[0]["trade_count"] == 7
