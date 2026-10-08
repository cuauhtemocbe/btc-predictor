"""
Tests for the UTC date of the daily jobs (#173).

The containers run with ``TZ=America/Mexico_City``, six hours behind UTC, while a
daily bar is a UTC day. At 00:10 UTC on 2026-10-04 the local date is still
2026-10-03, so a job built on ``date.today()`` is a day behind the pipeline.
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from shared.db.models import Model, Prediction, Price
from workers.daily import evaluator, predictor, trainer

UTC_DAY = date(2026, 10, 4)


def _add_daily_prices(db_session: Session, days: int) -> None:
    """Store ``days`` consecutive bars ending on the day before ``UTC_DAY``."""
    db_session.add_all(
        Price(
            timestamp=datetime.combine(
                UTC_DAY - timedelta(days=days - i), time.min, tzinfo=UTC
            ),
            open=Decimal(50000 + i * 100),
            high=Decimal(50500 + i * 100),
            low=Decimal(49500 + i * 100),
            close=Decimal(50000 + i * 100),
            volume=Decimal("1000.5"),
            source="test",
        )
        for i in range(days)
    )
    db_session.commit()


@pytest.mark.usefixtures("mexico_city_at_0010_utc")
class TestDailyJobsUseTheUtcDate:
    """Gherkin: TZ=America/Mexico_City and the clock at 2026-10-04 00:10 UTC."""

    def test_the_predictor_predicts_the_next_utc_day(
        self,
        db_session: Session,
        sample_trained_model: Model,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Then it stores predicted_for = 2026-10-05, not the local date plus one."""
        _add_daily_prices(db_session, 31)

        assert predictor.main(session=db_session) == 0

        assert db_session.query(Prediction).one().predicted_for == date(2026, 10, 5)

    def test_the_evaluator_settles_what_is_due_up_to_the_utc_day(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Then it evaluates the predictions due up to 2026-10-04."""
        monkeypatch.setattr(evaluator, "SessionLocal", MagicMock())
        asked: list[date] = []

        def find_pending(session: Session, today: date) -> list[Prediction]:
            asked.append(today)
            return []

        monkeypatch.setattr(evaluator, "find_pending_predictions", find_pending)

        assert evaluator.main() == 0

        assert asked == [UTC_DAY]

    def test_the_trainer_ends_the_training_range_on_the_utc_day(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(trainer, "SessionLocal", lambda: db_session)
        _add_daily_prices(db_session, 150)

        assert trainer.main() == 0

        assert db_session.query(Model).one().train_to == UTC_DAY
