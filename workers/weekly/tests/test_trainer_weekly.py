"""
Tests for the weekly trainer job (issue #61).

Covers Gherkin acceptance criteria:
1. Training creates a seven-day-ahead target
2. The weekly predictor uses the model active for the seven-day horizon
   (activation side, verified here; predictor-side coverage lives in
   test_predictor_weekly.py)
5. Insufficient history prevents invalid training
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from shared.config import settings
from shared.db.crud import get_active_model
from shared.db.models import Model, Price
from workers.weekly import trainer

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_prices_200_days(db_session: Session) -> list[Price]:
    """200 days of daily-spaced BTC prices: covers the window + a 7-day horizon."""
    base_price = 50000
    prices = []

    for i in range(200):
        price_record = Price(
            timestamp=datetime.now(UTC) - timedelta(days=200 - i),
            open=Decimal(base_price + i * 100),
            high=Decimal(base_price + i * 100 + 500),
            low=Decimal(base_price + i * 100 - 500),
            close=Decimal(base_price + i * 100),
            volume=Decimal("1000.5"),
            source="test",
        )
        prices.append(price_record)

    db_session.add_all(prices)
    db_session.commit()
    return prices


def _add_daily_prices(db_session: Session, days: int) -> list[Price]:
    base_price = 50000
    prices = []

    for i in range(days):
        price_record = Price(
            timestamp=datetime.now(UTC) - timedelta(days=days - i),
            open=Decimal(base_price + i * 100),
            high=Decimal(base_price + i * 100 + 500),
            low=Decimal(base_price + i * 100 - 500),
            close=Decimal(base_price + i * 100),
            volume=Decimal("1000.5"),
            source="test",
        )
        prices.append(price_record)

    db_session.add_all(prices)
    db_session.commit()
    return prices


@pytest.fixture
def sample_prices_115_days(db_session: Session) -> list[Price]:
    """
    115 days: enough for the configured window alone ((21 + 1) * 5 = 110 rows)
    but NOT once the 7-day horizon is added on top (needs 116).
    """
    return _add_daily_prices(db_session, 115)


@pytest.fixture
def active_daily_model(db_session: Session, sample_model_artifact: bytes) -> Model:
    """An active timeframe='1d' model, to verify the weekly trainer never touches it."""
    model = Model(
        name="linear_v1",
        version="1.0.0",
        params={"window_days": 30},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=datetime.now(UTC).date() - timedelta(days=30),
        train_to=datetime.now(UTC).date() - timedelta(days=1),
        timeframe="1d",
        is_active=True,
    )
    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)
    return model


@pytest.fixture
def sample_model_artifact() -> bytes:
    """A minimal serialized LinearRegressionModel, for active_daily_model."""
    import pickle

    import numpy as np

    from workers.daily.models.linear import LinearRegressionModel

    model = LinearRegressionModel(window_days=30)
    X = np.random.rand(30, 30) * 50000
    y = np.random.rand(30) * 50000
    model.train(X, y)
    return pickle.dumps(model)


# ============================================================================
# main()
# ============================================================================


class TestMainWeeklyTrainer:
    @pytest.fixture(autouse=True)
    def _patch_session_local(self, db_session: Session):
        """
        trainer.main() opens its own SessionLocal() rather than accepting an
        injected session, so route it to the test's SAVEPOINT-isolated
        db_session -- same pattern used by TestMainWeeklyPredictor in
        test_predictor_weekly.py.
        """
        original = trainer.SessionLocal
        trainer.SessionLocal = lambda: db_session
        yield
        trainer.SessionLocal = original

    def test_success_trains_and_activates_seven_day_model(
        self, db_session: Session, sample_prices_200_days: list[Price]
    ) -> None:
        """
        Given 200 days of historical prices
        When the weekly trainer runs
        Then it saves a model with timeframe='1w' and horizon_days=7 recorded
        And that model is active
        """
        exit_code = trainer.main()

        assert exit_code == 0

        active = get_active_model(db_session, timeframe="1w")
        assert active is not None
        assert active.timeframe == "1w"
        assert active.name == trainer.MODEL_NAME
        assert active.params["horizon_days"] == trainer.HORIZON_DAYS
        assert active.is_active is True

    def test_does_not_touch_active_daily_model(
        self,
        db_session: Session,
        sample_prices_200_days: list[Price],
        active_daily_model: Model,
    ) -> None:
        """
        Given an active '1d' model
        When the weekly trainer trains and activates a '1w' model
        Then the '1d' model remains active and unchanged
        """
        exit_code = trainer.main()
        assert exit_code == 0

        # main() closes its session; re-query by ID rather than refreshing
        # the pre-existing ORM object reference.
        reloaded = db_session.get(Model, active_daily_model.id)
        assert reloaded is not None
        assert reloaded.is_active is True

    def test_insufficient_history_prevents_training(
        self, db_session: Session, sample_prices_115_days: list[Price]
    ) -> None:
        """
        Scenario: Insufficient history prevents invalid training

        Given fewer than the required historical observations for a
        seven-day horizon (115 days: enough for the base window, not
        enough once the horizon is added)
        When weekly model training runs
        Then no invalid weekly model or prediction is created
        And the job reports insufficient data
        """
        exit_code = trainer.main()

        assert exit_code == 1
        assert get_active_model(db_session, timeframe="1w") is None

    def test_horizon_is_added_on_top_of_the_configured_window(
        self, db_session: Session
    ) -> None:
        """116 rows = (21 + 1) * 5 + 7 - 1: the smallest history that trains."""
        _add_daily_prices(db_session, 116)

        assert trainer.main() == 0

        active = get_active_model(db_session, timeframe="1w")
        assert active is not None
        assert active.params["window_days"] == settings.training_window_days == 21
        assert active.params["horizon_days"] == 7

    def test_weekly_trainer_ignores_other_symbols(self, db_session: Session) -> None:
        """PAXGUSDT rows must not make up for missing BTCUSDT history."""
        _add_daily_prices(db_session, 115)
        first_day = datetime.now(UTC).date() - timedelta(days=300)
        db_session.add_all(
            Price(
                symbol="PAXGUSDT",
                timestamp=datetime.combine(
                    first_day + timedelta(days=i), datetime.min.time(), tzinfo=UTC
                ),
                open=Decimal("4000"),
                high=Decimal("4000"),
                low=Decimal("4000"),
                close=Decimal("4000"),
                volume=Decimal("1"),
                source="test",
            )
            for i in range(300)
        )
        db_session.commit()

        assert trainer.main() == 1
        assert get_active_model(db_session, timeframe="1w") is None

    def test_no_data_fails_gracefully(self, db_session: Session) -> None:
        """With no price data at all, the job fails cleanly (exit 1), not a crash."""
        exit_code = trainer.main()

        assert exit_code == 1
