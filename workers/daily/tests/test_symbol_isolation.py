"""
Regression tests: daily worker queries must only read the BTCUSDT series.

Since #102 the ``prices`` table also holds PAXGUSDT bars. Queries that did not
filter by symbol returned two rows per day, so the trainer/predictor built
feature vectors twice as long as the model expected ("X must have 21 features,
got 42") and used the gold price as the "current BTC price".
"""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from scripts.backtest_engine import InsufficientHistoryError, load_daily_history
from shared.db.models import Model, Prediction, Price
from shared.utils import utc_today
from workers.backtest.main import plan_range
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
    first_day = utc_today() - timedelta(days=days)
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
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The newest row in the table is PAXG; the prediction must still be BTC."""
        _add_bar(db_session, PAXG, datetime.now(UTC), PAXG_CLOSE)
        db_session.commit()

        monkeypatch.setattr(predictor, "SessionLocal", lambda: db_session)

        assert predictor.main() == 0

        prediction = db_session.query(Prediction).one()
        assert prediction.price_at_prediction > 50000


class TestEvaluatorSymbolIsolation:
    def test_fetch_actual_price_ignores_other_symbol(self, db_session: Session) -> None:
        """Both symbols have a bar that settles today; each gets its own close."""
        today = utc_today()
        bar_open = datetime.combine(today - timedelta(days=1), time(0, 0), tzinfo=UTC)
        _add_bar(db_session, PAXG, bar_open, PAXG_CLOSE)
        _add_bar(db_session, BTC, bar_open, BTC_CLOSE)
        db_session.commit()

        assert evaluator.fetch_actual_price(db_session, today) == BTC_CLOSE
        assert evaluator.fetch_actual_price(db_session, today, symbol=PAXG) == (
            PAXG_CLOSE
        )


class TestBacktestWindowSymbolIsolation:
    def test_planned_range_counts_only_btc_days(self, db_session: Session) -> None:
        """300 BTC + PAXG days would plan a range; 10 BTC + 290 PAXG must not."""
        _add_daily_series(db_session, BTC, BTC_CLOSE, days=10)
        _add_daily_series(db_session, PAXG, PAXG_CLOSE, days=290)

        history = load_daily_history(db_session)

        with pytest.raises(InsufficientHistoryError):
            plan_range(history, 21)
