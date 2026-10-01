"""
Walk-forward backtest engine with production-code parity (#106).

For every day D of the range it trains on the daily rows dated before D (an
expanding window, like the daily worker), predicts D's close and stores the
result in ``backtest_results``. There is no feature or model code of its own: it
calls the builders in ``shared.features`` and the model factory in
``workers.daily.models.factory``, the same code the daily trainer and predictor
run.

The price series is loaded once and sliced in memory, so a day's training data can
only contain rows dated before it. Nothing is written unless the whole run
succeeds, and a start date without enough history fails before any work.
"""

import logging
import random
import sys
from bisect import bisect_left
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared.config import settings
from shared.db.models import DEFAULT_SYMBOL, BacktestResult, Price
from shared.features import (
    LOG_RETURN_TARGET,
    build_prediction_features,
    build_training_set,
    feature_count,
    price_from_return,
)
from shared.utils import (
    calculate_pnl,
    calculate_pnl_long_short,
    calculate_pnl_realistic,
    calculate_pnl_threshold,
)
from workers.daily.models.base import BaseModel
from workers.daily.models.factory import build_model, model_class_for
from workers.daily.trainer import required_training_days

logger = logging.getLogger(__name__)

PROGRESS_EVERY_DAYS = 10
PRICE_QUANTUM = Decimal("0.01")  # backtest_results prices are NUMERIC(15, 2)
DEFAULT_SEED = 42


class InsufficientHistoryError(ValueError):
    """The loaded history is too short for the requested start date."""


@dataclass(frozen=True)
class BacktestConfig:
    """Parameters of one walk-forward run.

    Attributes:
        model_name: Model family: linear, xgboost, lstm or arima.
        window_days: Sliding-window size of the features.
        start_date: First day predicted.
        end_date: Last day predicted (inclusive).
        symbol: Asset whose daily prices are backtested.
        seed: Seeds ``random``, ``numpy`` and TensorFlow before every training, so
            the same run stores the same predictions.
        retrain_every: The model is retrained every this many days and reused in
            between; the features are rebuilt every day. Part of the report.
    """

    model_name: str
    window_days: int
    start_date: date
    end_date: date
    symbol: str = DEFAULT_SYMBOL
    seed: int = DEFAULT_SEED
    retrain_every: int = 1

    @staticmethod
    def default_window() -> int:
        """The window production trains with (``settings.training_window_days``)."""
        return settings.training_window_days


@dataclass
class BacktestStats:
    """Counters of one run."""

    total_days: int = 0
    predictions: int = 0
    skipped_no_actual: int = 0
    skipped_training_failed: int = 0


@dataclass(frozen=True)
class DailyHistory:
    """One close and volume per day of one symbol, oldest to newest."""

    dates: list[date]
    closes: list[Decimal]
    volumes: list[Decimal]


def load_daily_history(db: Session, symbol: str = DEFAULT_SYMBOL) -> DailyHistory:
    """
    Load every stored daily row of ``symbol`` with one query.

    Same aggregation as ``trainer.fetch_training_data``: the latest row of each day
    supplies that day's close and volume.
    """
    latest_per_day = (
        select(
            func.date_trunc("day", Price.timestamp).label("day"),
            func.max(Price.timestamp).label("latest_timestamp"),
        )
        .where(Price.symbol == symbol)
        .group_by("day")
        .subquery()
    )
    rows = db.execute(
        select(latest_per_day.c.day, Price.close, Price.volume)
        .join(latest_per_day, Price.timestamp == latest_per_day.c.latest_timestamp)
        .where(Price.symbol == symbol)
        .order_by(latest_per_day.c.day)
    ).all()
    return DailyHistory(
        dates=[row.day.date() for row in rows],
        closes=[row.close for row in rows],
        volumes=[row.volume for row in rows],
    )


def check_enough_history(history: DailyHistory, config: BacktestConfig) -> None:
    """
    Fail when fewer rows than a production training run needs precede the start.

    Raises:
        InsufficientHistoryError: Naming the earliest start date that has enough
            history, the first loaded day and the window.
    """
    needed = required_training_days(config.window_days)
    if not history.dates:
        raise InsufficientHistoryError(
            f"No {config.symbol} prices are loaded; load history first "
            f"(scripts/load_binance_history.py)"
        )
    available = bisect_left(history.dates, config.start_date)
    if available >= needed:
        return
    if len(history.dates) > needed:
        earliest = f"the earliest allowed start date is {history.dates[needed]}"
    else:
        earliest = (
            f"{len(history.dates)} days are loaded, so no start date has enough history"
        )
    raise InsufficientHistoryError(
        f"Start date {config.start_date} has only {available} daily rows before it "
        f"but {config.symbol} needs {needed} (window={config.window_days}d): "
        f"{earliest} (first loaded day {history.dates[0]})"
    )


