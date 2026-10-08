"""Return-based performance metrics (#177).

The stored ``pnl_*`` columns are dollar deltas on a 1-unit position, so their sum
over years weights recent high prices more and says nothing about risk. Every
risk metric shown to the user is derived here from per-trade returns,
``pnl / price_at_prediction``, compounded from an equity of 1.0. Nothing in this
module is stored: callers recompute on read and the ``pnl_*`` columns do not change.

Every series is daily (the only timeframe left, #183), so the annualization factor
is the square root of ``PERIODS_PER_YEAR``.
"""

import math
from collections.abc import Iterable
from decimal import Decimal

import numpy as np

PERIODS_PER_YEAR = 365

# Prediction rows whose price is missing or not positive cannot give a return.
_MIN_VALID_PRICE = 0.0


def trade_return(
    pnl: Decimal | float | None, price: Decimal | float | None
) -> float | None:
    """Return ``pnl / price`` as a fraction, or None when either is unusable.

    A day without a PnL or without a positive price anchor has no return; it is
    skipped from every return-based metric instead of being counted as 0.
    """
    if pnl is None or price is None:
        return None
    price_value = float(price)
    if price_value <= _MIN_VALID_PRICE:
        return None
    return float(pnl) / price_value


def returns_from_pnl(
    rows: Iterable[tuple[Decimal | float | None, Decimal | float | None]],
) -> list[float]:
    """Turn ``(pnl, price_at_prediction)`` pairs into returns, in the given order.

    Pairs with no usable return (see ``trade_return``) are dropped.
    """
    returns: list[float] = []
    for pnl, price in rows:
        value = trade_return(pnl, price)
        if value is not None:
            returns.append(value)
    return returns


def equity_curve(returns: Iterable[float]) -> list[float]:
    """Compound ``returns`` from an equity of 1.0; the start is not included.

    Returns +10%, -20%, +5% give 1.10, 0.88, 0.924.
    """
    curve: list[float] = []
    equity = 1.0
    for value in returns:
        equity *= 1.0 + value
        curve.append(equity)
    return curve


def max_drawdown_pct(returns: Iterable[float]) -> float | None:
    """Largest peak-to-trough fall of the compounded equity curve, in percent.

    The starting equity of 1.0 counts as a peak, so a first losing day is a
    drawdown. Returns a value <= 0 (-20.0 for a 20% fall), or None without returns.
    """
    curve = equity_curve(returns)
    if not curve:
        return None
    equity = np.array([1.0, *curve])
    peak = np.maximum.accumulate(equity)
    return float(np.min((equity - peak) / peak) * 100)


def worst_trade_pct(returns: Iterable[float]) -> float | None:
    """The single worst return, in percent, or None without returns."""
    values = list(returns)
    if not values:
        return None
    return min(values) * 100


def sharpe_ratio(returns: Iterable[float], risk_free_rate: float = 0.0) -> float | None:
    """Annualized Sharpe ratio of daily returns.

    ``(mean - risk_free_rate / 365) / stdev * sqrt(365)``, with the sample standard
    deviation (``ddof=1``) and ``risk_free_rate`` an annual rate. None with fewer
    than 2 returns or when they do not vary, because the ratio is undefined.
    """
    values = np.array(list(returns), dtype=float)
    if len(values) < 2:
        return None
    std = float(np.std(values, ddof=1))
    if std == 0:
        return None
    mean = float(np.mean(values)) - risk_free_rate / PERIODS_PER_YEAR
    return mean / std * math.sqrt(PERIODS_PER_YEAR)
