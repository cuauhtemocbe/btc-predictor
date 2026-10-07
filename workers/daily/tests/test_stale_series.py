"""
Tests for refusing a stale or gapped price series (#174).

The jobs run at 00:10 UTC on day D and need the bar of D-1 as the last bar, with
one bar per day before it. Otherwise a return silently spans several days and the
evaluator later scores it as a one-day move. The clock is frozen at 2026-10-04
00:10 UTC (``mexico_city_at_0010_utc``), so the last valid bar is 2026-10-03.
"""

import logging
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from shared.config import settings
from shared.db.models import Model, Prediction, Price
from workers.daily import evaluator, predictor, trainer
from workers.daily.__main__ import main as daily_job

TODAY = date(2026, 10, 4)
YESTERDAY = date(2026, 10, 3)


def _add_bars(db_session: Session, days: Iterable[date]) -> None:
    """Store one bar per given UTC day."""
    db_session.add_all(
        Price(
            timestamp=datetime.combine(day, time.min, tzinfo=UTC),
            open=Decimal(50000 + day.toordinal()),
            high=Decimal(50500 + day.toordinal()),
            low=Decimal(49500 + day.toordinal()),
            close=Decimal(50000 + day.toordinal()),
            volume=Decimal("1000.5"),
            source="test",
        )
        for day in days
    )
    db_session.commit()


def _consecutive(last: date, count: int) -> list[date]:
    return [last - timedelta(days=count - 1 - i) for i in range(count)]