def seed_everything(seed: int) -> None:
    """Seed the global RNGs the models draw from (TensorFlow only if it is loaded)."""
    random.seed(seed)
    np.random.seed(seed)
    tensorflow = sys.modules.get("tensorflow")
    if tensorflow is not None:
        tensorflow.random.set_seed(seed)


def _midnight(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC)


def run_walk_forward(
    db: Session, config: BacktestConfig, backtest_run_id: UUID
) -> BacktestStats:
    """
    Run the walk-forward backtest and store one ``backtest_results`` row per day.

    Args:
        db: Database session; the rows are added and committed once, at the end.
        config: Run parameters.
        backtest_run_id: Identifies this run's rows.

    Returns:
        Counters of the run.

    Raises:
        ValueError: Invalid dates or an unknown model name.
        InsufficientHistoryError: Not enough history before ``config.start_date``.
    """
    if config.start_date > config.end_date:
        raise ValueError(
            f"start date must be before or equal to end date "
            f"({config.start_date} > {config.end_date})"
        )
    if config.retrain_every < 1:
        raise ValueError(f"retrain_every must be >= 1 (got {config.retrain_every})")
    model_class_for(config.model_name)  # unknown names fail before any work

    history = load_daily_history(db, config.symbol)
    check_enough_history(history, config)

    stats = BacktestStats()
    results: list[BacktestResult] = []
    model: BaseModel | None = None
    trained_on_day = 0  # index of the day (0 = start date) the model was trained on
    trained_samples = 0
    train_to = config.start_date
    day = config.start_date
    while day <= config.end_date:
        stats.total_days += 1
        if stats.total_days % PROGRESS_EVERY_DAYS == 0:
            logger.info(f"Backtesting day {stats.total_days} ({day})")

        end = bisect_left(history.dates, day)  # rows dated before `day`
        actual_index = (
            end if end < len(history.dates) and history.dates[end] == day else None
        )
        if actual_index is None:
            logger.warning(f"Skipping {day}: no actual price")
            stats.skipped_no_actual += 1
            day += timedelta(days=1)
            continue

        closes, volumes = history.closes[:end], history.volumes[:end]
        day_index = stats.total_days - 1
        try:
            if model is None or day_index - trained_on_day >= config.retrain_every:
                training_set = build_training_set(
                    closes, volumes, config.window_days, horizon_days=1
                )
                candidate = build_model(
                    config.model_name,
                    config.window_days,
                    feature_count(config.window_days),
                )
                seed_everything(config.seed)
                candidate.train(training_set.X, training_set.y)
                model, trained_on_day = candidate, day_index
                trained_samples = len(training_set.y)
                train_to = history.dates[end - 1]
            predicted_return = model.predict(
                build_prediction_features(closes, volumes, config.window_days)
            )
        except ValueError as error:
            logger.warning(f"Skipping {day}: training failed - {error}")
            stats.skipped_training_failed += 1
            day += timedelta(days=1)
            continue

        price_at_prediction = closes[-1]
        predicted_price = Decimal(
            str(price_from_return(price_at_prediction, predicted_return))
        ).quantize(PRICE_QUANTUM)
        actual_price = history.closes[actual_index]
        results.append(
            BacktestResult(
                backtest_run_id=backtest_run_id,
                predicted_for=day,
                predicted_at=_midnight(history.dates[end - 1]),
                price_at_prediction=price_at_prediction,
                predicted_price=predicted_price,
                actual_price=actual_price,
                pnl_simple=calculate_pnl(
                    predicted_price, price_at_prediction, actual_price
                ),
                pnl_long_short=calculate_pnl_long_short(
                    predicted_price, price_at_prediction, actual_price
                ),
                pnl_threshold=calculate_pnl_threshold(
                    predicted_price, price_at_prediction, actual_price
                ),
                pnl_realistic=calculate_pnl_realistic(
                    predicted_price, price_at_prediction, actual_price
                ),
                model_params={
                    "model_name": config.model_name,
                    "window_days": config.window_days,
                    "target": LOG_RETURN_TARGET,
                    "seed": config.seed,
                    "retrain_every": config.retrain_every,
                    "train_from": history.dates[0].isoformat(),
                    "train_to": train_to.isoformat(),
                    "training_samples": trained_samples,
                },
            )
        )
        stats.predictions += 1
        day += timedelta(days=1)

    db.add_all(results)
    db.commit()
    logger.info(f"Stored {len(results)} backtest results for run {backtest_run_id}")
    return stats
