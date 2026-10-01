"""
Regression tests: daily worker queries must only read the BTCUSDT series.

Since #102 the ``prices`` table also holds PAXGUSDT bars. Queries that did not
filter by symbol returned two rows per day, so the trainer/predictor built
feature vectors twice as long as the model expected ("X must have 21 features,
got 42") and used the gold price as the "current BTC price".
"""

from argparse import Namespace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from shared.db.models import Model, Prediction, Price
from workers.backtest.main import calculate_adaptive_window
from workers.daily import evaluator, predictor
from workers.daily.trainer import fetch_training_data

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


def _add_daily_series(
    session: Session, symbol: str, close: Decimal, days: int, step: Decimal = Decimal(0)
) -> None:
    """One 00:00 UTC bar per day for ``days`` days ending yesterday.

    Both symbols use identical timestamps on purpose: a join on timestamp
    alone would match both rows.
    """
    first_day = date.today() - timedelta(days=days)
    for i in range(days):
        day = first_day + timedelta(days=i)
        _add_bar(
            session,
            symbol,
            datetime.combine(day, time(0, 0), tzinfo=UTC),
            close + step * i,
        )
    session.commit()


@pytest.fixture
def two_symbols(db_session: Session) -> Session:
    """40 days of BTCUSDT (60000+) and PAXGUSDT (4139) on the same timestamps."""
    _add_daily_series(db_session, BTC, BTC_CLOSE, days=40, step=Decimal(10))
    _add_daily_series(db_session, PAXG, PAXG_CLOSE, days=40, step=Decimal("0.5"))
    return db_session


class TestTrainerSymbolIsolation:
    def test_fetch_training_data_returns_only_btc(self, two_symbols: Session) -> None:
        series = fetch_training_data(two_symbols, window_days=5)

        assert len(series) == 40
        assert all(p >= BTC_CLOSE for p in series.closes)

    def test_fetch_training_data_for_other_symbol(self, two_symbols: Session) -> None:
        series = fetch_training_data(two_symbols, window_days=5, symbol=PAXG)

        assert len(series) == 40
        assert all(p < 5000 for p in series.closes)


class TestPredictorSymbolIsolation:
    def test_get_recent_series_returns_one_btc_row_per_day(
        self, two_symbols: Session
    ) -> None:
        series = predictor.get_recent_series(two_symbols, days=22)

        assert len(series) == 22
        assert all(p >= BTC_CLOSE for p in series.closes)

    def test_get_recent_series_for_other_symbol(self, two_symbols: Session) -> None:
        series = predictor.get_recent_series(two_symbols, days=22, symbol=PAXG)

        assert len(series) == 22
        assert all(p < 5000 for p in series.closes)

    def test_main_uses_btc_price_and_predicts_when_paxg_is_newest(
        self,
        db_session: Session,
        sample_trained_model: Model,
        sample_btc_prices_31_days: list[Price],
    ) -> None:
        """The newest row in the table is PAXG; the prediction must still be BTC."""
        _add_bar(db_session, PAXG, datetime.now(UTC), PAXG_CLOSE)
        db_session.commit()

        original_session_local = predictor.SessionLocal
        original_parse_args = predictor.parse_args
        predictor.SessionLocal = lambda: db_session
        predictor.parse_args = lambda: Namespace(multi_model=False)
        try:
            assert predictor.main() == 0
        finally:
            predictor.SessionLocal = original_session_local
            predictor.parse_args = original_parse_args

        prediction = db_session.query(Prediction).one()
        assert prediction.price_at_prediction > 50000


class TestEvaluatorSymbolIsolation:
    def test_fetch_actual_price_ignores_other_symbol(self, db_session: Session) -> None:
        """PAXG has the earliest candle after 07:00, BTC has a later one."""
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
        assert evaluator.fetch_actual_price(db_session, today, symbol=PAXG) == (
            PAXG_CLOSE
        )


class TestBacktestWindowSymbolIsolation:
    def test_adaptive_window_counts_only_btc_days(self, db_session: Session) -> None:
        """80 BTC days would give a 30/30 window; 10 BTC + 70 PAXG must not."""
        _add_daily_series(db_session, BTC, BTC_CLOSE, days=10)
        _add_daily_series(db_session, PAXG, PAXG_CLOSE, days=70)

        assert calculate_adaptive_window(db_session) is None