@pytest.mark.usefixtures("mexico_city_at_0010_utc")
class TestDailyPredictorRefusesBadSeries:
    def test_latest_bar_two_days_ago_exits_1_and_stores_nothing(
        self,
        db_session: Session,
        sample_trained_model: Model,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Given the latest bar is dated two days ago, then exit 1, no prediction."""
        _add_bars(db_session, _consecutive(YESTERDAY - timedelta(days=1), 31))

        with caplog.at_level(logging.ERROR):
            assert predictor.main(session=db_session) == 1

        assert db_session.query(Prediction).count() == 0
        assert "latest bar is dated 2026-10-02" in caplog.text

    def test_a_missing_day_inside_the_window_exits_1_naming_the_date(
        self,
        db_session: Session,
        sample_trained_model: Model,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Given one day is missing inside the window, the message names it."""
        days = _consecutive(YESTERDAY, 32)
        days.remove(date(2026, 9, 20))
        _add_bars(db_session, days)

        with caplog.at_level(logging.ERROR):
            assert predictor.main(session=db_session) == 1

        assert db_session.query(Prediction).count() == 0
        assert "2026-09-20" in caplog.text

    def test_a_complete_series_ending_yesterday_predicts_as_before(
        self, db_session: Session, sample_trained_model: Model
    ) -> None:
        """Given a complete series ending yesterday (UTC), a prediction is saved."""
        _add_bars(db_session, _consecutive(YESTERDAY, 31))

        assert predictor.main(session=db_session) == 0

        saved = db_session.query(Prediction).one()
        assert saved.predicted_for == date(2026, 10, 5)
        assert saved.price_at_prediction == Decimal(50000 + YESTERDAY.toordinal())


@pytest.mark.usefixtures("mexico_city_at_0010_utc")
class TestDailyTrainerRefusesBadSeries:
    def test_stale_series_exits_1_and_creates_no_model(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Given a stale series, the daily trainer exits 1 and creates no model."""
        monkeypatch.setattr(trainer, "SessionLocal", lambda: db_session)
        _add_bars(db_session, _consecutive(YESTERDAY - timedelta(days=1), 150))

        assert trainer.main() == 1

        assert db_session.query(Model).count() == 0

    def test_a_gap_exits_1_and_creates_no_model(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(trainer, "SessionLocal", lambda: db_session)
        days = _consecutive(YESTERDAY, 151)
        days.remove(date(2026, 8, 1))
        _add_bars(db_session, days)

        assert trainer.main() == 1

        assert db_session.query(Model).count() == 0

    def test_complete_series_ending_yesterday_still_trains(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(trainer, "SessionLocal", lambda: db_session)
        _add_bars(db_session, _consecutive(YESTERDAY, 150))

        assert trainer.main() == 0

        assert db_session.query(Model).count() == 1


@pytest.mark.usefixtures("mexico_city_at_0010_utc")
class TestSeriesCarriesBarDates:
    def test_get_recent_series_returns_the_bar_dates_oldest_first(
        self, db_session: Session
    ) -> None:
        days = _consecutive(YESTERDAY, 5)
        _add_bars(db_session, days)

        assert predictor.get_recent_series(db_session, days=5).dates == days

    def test_fetch_training_data_returns_the_bar_dates_oldest_first(
        self, db_session: Session
    ) -> None:
        days = _consecutive(YESTERDAY, 120)
        _add_bars(db_session, days)

        assert trainer.fetch_training_data(db_session, 21).dates == days


@pytest.mark.usefixtures("mexico_city_at_0010_utc")
def test_the_daily_job_exits_1_and_skips_the_predictor_on_a_stale_series(
    db_session: Session,
    sample_trained_model: Model,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale trainer run fails the job, and the predictor never runs."""
    monkeypatch.setattr(evaluator, "main", lambda: 0)
    monkeypatch.setattr(trainer, "SessionLocal", lambda: db_session)
    ran: list[str] = []

    def fake_predictor() -> int:
        ran.append("predictor")
        return 0

    monkeypatch.setattr(predictor, "main", fake_predictor)
    _add_bars(db_session, _consecutive(YESTERDAY - timedelta(days=1), 150))

    assert daily_job() == 1

    assert ran == []
    assert db_session.query(Model).count() == 1  # only the pre-existing fixture model


@pytest.mark.usefixtures("mexico_city_at_0010_utc")
class TestPredictorRefusesAnOldClose:
    """Gherkin (#175): the prediction is anchored to a close at most 2 hours old."""

    def test_clock_at_0010_utc_saves_the_prediction(
        self, db_session: Session, sample_trained_model: Model
    ) -> None:
        """Given the bar closed at 00:00 UTC and the clock at 00:10, it is saved."""
        _add_bars(db_session, _consecutive(YESTERDAY, 31))

        now = datetime(2026, 10, 4, 0, 10, tzinfo=UTC)
        assert predictor.main(session=db_session, now=now) == 0

        assert db_session.query(Prediction).count() == 1

    def test_clock_at_0700_utc_with_the_same_bar_exits_1_and_saves_nothing(
        self,
        db_session: Session,
        sample_trained_model: Model,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Given the same bar and the clock at 07:00 UTC, exit 1 and save nothing."""
        _add_bars(db_session, _consecutive(YESTERDAY, 31))

        now = datetime(2026, 10, 4, 7, 0, tzinfo=UTC)
        with caplog.at_level(logging.ERROR):
            assert predictor.main(session=db_session, now=now) == 1

        assert db_session.query(Prediction).count() == 0
        assert "the maximum age is 2:00:00" in caplog.text

    def test_the_limit_comes_from_the_settings(
        self,
        db_session: Session,
        sample_trained_model: Model,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Given max_bar_age_hours = 8, a run at 07:00 UTC is accepted."""
        monkeypatch.setattr(settings, "max_bar_age_hours", 8)
        _add_bars(db_session, _consecutive(YESTERDAY, 31))

        now = datetime(2026, 10, 4, 7, 0, tzinfo=UTC)
        assert predictor.main(session=db_session, now=now) == 0

    def test_default_clock_is_the_utc_clock(
        self,
        db_session: Session,
        sample_trained_model: Model,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Given no ``now``, the predictor reads ``utc_now`` (frozen at 07:00)."""
        monkeypatch.setattr(
            predictor, "utc_now", lambda: datetime(2026, 10, 4, 7, 0, tzinfo=UTC)
        )
        _add_bars(db_session, _consecutive(YESTERDAY, 31))

        assert predictor.main(session=db_session) == 1
