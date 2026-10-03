#!/usr/bin/env python3
"""
Spike #109: is intraday (1h / 15m) prediction worth pursuing?

Runs the production recipe (``shared.features`` log-return features, Linear
regression, expanding training window, walk-forward) on BTCUSDT klines of any
interval, so 1d, 1h and 15m are compared on the same days, the same code and the
same baselines. Nothing is written to the database: klines are downloaded from
data.binance.vision into a cache directory (SHA256-verified) and kept in memory.

Per interval it reports, over the validation and test slices:

- direction accuracy of the model, always-up and persistence, the edge over the
  best baseline and its binomial p-value (``shared.baselines``)
- long-only strategy return per interval, before and after fees, where the model
  is long while it predicts UP and flat otherwise, paying ``--fee-pct`` on every
  position change (entry or exit); buy-and-hold and persistence use the same rule
- the training cost (rows, seconds per fit, whole-run seconds) and storage cost

Usage:
    python scripts/spike_intraday.py --intervals 1d 1h 15m
"""

import argparse
import hashlib
import io
import logging
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt
from sklearn.linear_model import LinearRegression

from shared.baselines import binomial_tail_probability
from shared.binance_vision import (
    BinanceVisionError,
    HttpStatusError,
    http_get,
    last_closed_month,
    months_between,
)
from shared.features import build_training_set

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
SYMBOL = "BTCUSDT"
# Training rows between refits per interval: one refit per day, like production.
RETRAIN_EVERY = {"1d": 1, "1h": 24, "15m": 96}
PERIODS_PER_YEAR = {"1d": 365, "1h": 24 * 365, "15m": 96 * 365}
BYTES_PER_ROW = 210  # pg_total_relation_size('prices') / row count, dev database


@dataclass(frozen=True)
class Klines:
    """Open times (epoch seconds), closes and volumes of one interval, oldest first."""

    open_time: npt.NDArray[np.int64]
    close: npt.NDArray[np.float64]
    volume: npt.NDArray[np.float64]


@dataclass(frozen=True)
class StrategyResult:
    """Long-only strategy over one slice."""

    total_return_gross: float
    total_return_net: float
    trades: int
    periods_long: int
    gross_bps_per_entry: float | None


@dataclass(frozen=True)
class SliceResult:
    """Model and baselines over one slice of one interval."""

    n: int
    model_accuracy: float
    always_up_accuracy: float
    persistence_accuracy: float
    best_baseline: str
    edge_pp: float
    p_value: float
    model: StrategyResult
    always_up: StrategyResult
    persistence: StrategyResult


def _download(url: str, cache_dir: Path) -> bytes | None:
    """Download a monthly zip (cached, checksum-verified); None when it is missing."""
    target = cache_dir / url.rsplit("/", 1)[1]
    if target.exists():
        return target.read_bytes()
    try:
        body = http_get(url)
        checksum = http_get(url + ".CHECKSUM").decode().split()[0]
    except HttpStatusError as exc:
        if exc.status == 404:
            return None
        raise
    if hashlib.sha256(body).hexdigest() != checksum:
        raise BinanceVisionError(f"Checksum mismatch for {url}")
    target.write_bytes(body)
    return body


def _parse(archive: bytes) -> list[tuple[int, float, float]]:
    """(open time in seconds, close, volume) of every row of a monthly zip."""
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        text = zf.read(zf.namelist()[0]).decode()
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split(",")
        opened = int(fields[0])
        seconds = opened // 1_000_000 if opened >= 10**14 else opened // 1_000
        rows.append((seconds, float(fields[4]), float(fields[5])))
    return rows


