"""
Regression tests: weekly worker queries must only read the BTCUSDT series.

Same bug as the daily worker: PAXGUSDT bars share the ``prices`` table since
#102, and unfiltered queries returned two rows per day.
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

import workers.weekly.predictor as pred_module
from shared.db.models import Model, Prediction, Price
from workers.weekly import evaluator, predictor

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
    first_day = date.today() - timedelta(days=days)
    for i in range(days):
        day = first_day + timedelta(days=i)
        _add_bar(session, symbol, datetime.combine(day, time(0, 0), tzinfo=UTC), close)
    session.commit()


class TestWeeklyPredictorSymbolIsolation:
    def test_get_daily_close_prices_returns_one_btc_price_per_day(
        self, db_session: Session
    ) -> None:
        _add_daily_series(db_session, BTC, BTC_CLOSE, days=40)
        _add_daily_series(db_session, PAXG, PAXG_CLOSE, days=40)

        prices = predictor.get_daily_close_prices(db_session, window_days=30)

        assert len(prices) == 30
        assert all(p == BTC_CLOSE for p in prices)

    def test_get_daily_close_prices_for_other_symbol(self, db_session: Session) -> None:
        _add_daily_series(db_session, BTC, BTC_CLOSE, days=40)
        _add_daily_series(db_session, PAXG, PAXG_CLOSE, days=40)

        prices = predictor.get_daily_close_prices(
            db_session, window_days=30, symbol=PAXG
        )

        assert len(prices) == 30
        assert all(p == PAXG_CLOSE for p in prices)

    def test_main_uses_btc_price_when_paxg_is_newest(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_daily_close_prices_30_days: list[Price],
    ) -> None:
        _add_bar(db_session, PAXG, datetime.now(UTC), PAXG_CLOSE)
        db_session.commit()

        original_session = pred_module.SessionLocal
        pred_module.SessionLocal = lambda: db_session
        try:
            assert predictor.main() == 0
        finally:
            pred_module.SessionLocal = original_session

        prediction = db_session.query(Prediction).one()
        assert prediction.price_at_prediction > 50000


class TestWeeklyEvaluatorSymbolIsolation:
    def test_fetch_actual_price_ignores_other_symbol(self, db_session: Session) -> None:
        today = date.today()
        _add_bar(
            db_session,
            PAXG,
            datetime.combine(today, time(7, 0), tzinfo=UTC),
            PAXG_CLOSE,
        )
        _add_bar(
            db_session, BTC, datetime.combine(today, time(8, 0), tzinfo=UTC), BTC_CLOSE
        )
        db_session.commit()

        assert evaluator.fetch_actual_price(db_session, today) == BTC_CLOSE
