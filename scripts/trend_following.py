"""
Trend-following rules and the metrics that judge them (spike #181).

Pure functions over daily closes, no database and no model: the rules (SMA and a
Donchian ensemble with volatility sizing), a long-or-cash simulation with fees and
slippage charged on position changes, metrics on compounded returns, the deflated
Sharpe ratio and rolling-window result distributions. ``scripts/trend_study.py``
runs the validation and test protocol on top of them.

Timing: a position is decided with the closes up to day ``t`` (inclusive) and earns
the return from close ``t`` to close ``t + 1``. A rule never sees a later close.
"""

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import numpy.typing as npt

TRADING_DAYS_PER_YEAR = 365  # Bitcoin trades every day, so the year has 365 bars
EULER_MASCHERONI = 0.5772156649015329
FLAT_STD = 1e-12  # below this a return series counts as constant

Floats = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Costs:
    """Cost of one side of a trade, as a fraction of the traded value."""

    fee: float = 0.001  # Binance spot, 0.1% per side
    slippage: float = 0.001  # allowance for a manual fill away from the close

    @property
    def per_side(self) -> float:
        """Fee plus slippage."""
        return self.fee + self.slippage


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def sma_positions(closes: Floats, lookback: int) -> Floats:
    """
    Long (1.0) while the close is above its simple moving average, else cash (0.0).

    The average covers the last ``lookback`` closes, today's included. Until
    ``lookback`` closes exist the position is cash. A close equal to the average is
    cash.

    Raises:
        ValueError: If ``lookback`` < 2.
    """
    if lookback < 2:
        raise ValueError("lookback must be >= 2")
    positions = np.zeros(len(closes))
    if len(closes) < lookback:
        return positions
    cumulative = np.concatenate(([0.0], np.cumsum(closes)))
    average = (cumulative[lookback:] - cumulative[:-lookback]) / lookback
    positions[lookback - 1 :] = closes[lookback - 1 :] > average
    return positions


def donchian_state(closes: Floats, lookback: int) -> Floats:
    """
    Long (1.0) or cash (0.0) from one Donchian channel on closes.

    Enters when the close is above the highest close of the previous ``lookback``
    days and leaves when it falls below the midpoint of that channel (highest and
    lowest close of the previous ``lookback`` days). Cash until ``lookback`` closes
    precede the day.

    Raises:
        ValueError: If ``lookback`` < 2.
    """
    if lookback < 2:
        raise ValueError("lookback must be >= 2")
    state = np.zeros(len(closes))
    long = False
    for day in range(lookback, len(closes)):
        previous = closes[day - lookback : day]
        upper = float(previous.max())
        midpoint = (upper + float(previous.min())) / 2
        if not long and closes[day] > upper:
            long = True
        elif long and closes[day] < midpoint:
            long = False
        state[day] = 1.0 if long else 0.0
    return state


def volatility_scale(closes: Floats, target_vol: float, vol_window: int = 30) -> Floats:
    """
    ``min(1, target_vol / realized_vol)`` per day, 0 until ``vol_window`` returns exist.

    Realized volatility is the standard deviation of the last ``vol_window`` daily
    returns, annualized with the square root of 365. The cap at 1 keeps the position
    on spot, with no leverage.

    Raises:
        ValueError: If ``target_vol`` <= 0 or ``vol_window`` < 2.
    """
    if target_vol <= 0:
        raise ValueError("target_vol must be > 0")
    if vol_window < 2:
        raise ValueError("vol_window must be >= 2")
    scale = np.zeros(len(closes))
    returns = closes[1:] / closes[:-1] - 1.0
    for day in range(vol_window, len(closes)):
        recent = returns[day - vol_window : day]
        realized = float(recent.std(ddof=1)) * math.sqrt(TRADING_DAYS_PER_YEAR)
        scale[day] = 1.0 if realized == 0 else min(1.0, target_vol / realized)
    return scale


