"""
Trivial baselines to compare every model against (#105).

A model that does not beat "always up" or "same direction as yesterday" adds no
value, so every reported accuracy and PnL is shown next to these baselines, over
exactly the days the model was evaluated on:

- **always-up**: predicts UP every day. Its simple-strategy PnL (long 1 BTC every
  day) telescopes to the buy-and-hold PnL of the period.
- **persistence**: predicts tomorrow's direction is today's, i.e. UP iff
  ``price_at_prediction >= previous_close`` (close of the day before).
- **buy-and-hold**: last ``actual_price`` minus first ``price_at_prediction``.

Directions follow the evaluator rule (``workers/daily/evaluator.py``): the actual
direction is UP iff ``actual_price >= price_at_prediction`` (flat counts as UP);
a model predicts UP iff ``predicted_price > price_at_prediction``. PnL is per 1 BTC
in USDT, like ``shared.utils.calculate_pnl``.

The edge over the best baseline comes with its sample size and a one-sided
binomial-test p-value. It is an approximation: it takes the best baseline's
accuracy as a fixed null probability and does not account for having picked the
best of two baselines.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

DEFAULT_SIGNIFICANCE_LEVEL = 0.05

ALWAYS_UP = "always_up"
PERSISTENCE = "persistence"


@dataclass(frozen=True)
class EvaluatedDay:
    """One day a model was evaluated on.

    Attributes:
        predicted_for: Day the prediction is for (D).
        previous_close: Close of D-2, or None when it is not available. Days without
            it are left out of the persistence baseline only.
        price_at_prediction: Close of D-1, the price the prediction was made at.
        actual_price: Close of D.
        predicted_price: The model's prediction for D, or None when only the
            baselines are scored.
    """

    predicted_for: date
    previous_close: Decimal | None
    price_at_prediction: Decimal
    actual_price: Decimal
    predicted_price: Decimal | None = None


@dataclass(frozen=True)
class BaselineReport:
    """Baselines and the model's edge over them for one set of evaluated days.

    Every metric is None when it cannot be computed (no days, no previous close,
    a missing prediction): unavailable, never zero.
    """

    n_days: int
    always_up_accuracy: float | None
    persistence_accuracy: float | None
    persistence_n_days: int
    always_up_pnl: Decimal | None
    persistence_pnl: Decimal | None
    buy_and_hold_pnl: Decimal | None
    best_baseline: str | None
    model_accuracy: float | None
    edge: float | None
    p_value: float | None
    significant: bool | None


def binomial_tail_probability(successes: int, trials: int, p: float) -> float:
    """
    One-sided binomial p-value, ``P(X >= successes)`` for ``X ~ Binomial(trials, p)``.

    Summed in log space so it stays accurate for thousands of trials.
    """
    if successes <= 0:
        return 1.0
    if successes > trials:
        return 0.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0

    log_p = math.log(p)
    log_q = math.log1p(-p)
    log_n_factorial = math.lgamma(trials + 1)
    log_terms = [
        log_n_factorial
        - math.lgamma(i + 1)
        - math.lgamma(trials - i + 1)
        + i * log_p
        + (trials - i) * log_q
        for i in range(successes, trials + 1)
    ]
    peak = max(log_terms)
    total = peak + math.log(sum(math.exp(term - peak) for term in log_terms))
    return min(1.0, math.exp(total))


def _actual_up(day: EvaluatedDay) -> bool:
    return day.actual_price >= day.price_at_prediction


def _model_correct(day: EvaluatedDay) -> bool | None:
    if day.predicted_price is None:
        return None
    predicted_up = day.predicted_price > day.price_at_prediction
    return predicted_up == _actual_up(day)


def evaluate_baselines(
    days: Sequence[EvaluatedDay],
    significance_level: float = DEFAULT_SIGNIFICANCE_LEVEL,
) -> BaselineReport:
    """
    Score the baselines, and the model when it has predictions, over ``days``.

    Args:
        days: The evaluated days, in any order (sorted by ``predicted_for``).
        significance_level: Threshold the p-value is compared to for ``significant``.

    Returns:
        A BaselineReport; all metrics are None when ``days`` is empty.
    """
    ordered = sorted(days, key=lambda d: d.predicted_for)
    n_days = len(ordered)
    if n_days == 0:
        return BaselineReport(
            n_days=0,
            always_up_accuracy=None,
            persistence_accuracy=None,
            persistence_n_days=0,
            always_up_pnl=None,
            persistence_pnl=None,
            buy_and_hold_pnl=None,
            best_baseline=None,
            model_accuracy=None,
            edge=None,
            p_value=None,
            significant=None,
        )

    always_up_accuracy = sum(_actual_up(d) for d in ordered) / n_days
    always_up_pnl = sum(
        (d.actual_price - d.price_at_prediction for d in ordered), Decimal(0)
    )
    buy_and_hold_pnl = ordered[-1].actual_price - ordered[0].price_at_prediction

    scored = [d for d in ordered if d.previous_close is not None]
    persistence_accuracy: float | None = None
    persistence_pnl: Decimal | None = None
    if scored:
        persistence_up = [
            d.price_at_prediction >= d.previous_close  # type: ignore[operator]
            for d in scored
        ]
        persistence_accuracy = sum(
            up == _actual_up(d) for up, d in zip(persistence_up, scored, strict=True)
        ) / len(scored)
        persistence_pnl = sum(
            (
                d.actual_price - d.price_at_prediction
                for up, d in zip(persistence_up, scored, strict=True)
                if up
            ),
            Decimal(0),
        )

    best_baseline, best_accuracy = ALWAYS_UP, always_up_accuracy
    if persistence_accuracy is not None and persistence_accuracy > best_accuracy:
        best_baseline, best_accuracy = PERSISTENCE, persistence_accuracy

    model_accuracy: float | None = None
    edge: float | None = None
    p_value: float | None = None
    significant: bool | None = None
    outcomes = [_model_correct(d) for d in ordered]
    if all(outcome is not None for outcome in outcomes):
        correct = sum(bool(outcome) for outcome in outcomes)
        model_accuracy = correct / n_days
        edge = model_accuracy - best_accuracy
        p_value = binomial_tail_probability(correct, n_days, best_accuracy)
        significant = p_value < significance_level

    return BaselineReport(
        n_days=n_days,
        always_up_accuracy=always_up_accuracy,
        persistence_accuracy=persistence_accuracy,
        persistence_n_days=len(scored),
        always_up_pnl=always_up_pnl,
        persistence_pnl=persistence_pnl,
        buy_and_hold_pnl=buy_and_hold_pnl,
        best_baseline=best_baseline,
        model_accuracy=model_accuracy,
        edge=edge,
        p_value=p_value,
        significant=significant,
    )
