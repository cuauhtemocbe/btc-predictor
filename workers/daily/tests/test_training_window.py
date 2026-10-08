"""
Tests for the configured training window (#103).

The trainers no longer pick a window from a phase table: the window comes from
``settings.training_window_days`` and every stored BTCUSDT daily row is used.
"""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import numpy as np
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from shared.config import Settings, settings
from shared.db.models import Model, Price
from shared.utils import utc_today
from workers.daily import trainer
from workers.daily.models import LinearRegressionModel

BTC = "BTCUSDT"
PAXG = "PAXGUSDT"


def _add_daily_rows(
    session: Session, symbol: str, days: int, close: Decimal = Decimal("60000")
) -> None:
    first_day = utc_today() - timedelta(days=days)
    session.add_all(
        Price(
            symbol=symbol,
            timestamp=datetime.combine(
                first_day + timedelta(days=i), time(0, 0), tzinfo=UTC
            ),
            open=close + i,
            high=close + i,
            low=close + i,
            close=close + i,
            volume=Decimal("1"),
            source="test",
        )
        for i in range(days)
    )
    session.commit()


@pytest.fixture
def use_session(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    """trainer.main() opens its own session; hand it the test one."""
    monkeypatch.setattr(trainer, "SessionLocal", lambda: db_session)
    return db_session


class TestPhaseTableRemoved:
    @pytest.mark.parametrize(
        "name", ["calculate_dynamic_window", "count_available_days", "_get_phase_name"]
    )
    def test_function_is_gone(self, name: str) -> None:
        assert not hasattr(trainer, name)


class TestTrainingWindowSetting:
    def test_default_is_21(self) -> None:
        assert Settings(database_url="postgresql://x").training_window_days == 21

    def test_overridable_by_environment_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRAINING_WINDOW_DAYS", "14")

        assert Settings(database_url="postgresql://x").training_window_days == 14

    def test_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Settings(database_url="postgresql://x", training_window_days=0)

    def test_window_is_stored_in_the_model_params(self, use_session: Session) -> None:
        _add_daily_rows(use_session, BTC, days=150)

        assert trainer.main() == 0

        model = use_session.query(Model).one()
        assert model.params["window_days"] == settings.training_window_days == 21

    def test_changing_the_setting_changes_the_window(
        self, use_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "training_window_days", 14)
        _add_daily_rows(use_session, BTC, days=150)

        assert trainer.main() == 0

        assert use_session.query(Model).one().params["window_days"] == 14


class TestTrainsOnEveryBtcRow:
    def test_fetch_returns_every_btc_row_and_no_other_symbol(
        self, db_session: Session
    ) -> None:
        _add_daily_rows(db_session, BTC, days=500, close=Decimal("60000"))
        _add_daily_rows(db_session, PAXG, days=500, close=Decimal("4000"))

        series = trainer.fetch_training_data(db_session, window_days=21)

        assert len(series) == 500
        assert len(series.volumes) == 500
        assert all(p >= 60000 for p in series.closes)
        assert series.closes == sorted(series.closes)  # oldest to newest, rising

    def test_trainer_trains_on_exactly_the_btc_rows(
        self, use_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _add_daily_rows(use_session, BTC, days=500)
        _add_daily_rows(use_session, PAXG, days=500, close=Decimal("4000"))
        seen: dict[str, tuple[int, int]] = {}
        original_train = LinearRegressionModel.train

        def spy(self: LinearRegressionModel, X: np.ndarray, y: np.ndarray) -> None:
            seen["shape"] = X.shape
            original_train(self, X, y)

        monkeypatch.setattr(LinearRegressionModel, "train", spy)

        assert trainer.main() == 0

        # 500 BTCUSDT rows -> 500 - 21 - 1 samples of 2 * 21 + 1 return features
        # (PAXG excluded)
        assert seen["shape"] == (478, 43)


class TestMinimumRows:
    def test_required_rows_follow_the_70_20_10_split(self) -> None:
        assert trainer.required_training_days(21) == 110
        assert trainer.required_training_days(10) == 55

    def test_too_few_rows_names_required_and_available(
        self, db_session: Session
    ) -> None:
        _add_daily_rows(db_session, BTC, days=109)

        with pytest.raises(ValueError, match=r"need 110 daily rows.*have 109"):
            trainer.fetch_training_data(db_session, window_days=21)

    def test_exactly_the_required_rows_is_enough(self, db_session: Session) -> None:
        _add_daily_rows(db_session, BTC, days=110)

        assert len(trainer.fetch_training_data(db_session, window_days=21)) == 110

    def test_other_symbols_do_not_count_toward_the_minimum(
        self, db_session: Session
    ) -> None:
        _add_daily_rows(db_session, BTC, days=50)
        _add_daily_rows(db_session, PAXG, days=500)

        with pytest.raises(ValueError, match=r"need 110 daily rows.*have 50"):
            trainer.fetch_training_data(db_session, window_days=21)

    def test_main_exits_1_when_there_is_not_enough_data(
        self, use_session: Session
    ) -> None:
        _add_daily_rows(use_session, BTC, days=30)

        assert trainer.main() == 1
        assert use_session.query(Model).count() == 0