def donchian_positions(
    closes: Floats,
    lookbacks: tuple[int, ...],
    target_vol: float | None = None,
    vol_window: int = 30,
    rebalance_band: float = 0.10,
) -> Floats:
    """
    Donchian ensemble: the share of channels that are long, optionally vol-sized.

    The target position is the mean of ``donchian_state`` over ``lookbacks``,
    multiplied by ``volatility_scale`` when ``target_vol`` is given. To avoid paying
    fees on every small change of the size, the position only moves when the target
    differs from it by at least ``rebalance_band``, and it always goes to zero when
    the target is zero.

    Raises:
        ValueError: If ``lookbacks`` is empty or a lookback is < 2.
    """
    if not lookbacks:
        raise ValueError("lookbacks must not be empty")
    target = np.mean([donchian_state(closes, n) for n in lookbacks], axis=0)
    if target_vol is not None:
        target = target * volatility_scale(closes, target_vol, vol_window)
    positions = np.zeros(len(closes))
    held = 0.0
    for day, wanted in enumerate(target):
        if wanted == 0.0 or abs(wanted - held) >= rebalance_band:
            held = float(wanted)
        positions[day] = held
    return positions


# ---------------------------------------------------------------------------
# Simulation and metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Simulation:
    """Net daily returns of a position series over one stretch of days.

    Attributes:
        net: Daily return after costs.
        held: Position held during each day.
        traded: Absolute change of position at the close before each day.
    """

    net: Floats
    held: Floats
    traded: Floats


def simulate(
    closes: Floats,
    positions: Floats,
    costs: Costs,
    first_day: int,
    last_day: int,
) -> Simulation:
    """
    Net returns of ``positions`` over the days ``first_day`` to ``last_day``.

    Day ``i`` is the return from ``closes[i - 1]`` to ``closes[i]``, earned by
    ``positions[i - 1]``, the position decided at the close of day ``i - 1``. The
    stretch starts from cash: whatever position is held on its first day is bought
    at the previous close and pays the per-side cost, and nothing is sold at the
    end. Every change of position pays ``costs.per_side`` times its size.

    Args:
        closes: Daily closes, oldest first.
        positions: Position decided at each close, in [0, 1], same length.
        costs: Per-side costs.
        first_day: Index of the first return day, at least 1.
        last_day: Index of the last return day, inclusive.

    Raises:
        ValueError: If the lengths differ or the days are out of range.
    """
    if len(closes) != len(positions):
        raise ValueError("closes and positions must have the same length")
    if not 1 <= first_day <= last_day < len(closes):
        raise ValueError(
            f"days must satisfy 1 <= first_day <= last_day < {len(closes)}, "
            f"got {first_day} and {last_day}"
        )
    days = np.arange(first_day, last_day + 1)
    held = positions[days - 1]
    before = np.concatenate(([0.0], held[:-1]))
    traded = np.abs(held - before)
    returns = closes[days] / closes[days - 1] - 1.0
    return Simulation(
        net=held * returns - traded * costs.per_side, held=held, traded=traded
    )


@dataclass(frozen=True)
class Metrics:
    """Results on compounded returns over one stretch of days."""

    n_days: int
    total_return: float
    cagr: float
    sharpe: float
    max_drawdown: float  # negative, 0.0 when the equity never fell
    calmar: float | None  # None when there was no drawdown
    trades: int
    trades_per_year: float
    turnover_per_year: float  # sum of |change of position| per year
    exposure: float  # mean position


def compute_metrics(simulation: Simulation) -> Metrics:
    """
    CAGR, Sharpe, drawdown, Calmar, trades and exposure of a simulation.

    Sharpe is the mean over the standard deviation of the daily net returns times
    the square root of 365, with a zero risk-free rate. CAGR compounds the net
    returns. A total loss gives a CAGR of -100%.

    Raises:
        ValueError: If the simulation has no days.
    """
    net = simulation.net
    if len(net) == 0:
        raise ValueError("cannot compute metrics of an empty simulation")
    years = len(net) / TRADING_DAYS_PER_YEAR
    equity = np.cumprod(1.0 + net)
    final = float(equity[-1])
    cagr = -1.0 if final <= 0 else final ** (1 / years) - 1
    std = float(net.std(ddof=1)) if len(net) > 1 else 0.0
    sharpe = (
        0.0
        if std < FLAT_STD
        else float(net.mean()) / std * math.sqrt(TRADING_DAYS_PER_YEAR)
    )
    peak = np.maximum.accumulate(np.concatenate(([1.0], equity)))
    drawdown = float((np.concatenate(([1.0], equity)) / peak - 1.0).min())
    trades = int((simulation.traded > 1e-12).sum())
    return Metrics(
        n_days=len(net),
        total_return=final - 1.0,
        cagr=cagr,
        sharpe=sharpe,
        max_drawdown=drawdown,
        calmar=None if drawdown == 0 else cagr / abs(drawdown),
        trades=trades,
        trades_per_year=trades / years,
        turnover_per_year=float(simulation.traded.sum()) / years,
        exposure=float(simulation.held.mean()),
    )


