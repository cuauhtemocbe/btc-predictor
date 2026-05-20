"""Tests for strategy metrics calculation utilities."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from btc_shared.strategies import (
    calculate_cumulative_pnl,
    calculate_strategy_metrics,
    get_all_strategies_metrics,
)
from sqlalchemy.orm import Session

from shared.db.models import Model, Prediction


@pytest.fixture
def test_model(db_session: Session) -> Model:
    """Create a test model for predictions."""
    model = Model(
        name="test_model",
        version="1.0.0",
        params={"window_days": 30},
        artifact=b"fake_pickle_data",
        trained_at=datetime.now(UTC),
        train_from=date.today() - timedelta(days=30),
        train_to=date.today(),
        is_active=True,
    )
    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)
    return model


@pytest.fixture
def sample_predictions(db_session: Session, test_model: Model) -> list[Prediction]:
    """Create sample predictions with PnL values for testing."""
    predictions = [
        Prediction(
            model_id=test_model.id,
            predicted_for=date(2026, 5, 1),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("50000"),
            predicted_price=Decimal("50000"),
            actual_price=Decimal("51000"),
            pnl_simulated=Decimal("100"),
            pnl_long_short=Decimal("100"),
            pnl_threshold=Decimal("100"),
            pnl_realistic=Decimal("95"),
        ),
        Prediction(
            model_id=test_model.id,
            predicted_for=date(2026, 5, 2),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("51000"),
            predicted_price=Decimal("51000"),
            actual_price=Decimal("50500"),
            pnl_simulated=Decimal("-50"),
            pnl_long_short=Decimal("-50"),
            pnl_threshold=Decimal("0"),  # Below threshold
            pnl_realistic=Decimal("-52.5"),
        ),
        Prediction(
            model_id=test_model.id,
            predicted_for=date(2026, 5, 3),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("50500"),
            predicted_price=Decimal("50500"),
            actual_price=Decimal("52000"),
            pnl_simulated=Decimal("200"),
            pnl_long_short=Decimal("200"),
            pnl_threshold=Decimal("200"),
            pnl_realistic=Decimal("190"),
        ),
        Prediction(
            model_id=test_model.id,
            predicted_for=date(2026, 5, 4),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("52000"),
            predicted_price=Decimal("52000"),
            actual_price=Decimal("51700"),
            pnl_simulated=Decimal("-30"),
            pnl_long_short=Decimal("-30"),
            pnl_threshold=Decimal("0"),  # Below threshold
            pnl_realistic=Decimal("-31.5"),
        ),
        Prediction(
            model_id=test_model.id,
            predicted_for=date(2026, 5, 5),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("51700"),
            predicted_price=Decimal("51700"),
            actual_price=Decimal("53000"),
            pnl_simulated=Decimal("150"),
            pnl_long_short=Decimal("150"),
            pnl_threshold=Decimal("150"),
            pnl_realistic=Decimal("142.5"),
        ),
    ]
    db_session.add_all(predictions)
    db_session.commit()
    for pred in predictions:
        db_session.refresh(pred)
    return predictions


def test_calculate_strategy_metrics_with_known_values(
    sample_predictions: list[Prediction],
):
    """Test metrics calculation with known PnL values."""
    # Long/Short strategy: [100, -50, 200, -30, 150]
    metrics = calculate_strategy_metrics(sample_predictions, "pnl_long_short")

    assert metrics["total_pnl"] == 370.0  # 100 - 50 + 200 - 30 + 150
    assert metrics["win_rate"] == 0.6  # 3 wins out of 5 trades (60%)
    assert metrics["max_drawdown"] == -50.0  # Worst single loss
    assert metrics["avg_win"] == 150.0  # (100 + 200 + 150) / 3
    assert metrics["avg_loss"] == -40.0  # (-50 + -30) / 2
    assert metrics["trade_count"] == 5
    assert metrics["sharpe_ratio"] != 0.0  # Should be calculated


def test_calculate_strategy_metrics_with_threshold_strategy(
    sample_predictions: list[Prediction],
):
    """Test threshold strategy which has some zero-trade days."""
    # Threshold strategy: [100, 0, 200, 0, 150] (only 3 actual trades)
    metrics = calculate_strategy_metrics(sample_predictions, "pnl_threshold")

    assert metrics["total_pnl"] == 450.0  # 100 + 200 + 150 (ignoring zeros)
    assert metrics["trade_count"] == 5  # All predictions included
    assert metrics["win_rate"] == 0.6  # 3 wins, 2 zeros
    assert metrics["max_drawdown"] == 0.0  # No losses


def test_calculate_strategy_metrics_with_empty_predictions():
    """Test metrics calculation with no predictions."""
    metrics = calculate_strategy_metrics([], "pnl_simulated")

    assert metrics["total_pnl"] == 0.0
    assert metrics["win_rate"] == 0.0
    assert metrics["max_drawdown"] == 0.0
    assert metrics["avg_win"] == 0.0
    assert metrics["avg_loss"] == 0.0
    assert metrics["sharpe_ratio"] == 0.0
    assert metrics["trade_count"] == 0


def test_calculate_strategy_metrics_with_only_unevaluated_predictions(
    db_session: Session, test_model: Model
):
    """Test metrics with predictions that haven't been evaluated yet (actual_price is NULL)."""
    predictions = [
        Prediction(
            model_id=test_model.id,
            predicted_for=date(2026, 5, 6),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("50000"),
            predicted_price=Decimal("50000"),
            actual_price=None,  # Not evaluated yet
            pnl_simulated=None,
            pnl_long_short=None,
            pnl_threshold=None,
            pnl_realistic=None,
        )
    ]
    db_session.add_all(predictions)
    db_session.commit()

    metrics = calculate_strategy_metrics(predictions, "pnl_simulated")

    # Should treat as zero trades
    assert metrics["total_pnl"] == 0.0
    assert metrics["trade_count"] == 0


