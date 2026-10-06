"""
Regression tests: weekly worker queries must only read the BTCUSDT series.

Same bug as the daily worker: PAXGUSDT bars share the ``prices`` table since
#102, and unfiltered queries returned two rows per day.
"""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

import workers.weekly.predictor as pred_module
from shared.db.models import Model, Prediction, Price
from shared.utils import utc_today
from workers.daily import predictor as daily_predictor
from workers.weekly import evaluator, predictor

# weekly.evaluator.fetch_actual_price is re-exported from the daily module, not in its
# public API, so mypy rejects the attribute; look it up through vars().
fetch_actual_price = vars(evaluator)["fetch_actual_price"]

BTC = "BTCUSDT"
PAXG = "PAXGUSDT"
BTC_CLOSE = Decimal("60000")
PAXG_CLOSE = Decimal("4139.2")


def _add_bar(
    session: Session, symbol: str, timestamp: datetime, close: Decimal
) -> None:
    session.add(
        Price(
            symbol=symbol,
            timestamp=timestamp,
            open=close,
            high=close,
            low=close,
            close=close,
            volume=Decimal("1"),
            source="test",
        )
    )


def _add_daily_series(session: Session, symbol: str, close: Decimal, days: int) -> None:
    first_day = utc_today() - timedelta(days=days)
    for i in range(days):
        day = first_day + timedelta(days=i)
        _add_bar(session, symbol, datetime.combine(day, time(0, 0), tzinfo=UTC), close)
    session.commit()


class TestWeeklyPredictorSymbolIsolation:
    def test_get_recent_series_returns_one_btc_row_per_day(
        self, db_session: Session
    ) -> None:
        _add_daily_series(db_session, BTC, BTC_CLOSE, days=40)
        _add_daily_series(db_session, PAXG, PAXG_CLOSE, days=40)

        series = daily_predictor.get_recent_series(db_session, days=31)

        assert len(series) == 31
        assert all(p == BTC_CLOSE for p in series.closes)

    def test_get_recent_series_for_other_symbol(self, db_session: Session) -> None:
        _add_daily_series(db_session, BTC, BTC_CLOSE, days=40)
        _add_daily_series(db_session, PAXG, PAXG_CLOSE, days=40)

        series = daily_predictor.get_recent_series(db_session, days=31, symbol=PAXG)

        assert len(series) == 31
        assert all(p == PAXG_CLOSE for p in series.closes)

    def test_main_uses_btc_price_when_paxg_is_newest(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_daily_close_prices_31_days: list[Price],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _add_bar(db_session, PAXG, datetime.now(UTC), PAXG_CLOSE)
        db_session.commit()

        monkeypatch.setattr(pred_module, "SessionLocal", lambda: db_session)

        assert predictor.main() == 0

        prediction = db_session.query(Prediction).one()
        assert prediction.price_at_prediction > 50000


class TestWeeklyEvaluatorSymbolIsolation:
    def test_fetch_actual_price_ignores_other_symbol(self, db_session: Session) -> None:
        today = utc_today()
        bar_open = datetime.combine(today - timedelta(days=1), time(0, 0), tzinfo=UTC)
        _add_bar(db_session, PAXG, bar_open, PAXG_CLOSE)
        _add_bar(db_session, BTC, bar_open, BTC_CLOSE)
        db_session.commit()

        assert fetch_actual_price(db_session, today) == BTC_CLOSE