def load_klines(interval: str, first: date, last: date, cache_dir: Path) -> Klines:
    """Every kline of ``interval``, from the month of ``first`` to that of ``last``."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[int, float, float]] = []
    for year, month in months_between(
        (first.year, first.month), (last.year, last.month)
    ):
        url = (
            f"{BASE_URL}/{SYMBOL}/{interval}/{SYMBOL}-{interval}-{year}-{month:02d}.zip"
        )
        archive = _download(url, cache_dir)
        if archive is None:
            raise BinanceVisionError(f"Missing month file: {url}")
        rows.extend(_parse(archive))
    rows.sort()
    times = np.array([r[0] for r in rows], dtype=np.int64)
    close = np.array([r[1] for r in rows], dtype=np.float64)
    volume = np.array([r[2] for r in rows], dtype=np.float64)
    keep = (volume > 0) & (close > 0)  # the log-return features need positive values
    dropped = int((~keep).sum())
    if dropped:
        logger.info("%s: dropped %d rows with zero volume", interval, dropped)
    return Klines(times[keep], close[keep], volume[keep])


def _strategy(
    position: npt.NDArray[np.bool_],
    period_return: npt.NDArray[np.float64],
    fee: float,
) -> StrategyResult:
    """Long-only strategy: fee on every position change, entry from flat included."""
    held = position.astype(np.float64)
    previous = np.concatenate([[0.0], held[:-1]])
    changes = np.abs(held - previous)
    gross = held * period_return
    net = gross - changes * fee
    entries = int(((held == 1.0) & (previous == 0.0)).sum())
    periods_long = int(held.sum())
    return StrategyResult(
        total_return_gross=float(np.prod(1.0 + gross) - 1.0),
        total_return_net=float(np.prod(1.0 + net) - 1.0),
        trades=entries,
        periods_long=periods_long,
        gross_bps_per_entry=(float(gross.sum() * 1e4 / entries) if entries else None),
    )


def _slice_result(
    predicted_up: npt.NDArray[np.bool_],
    actual: npt.NDArray[np.float64],
    base: npt.NDArray[np.float64],
    previous: npt.NDArray[np.float64],
    fee: float,
) -> SliceResult:
    """Score one slice: ``base`` is the close predicted at, ``actual`` the next one."""
    actual_up = actual >= base  # evaluator rule: flat counts as UP
    n = len(base)
    persistence_up = base >= previous
    always_up = np.ones(n, dtype=bool)

    def accuracy(direction: npt.NDArray[np.bool_]) -> float:
        return float((direction == actual_up).mean())

    model_acc = accuracy(predicted_up)
    baselines = {
        "always_up": accuracy(always_up),
        "persistence": accuracy(persistence_up),
    }
    best = max(baselines, key=lambda name: baselines[name])
    p_value = binomial_tail_probability(
        int((predicted_up == actual_up).sum()), n, baselines[best]
    )
    period_return = actual / base - 1.0
    return SliceResult(
        n=n,
        model_accuracy=model_acc,
        always_up_accuracy=baselines["always_up"],
        persistence_accuracy=baselines["persistence"],
        best_baseline=best,
        edge_pp=(model_acc - baselines[best]) * 100,
        p_value=p_value,
        model=_strategy(predicted_up, period_return, fee),
        always_up=_strategy(always_up, period_return, fee),
        persistence=_strategy(persistence_up, period_return, fee),
    )


@dataclass(frozen=True)
class IntervalResult:
    """Everything the spike reports for one interval."""

    interval: str
    rows: int
    first_day: date
    last_day: date
    train_rows: int
    fit_seconds: float
    run_seconds: float
    refits: int
    validation: SliceResult
    test: SliceResult


def run_interval(
    interval: str, klines: Klines, window: int, test_start: datetime, fee: float
) -> IntervalResult:
    """Walk-forward Linear model on one interval, like the production backtest."""
    started = time.perf_counter()
    training = build_training_set(klines.close, klines.volume, window)
    n_samples = len(training.y)
    # Sample s is row s + window; it predicts the close of row s + window + 1
    sample_time = klines.open_time[window : window + n_samples]
    base = training.base_close
    actual = klines.close[window + 1 : window + 1 + n_samples]
    previous = klines.close[window - 1 : window - 1 + n_samples]

    test_from = int(np.searchsorted(sample_time, int(test_start.timestamp())))
    first_predicted = 1000  # let the first model see at least this many samples
    retrain_every = RETRAIN_EVERY[interval]
    predicted_return = np.empty(n_samples)
    predicted_return[:] = np.nan
    fits = 0
    fit_seconds = 0.0
    for start in range(first_predicted, n_samples, retrain_every):
        # The target of sample s is known once row s + window + 1 has closed, i.e.
        # by the time sample s + 1 is predicted: train on samples before ``start``.
        fit_started = time.perf_counter()
        model = LinearRegression().fit(training.X[:start], training.y[:start])
        fit_seconds += time.perf_counter() - fit_started
        fits += 1
        stop = min(start + retrain_every, n_samples)
        predicted_return[start:stop] = model.predict(training.X[start:stop])

    valid = ~np.isnan(predicted_return)
    predicted_up = (np.exp(predicted_return) * base) > base  # production rule
    idx = np.arange(n_samples)
    slices = {}
    for name, mask in (
        ("validation", valid & (idx < test_from)),
        ("test", valid & (idx >= test_from)),
    ):
        slices[name] = _slice_result(
            predicted_up[mask], actual[mask], base[mask], previous[mask], fee
        )

    return IntervalResult(
        interval=interval,
        rows=len(klines.close),
        first_day=datetime.fromtimestamp(int(klines.open_time[0]), tz=UTC).date(),
        last_day=datetime.fromtimestamp(int(klines.open_time[-1]), tz=UTC).date(),
        train_rows=n_samples,
        fit_seconds=fit_seconds / fits,
        run_seconds=time.perf_counter() - started,
        refits=fits,
        validation=slices["validation"],
        test=slices["test"],
    )


def format_result(result: IntervalResult, fee: float) -> str:
    """Human-readable report of one interval."""
    lines = [
        f"== {result.interval}: {result.rows:,} rows "
        f"({result.first_day} to {result.last_day}), "
        f"~{result.rows * BYTES_PER_ROW / 1e6:.1f} MB in Postgres ==",
        f"  Fit: {result.fit_seconds * 1000:.0f} ms per fit on up to "
        f"{result.train_rows:,} samples, {result.refits:,} refits, "
        f"{result.run_seconds:.1f} s for the whole walk-forward",
    ]
    for label, part in (("test", result.test), ("validation", result.validation)):
        lines += [
            f"  -- {label} slice, {part.n:,} predictions --",
            f"  accuracy: model {part.model_accuracy:.2%}  "
            f"always-up {part.always_up_accuracy:.2%}  "
            f"persistence {part.persistence_accuracy:.2%}",
            f"  edge over best baseline ({part.best_baseline}): "
            f"{part.edge_pp:+.2f} pp, p = {part.p_value:.4f}",
        ]
        for name, strat in (
            ("model", part.model),
            ("always-up", part.always_up),
            ("persistence", part.persistence),
        ):
            per_entry = (
                f"{strat.gross_bps_per_entry:+.1f} bps gross per entry"
                if strat.gross_bps_per_entry is not None
                else "never long"
            )
            lines.append(
                f"  {name:<12} return gross {strat.total_return_gross:+.1%}  "
                f"net of {fee:.2%}/side {strat.total_return_net:+.1%}  "
                f"entries {strat.trades:,}, long {strat.periods_long:,} periods  "
                f"({per_entry})"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Intraday prediction spike (#109)")
    parser.add_argument("--intervals", nargs="+", default=["1d", "1h"])
    parser.add_argument("--start", default="2019-01-01", help="first day of data")
    parser.add_argument("--end", default="2026-08-31", help="last day of data")
    parser.add_argument("--test-start", default="2024-01-01")
    parser.add_argument("--window", type=int, default=21)
    parser.add_argument("--fee-pct", type=float, default=0.1, help="per side, in %%")
    parser.add_argument("--cache-dir", default="/tmp/spike_intraday_cache")  # noqa: S108
    args = parser.parse_args(argv)

    first = date.fromisoformat(args.start)
    last = date.fromisoformat(args.end)
    test_start = datetime.fromisoformat(args.test_start).replace(tzinfo=UTC)
    if (last.year, last.month) > last_closed_month(date.today()):
        logger.warning("--end is after the last closed month; the file will be missing")
    fee = args.fee_pct / 100

    for interval in args.intervals:
        if interval not in RETRAIN_EVERY:
            logger.error(
                "Unsupported interval %s (use %s)", interval, list(RETRAIN_EVERY)
            )
            return 1
        klines = load_klines(interval, first, last, Path(args.cache_dir))
        result = run_interval(interval, klines, args.window, test_start, fee)
        print(format_result(result, fee))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