# ---------------------------------------------------------------------------
# Deflated Sharpe ratio
# ---------------------------------------------------------------------------


def expected_max_sharpe(n_trials: int, trial_sharpe_variance: float) -> float:
    """
    Sharpe ratio the best of ``n_trials`` skill-less configurations reaches by luck.

    Bailey and López de Prado (2014). Both the variance and the result are in
    per-period (daily) units.

    Raises:
        ValueError: If ``n_trials`` < 1 or the variance is negative.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if trial_sharpe_variance < 0:
        raise ValueError("trial_sharpe_variance must be >= 0")
    if n_trials == 1:
        return 0.0
    normal = NormalDist()
    quantile = (1 - EULER_MASCHERONI) * normal.inv_cdf(1 - 1 / n_trials)
    quantile += EULER_MASCHERONI * normal.inv_cdf(1 - 1 / (n_trials * math.e))
    return math.sqrt(trial_sharpe_variance) * quantile


def deflated_sharpe_probability(
    net: Floats, n_trials: int, trial_sharpe_variance: float
) -> float:
    """
    Probability that the true Sharpe ratio beats what ``n_trials`` tries give by luck.

    Bailey and López de Prado (2014): the observed per-period Sharpe ratio is
    compared with ``expected_max_sharpe`` after adjusting for the sample length, the
    skewness and the kurtosis of the returns. Counting every configuration tried as
    a trial, independent of each other, is conservative when the configurations are
    correlated, as neighboring lookbacks are.

    Raises:
        ValueError: If fewer than 3 returns are given or they have no variance.
    """
    if len(net) < 3:
        raise ValueError("at least 3 returns are needed")
    std = float(net.std(ddof=1))
    if std < FLAT_STD:
        raise ValueError("returns have no variance")
    sharpe = float(net.mean()) / std
    centered = (net - net.mean()) / net.std(ddof=0)
    skewness = float((centered**3).mean())
    kurtosis = float((centered**4).mean())  # not excess: 3 for a normal
    benchmark = expected_max_sharpe(n_trials, trial_sharpe_variance)
    spread = 1 - skewness * sharpe + (kurtosis - 1) / 4 * sharpe**2
    z = (sharpe - benchmark) * math.sqrt(len(net) - 1) / math.sqrt(max(spread, 1e-12))
    return NormalDist().cdf(z)


# ---------------------------------------------------------------------------
# Rolling windows
# ---------------------------------------------------------------------------

WINDOW_PERCENTILES = (5, 25, 50, 75, 95)


def rolling_returns(net: Floats, window: int) -> Floats:
    """
    Compounded return of every ``window`` consecutive days, one window per day.

    Raises:
        ValueError: If ``window`` < 1.
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    if len(net) < window:
        return np.array([], dtype=np.float64)
    log_equity = np.concatenate(([0.0], np.cumsum(np.log1p(net))))
    return np.expm1(log_equity[window:] - log_equity[:-window])


@dataclass(frozen=True)
class WindowSummary:
    """Distribution of the compounded return over rolling windows of one length."""

    window: int
    n_windows: int
    percentiles: dict[int, float]  # keys are WINDOW_PERCENTILES; empty if no window
    share_negative: float | None


def summarize_windows(net: Floats, window: int) -> WindowSummary:
    """Percentiles and share of losing windows of the rolling ``window``-day returns."""
    windows = rolling_returns(net, window)
    if len(windows) == 0:
        return WindowSummary(window, 0, {}, None)
    return WindowSummary(
        window=window,
        n_windows=len(windows),
        percentiles={p: float(np.percentile(windows, p)) for p in WINDOW_PERCENTILES},
        share_negative=float((windows < 0).mean()),
    )