def test_calculate_strategy_metrics_sharpe_ratio(test_model: Model):
    """Test Sharpe Ratio calculation with known daily returns."""
    # Create predictions with specific PnL pattern
    predictions = [
        Prediction(
            model_id=test_model.id,
            predicted_for=date(2026, 5, i),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("50000"),
            predicted_price=Decimal("50000"),
            actual_price=Decimal("50000"),
            pnl_simulated=Decimal(str(pnl)),
            pnl_long_short=Decimal(str(pnl)),
            pnl_threshold=Decimal(str(pnl)),
            pnl_realistic=Decimal(str(pnl)),
        )
        for i, pnl in enumerate([100, -50, 150, 80, 120], start=1)
    ]

    metrics = calculate_strategy_metrics(predictions, "pnl_simulated")

    # Sharpe = mean / stdev
    # mean = (100 - 50 + 150 + 80 + 120) / 5 = 80
    # stdev ≈ 69.28 (numpy calculation)
    # sharpe ≈ 80 / 69.28 ≈ 1.15
    assert metrics["sharpe_ratio"] > 0
    assert 1.0 <= metrics["sharpe_ratio"] <= 1.2


def test_calculate_cumulative_pnl(sample_predictions: list[Prediction]):
    """Test cumulative PnL calculation over time."""
    cumulative = calculate_cumulative_pnl(sample_predictions, "pnl_long_short")

    assert len(cumulative) == 5
    assert cumulative[0]["date"] == "2026-05-01"
    assert cumulative[0]["cumulative_pnl"] == 100.0
    assert cumulative[1]["cumulative_pnl"] == 50.0  # 100 - 50
    assert cumulative[2]["cumulative_pnl"] == 250.0  # 50 + 200
    assert cumulative[3]["cumulative_pnl"] == 220.0  # 250 - 30
    assert cumulative[4]["cumulative_pnl"] == 370.0  # 220 + 150


def test_calculate_cumulative_pnl_sorted_by_date(
    db_session: Session, test_model: Model
):
    """Test that cumulative PnL is calculated in date order."""
    # Insert predictions out of order
    predictions = [
        Prediction(
            model_id=test_model.id,
            predicted_for=date(2026, 5, 3),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("50000"),
            predicted_price=Decimal("50000"),
            actual_price=Decimal("51000"),
            pnl_simulated=Decimal("200"),
            pnl_long_short=Decimal("200"),
            pnl_threshold=Decimal("200"),
            pnl_realistic=Decimal("190"),
        ),
        Prediction(
            model_id=test_model.id,
            predicted_for=date(2026, 5, 1),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("50000"),
            predicted_price=Decimal("50000"),
            actual_price=Decimal("51000"),
            pnl_simulated=Decimal("100"),
            pnl_long_short=Decimal("100"),
            pnl_threshold=Decimal("100"),
            pnl_realistic=Decimal("95"),
        ),
        Prediction(
            model_id=test_model.id,
            predicted_for=date(2026, 5, 2),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("50000"),
            predicted_price=Decimal("50000"),
            actual_price=Decimal("50500"),
            pnl_simulated=Decimal("-50"),
            pnl_long_short=Decimal("-50"),
            pnl_threshold=Decimal("0"),
            pnl_realistic=Decimal("-47.5"),
        ),
    ]
    db_session.add_all(predictions)
    db_session.commit()

    cumulative = calculate_cumulative_pnl(predictions, "pnl_simulated")

    # Should be sorted by date: 5/1 → 5/2 → 5/3
    assert cumulative[0]["date"] == "2026-05-01"
    assert cumulative[0]["cumulative_pnl"] == 100.0
    assert cumulative[1]["date"] == "2026-05-02"
    assert cumulative[1]["cumulative_pnl"] == 50.0  # 100 - 50
    assert cumulative[2]["date"] == "2026-05-03"
    assert cumulative[2]["cumulative_pnl"] == 250.0  # 50 + 200


def test_get_all_strategies_metrics(
    db_session: Session, sample_predictions: list[Prediction]
):
    """Test getting metrics for all 4 strategies at once."""
    strategies = get_all_strategies_metrics(db_session)

    assert len(strategies) == 4
    assert strategies[0]["name"] == "simple"
    assert strategies[1]["name"] == "long_short"
    assert strategies[2]["name"] == "threshold"
    assert strategies[3]["name"] == "realistic"

    # Verify each has all required fields
    for strategy in strategies:
        assert "display_name" in strategy
        assert "color" in strategy
        assert "total_pnl" in strategy
        assert "win_rate" in strategy
        assert "max_drawdown" in strategy
        assert "avg_win" in strategy
        assert "avg_loss" in strategy
        assert "sharpe_ratio" in strategy
        assert "trade_count" in strategy
        assert "cumulative_pnl" in strategy

    # Verify cumulative PnL is a list
    assert isinstance(strategies[0]["cumulative_pnl"], list)
    assert len(strategies[0]["cumulative_pnl"]) == 5  # 5 sample predictions


def test_get_all_strategies_metrics_with_empty_database(db_session: Session):
    """Test all strategies metrics with no predictions."""
    strategies = get_all_strategies_metrics(db_session)

    assert len(strategies) == 4
    for strategy in strategies:
        assert strategy["total_pnl"] == 0.0
        assert strategy["trade_count"] == 0
        assert len(strategy["cumulative_pnl"]) == 0
