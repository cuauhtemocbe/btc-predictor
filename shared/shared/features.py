"""
Return-based features and targets for next-day prediction.

The single builder used by the daily trainer, the daily predictor
and the backtest (#106). Models are trained on log returns, not on
price levels, and the predicted price is ``last close * exp(predicted return)``.

For the day at index ``t`` of a daily series, with window ``W``, the features are
(``2 * W + 1`` columns, see ``feature_count``):

- the last ``W`` daily log returns of the close, ``ln(close[i] / close[i-1])``
- the rolling volatility: the standard deviation of those ``W`` returns
- the last ``W`` daily log volume changes, ``ln(volume[i] / volume[i-1])``

and the target is the log return over the next ``horizon_days`` days (the sum of
the next ``horizon_days`` daily log returns). Features of day ``t`` read only
rows ``t - W .. t``, so they carry no future data.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import numpy as np
import numpy.typing as npt
from numpy.lib.stride_tricks import sliding_window_view

Number = Decimal | float | int | None
Series = Sequence[Number] | npt.NDArray[np.float64]

# Target stored in models.params["target"] so a predictor can tell a model trained
# on returns from one trained on price levels.
LOG_RETURN_TARGET = "log_return"


@dataclass(frozen=True)
class FeatureSet:
    """Training samples built from one daily series.

    Attributes:
        X: Feature matrix of shape (n_samples, feature_count(window_days)).
        y: Target log return over the horizon, shape (n_samples,).
        base_close: Close of the day each sample was built at, shape (n_samples,).
            ``base_close * exp(y)`` is the price the target corresponds to.
    """

    X: npt.NDArray[np.float64]
    y: npt.NDArray[np.float64]
    base_close: npt.NDArray[np.float64]


@dataclass(frozen=True)
class DailySeries:
    """Bar dates, closes and volumes of one symbol, oldest to newest, same length."""

    dates: list[date]
    closes: list[Decimal]
    volumes: list[Decimal]

    def __len__(self) -> int:
        return len(self.closes)


def require_recent_close(last_bar: date, now: datetime, max_age: timedelta) -> None:
    """
    Refuse to predict from a bar that closed too long ago (#175).

    The bar dated ``last_bar`` closes at 00:00 UTC of the next day, and the
    prediction is anchored to that close. The pnl columns assume a position
    opened at that price, so the job has to run right after it.

    Args:
        last_bar: Date (UTC day) of the last stored bar
        now: The instant the job runs at, timezone-aware
        max_age: Oldest acceptable time since the bar's close

    Raises:
        ValueError: If the bar closed more than ``max_age`` before ``now``.
    """
    closed_at = datetime.combine(last_bar + timedelta(days=1), time.min, tzinfo=UTC)
    age = now - closed_at
    if age > max_age:
        raise ValueError(
            f"Last bar ({last_bar}) closed at {closed_at:%Y-%m-%d %H:%M} UTC, "
            f"{age} ago; the maximum age is {max_age}, so the price the "
            "prediction is anchored to is stale"
        )


def require_fresh_series(dates: Sequence[date], today: date) -> None:
    """
    Refuse a series that is stale or has gaps, before features are built from it.

    A prediction made at 00:10 UTC on ``today`` needs the bar of ``today - 1`` as
    its last bar, and one bar per day before it. Otherwise a return silently
    spans several days and is scored as a one-day move (#174).

    Production entry points call this (predictors and trainers); the backtest
    builds its windows from history with its own clock and does not.

    Args:
        dates: Bar dates (UTC days), oldest to newest
        today: The UTC day the job runs on

    Raises:
        ValueError: If the series is empty, its last bar is not dated
            ``today - 1``, or a day is missing between its first and last bar;
            the message names the missing dates.
    """
    expected_last = today - timedelta(days=1)
    if not dates:
        raise ValueError(f"No stored bars: expected one dated {expected_last}")

    present = set(dates)
    first, last = dates[0], max(dates)
    span_end = max(last, expected_last)
    missing = [
        first + timedelta(days=offset)
        for offset in range((span_end - first).days + 1)
        if first + timedelta(days=offset) not in present
    ]
    if last != expected_last or missing:
        listed = ", ".join(d.isoformat() for d in missing) or "none"
        raise ValueError(
            f"Stale or incomplete series: latest bar is dated {last}, expected "
            f"{expected_last}; missing bar date(s): {listed}"
        )


def feature_count(window_days: int) -> int:
    """Feature columns for a window: W returns, volatility, W volume changes."""
    return 2 * window_days + 1


def required_history_days(window_days: int, horizon_days: int = 0) -> int:
    """
    Daily rows needed to build features.

    ``window_days + 1`` closes give ``window_days`` returns. Each training sample
    also needs ``horizon_days`` more rows for its target (0 when only predicting).
    """
    return window_days + 1 + horizon_days


def _positive_series(values: Series, name: str) -> npt.NDArray[np.float64]:
    """Convert to floats, rejecting missing, non-finite, zero or negative values."""
    series = np.array(
        [np.nan if v is None else float(v) for v in values], dtype=np.float64
    )
    invalid = ~np.isfinite(series) | (series <= 0)
    if invalid.any():
        rows = np.flatnonzero(invalid)[:5].tolist()
        raise ValueError(
            f"Invalid {name} values at row(s) {rows}: every {name} must be a "
            f"finite number > 0 (missing, zero and negative values are rejected)"
        )
    return series


def _validated_series(
    closes: Series,
    volumes: Series,
    window_days: int,
    horizon_days: int,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    if window_days < 1:
        raise ValueError("window_days must be >= 1")
    if horizon_days < 0:
        raise ValueError("horizon_days must be >= 0")
    if len(closes) != len(volumes):
        raise ValueError(
            f"closes and volumes must have the same length, "
            f"got {len(closes)} and {len(volumes)}"
        )

    required = required_history_days(window_days, horizon_days)
    if len(closes) < required:
        raise ValueError(
            f"Insufficient history: need {required} daily rows "
            f"(window={window_days}d, horizon={horizon_days}d), have {len(closes)}"
        )

    return _positive_series(closes, "close"), _positive_series(volumes, "volume")


def _feature_matrix(
    closes: npt.NDArray[np.float64],
    volumes: npt.NDArray[np.float64],
    window_days: int,
) -> npt.NDArray[np.float64]:
    """
    Features of every day from index ``window_days`` to the last one.

    Row ``k`` is the day at index ``k + window_days`` and reads only rows
    ``k .. k + window_days`` of the inputs.
    """
    returns = np.diff(np.log(closes))
    volume_changes = np.diff(np.log(volumes))

    lagged_returns = sliding_window_view(returns, window_days)
    lagged_volume = sliding_window_view(volume_changes, window_days)
    volatility = lagged_returns.std(axis=1)

    return np.hstack([lagged_returns, volatility[:, None], lagged_volume])


def build_training_set(
    closes: Series,
    volumes: Series,
    window_days: int,
    horizon_days: int = 1,
) -> FeatureSet:
    """
    Build every (features, target) sample of a daily series, oldest to newest.

    Args:
        closes: Daily close prices, oldest to newest
        volumes: Daily volumes, same length as ``closes``
        window_days: Days of returns and volume changes per sample
        horizon_days: Days ahead of the target: 1 for the daily worker.
            The target is the sum of the next ``horizon_days`` daily log returns.

    Returns:
        FeatureSet with ``len(closes) - window_days - horizon_days`` samples

    Raises:
        ValueError: If there are fewer than ``window_days + 1 + horizon_days`` rows
            (the message names the required and available days), or if a close or
            volume is missing, zero, negative or not finite.
    """
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1 to build targets")

    close, volume = _validated_series(closes, volumes, window_days, horizon_days)

    n_samples = len(close) - window_days - horizon_days
    X = _feature_matrix(close, volume, window_days)[:n_samples]

    returns = np.diff(np.log(close))
    forward_return = sliding_window_view(returns, horizon_days).sum(axis=1)
    y = forward_return[window_days : window_days + n_samples]
    base_close = close[window_days : window_days + n_samples]

    return FeatureSet(X=X, y=y, base_close=base_close)


def build_prediction_features(
    closes: Series,
    volumes: Series,
    window_days: int,
) -> npt.NDArray[np.float64]:
    """
    Build the features of the most recent day, shape ``(1, feature_count)``.

    Uses the same code as ``build_training_set``, on the last ``window_days + 1``
    rows. Extra older rows are ignored.

    Raises:
        ValueError: Same cases as ``build_training_set`` (horizon 0).
    """
    close, volume = _validated_series(closes, volumes, window_days, 0)
    tail = window_days + 1
    return _feature_matrix(close[-tail:], volume[-tail:], window_days)


def price_from_return(last_close: Number, predicted_return: float) -> float:
    """Predicted price: ``last_close * exp(predicted_return)``."""
    if last_close is None:
        raise ValueError("last_close is required")
    return float(last_close) * math.exp(predicted_return)
