"""
Tests for refusing a stale or gapped price series in the weekly jobs (#174).

Same rule as the daily jobs (see workers/daily/tests/test_stale_series.py): the
last bar must be dated yesterday (UTC) and the days before it consecutive. The
clock is frozen at 2026-10-04 03:00 UTC, so the last valid bar is 2026-10-03.
"""

import logging
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from shared.db.models import Model, Prediction, Price
from workers.weekly import predictor as weekly_predictor
from workers.weekly import trainer as weekly_trainer

YESTERDAY = date(2026, 10, 3)


def _add_bars(db_session: Session, days: Iterable[date]) -> None:
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


@pytest.mark.usefixtures("mexico_city_at_0300_utc")
class TestWeeklyJobsRefuseBadSeries:
    def test_weekly_predictor_accepts_a_complete_series_ending_yesterday(
        self,
        db_session: Session,
        sample_trained_model: Model,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(weekly_predictor, "SessionLocal", lambda: db_session)
        _add_bars(db_session, _consecutive(YESTERDAY, 31))

        assert weekly_predictor.main() == 0

        assert db_session.query(Prediction).one().predicted_for == date(2026, 10, 11)

    def test_weekly_predictor_refuses_a_stale_series(
        self,
        db_session: Session,
        sample_trained_model: Model,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(weekly_predictor, "SessionLocal", lambda: db_session)
        _add_bars(db_session, _consecutive(YESTERDAY - timedelta(days=1), 31))

        with caplog.at_level(logging.ERROR):
            assert weekly_predictor.main() == 1

        assert "latest bar is dated 2026-10-02" in caplog.text
        assert db_session.query(Prediction).count() == 0

    def test_weekly_predictor_refuses_a_gap(
        self,
        db_session: Session,
        sample_trained_model: Model,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(weekly_predictor, "SessionLocal", lambda: db_session)
        days = _consecutive(YESTERDAY, 32)
        days.remove(date(2026, 9, 20))
        _add_bars(db_session, days)

        with caplog.at_level(logging.ERROR):
            assert weekly_predictor.main() == 1

        assert "2026-09-20" in caplog.text
        assert db_session.query(Prediction).count() == 0

    def test_weekly_trainer_refuses_a_stale_series(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(weekly_trainer, "SessionLocal", lambda: db_session)
        _add_bars(db_session, _consecutive(YESTERDAY - timedelta(days=1), 200))

        assert weekly_trainer.main() == 1

        assert db_session.query(Model).count() == 0
