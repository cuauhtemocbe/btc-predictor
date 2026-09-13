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

from shared.db.crud import get_active_model
from shared.db.models import BtcPrice, Model
from workers.weekly import trainer

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_prices_200_days(db_session: Session) -> list[BtcPrice]:
    """200 days of daily-spaced BTC prices -- enough for Phase 5 + a 7-day horizon."""
    base_price = 50000
    prices = []

    for i in range(200):
        price_record = BtcPrice(
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


@pytest.fixture
def sample_prices_35_days(db_session: Session) -> list[BtcPrice]:
    """
    35 days: enough for calculate_dynamic_window()'s Phase 1 floor (min=30)
    but NOT enough once the 7-day horizon is added on top (needs 36).
    """
    base_price = 50000
    prices = []

    for i in range(35):
        price_record = BtcPrice(
            timestamp=datetime.now(UTC) - timedelta(days=35 - i),
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
        self, db_session: Session, sample_prices_200_days: list[BtcPrice]
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
        sample_prices_200_days: list[BtcPrice],
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
        self, db_session: Session, sample_prices_35_days: list[BtcPrice]
    ) -> None:
        """
        Scenario: Insufficient history prevents invalid training

        Given fewer than the required historical observations for a
        seven-day horizon (35 days: enough for the base window, not
        enough once the horizon is added)
        When weekly model training runs
        Then no invalid weekly model or prediction is created
        And the job reports insufficient data
        """
        exit_code = trainer.main()

        assert exit_code == 1
        assert get_active_model(db_session, timeframe="1w") is None

    def test_no_data_fails_gracefully(self, db_session: Session) -> None:
        """With no price data at all, the job fails cleanly (exit 1), not a crash."""
        exit_code = trainer.main()

        assert exit_code == 1
