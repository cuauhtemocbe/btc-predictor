"""Tests for the return-based metrics (#177)."""

import math
import statistics
from decimal import Decimal

import pytest

from shared.returns import (
    PERIODS_PER_YEAR,
    equity_curve,
    max_drawdown_pct,
    returns_from_pnl,
    sharpe_ratio,
    trade_return,
    worst_trade_pct,
)


def test_equity_curve_compounds_from_one() -> None:
    """Given +10%, -20% and +5%, the equity is 1.10, 0.88, 0.924."""
    assert equity_curve([0.10, -0.20, 0.05]) == pytest.approx([1.10, 0.88, 0.924])


def test_max_drawdown_of_the_compounded_curve_is_minus_20_pct() -> None:
    """
    Given returns of +10%, -20% and +5%
    When the max drawdown is computed
    Then it is -20% (equity 1.10, 0.88, 0.924; peak 1.10)
    """
    assert max_drawdown_pct([0.10, -0.20, 0.05]) == pytest.approx(-20.0)


def test_max_drawdown_compounds_instead_of_adding() -> None:
    """Two -10% days after a +10% peak fall 19%, not 20%."""
    assert max_drawdown_pct([0.10, -0.10, -0.10]) == pytest.approx(-19.0)


def test_max_drawdown_counts_the_starting_equity_as_a_peak() -> None:
    """A losing first day is a drawdown from the 1.0 start."""
    assert max_drawdown_pct([-0.05, 0.02]) == pytest.approx(-5.0)


def test_max_drawdown_is_zero_when_equity_only_rises() -> None:
    assert max_drawdown_pct([0.01, 0.02]) == 0.0


def test_max_drawdown_never_goes_below_minus_100_pct() -> None:
    """Three -60% days stay above -100%; the dollar curve could go to zero."""
    drawdown = max_drawdown_pct([-0.6, -0.6, -0.6])

    assert drawdown is not None
    assert -100.0 < drawdown < 0.0


def test_max_drawdown_is_none_without_returns() -> None:
    assert max_drawdown_pct([]) is None


def test_trade_return_is_pnl_over_the_price_at_prediction() -> None:
    """
    Given BTC at $100,000 and one day of -$5,000
    Then the day's return is -5%, not -50%
    """
    assert trade_return(Decimal("-5000"), Decimal("100000")) == pytest.approx(-0.05)
    assert max_drawdown_pct([-5000 / 100_000]) == pytest.approx(-5.0)


@pytest.mark.parametrize("price", [None, Decimal("0"), Decimal("-1")])
def test_trade_return_is_none_without_a_positive_price(price: Decimal | None) -> None:
    assert trade_return(Decimal("100"), price) is None


def test_trade_return_is_none_without_a_pnl() -> None:
    assert trade_return(None, Decimal("100")) is None


def test_returns_from_pnl_drops_days_without_a_return() -> None:
    rows = [
        (Decimal("10"), Decimal("100")),
        (None, Decimal("100")),
        (Decimal("5"), Decimal("0")),
        (Decimal("-20"), Decimal("200")),
    ]

    assert returns_from_pnl(rows) == pytest.approx([0.10, -0.10])


def test_worst_trade_is_the_minimum_single_day_return() -> None:
    assert worst_trade_pct([0.10, -0.10, -0.05]) == pytest.approx(-10.0)
    assert worst_trade_pct([]) is None


def test_sharpe_ratio_is_mean_over_stdev_times_sqrt_365() -> None:
    """
    Given daily returns with mean m and standard deviation s
    Then the Sharpe ratio is m / s * sqrt(365)
    """
    returns = [0.01, -0.02, 0.03, 0.005]
    expected = statistics.fmean(returns) / statistics.stdev(returns) * math.sqrt(365)

    assert PERIODS_PER_YEAR == 365
    assert sharpe_ratio(returns) == pytest.approx(expected)


def test_sharpe_ratio_subtracts_the_daily_risk_free_rate() -> None:
    returns = [0.01, -0.02, 0.03, 0.005]
    expected = (
        (statistics.fmean(returns) - 0.05 / 365)
        / statistics.stdev(returns)
        * math.sqrt(365)
    )

    assert sharpe_ratio(returns, risk_free_rate=0.05) == pytest.approx(expected)


@pytest.mark.parametrize("returns", [[], [0.01], [0.01, 0.01, 0.01]])
def test_sharpe_ratio_is_none_when_undefined(returns: list[float]) -> None:
    """Fewer than 2 returns, or returns that do not vary, have no Sharpe ratio."""
    assert sharpe_ratio(returns) is None
