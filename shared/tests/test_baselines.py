"""
Tests for the baseline comparison (#105).

Each test maps to a Gherkin scenario of issue #105 ("Baseline comparison"), except
the ones under "Implementation details", which pin behaviour the spec adds.
"""

import math
from datetime import date, timedelta
from decimal import Decimal

import pytest

from shared.baselines import EvaluatedDay, evaluate_baselines

START = date(2024, 1, 1)


def days_from_directions(
    directions: str,
    *,
    predicted: str | None = None,
    start_price: Decimal = Decimal("100"),
) -> list[EvaluatedDay]:
    """
    Build evaluated days from a string of daily directions ("U"/"D").

    Day ``i`` moves from ``price_at_prediction`` to ``actual_price`` in the given
    direction. The first day has no ``previous_close`` (no direction precedes it);
    every later day's ``previous_close`` is the close before ``price_at_prediction``.
    ``predicted`` optionally gives the model's direction per day.
    """
    days: list[EvaluatedDay] = []
    previous_close: Decimal | None = None
    price = start_price
    for i, direction in enumerate(directions):
        actual = price + 1 if direction == "U" else price - 1
        predicted_price = None
        if predicted is not None:
            predicted_price = price + 1 if predicted[i] == "U" else price - 1
        days.append(
            EvaluatedDay(
                predicted_for=START + timedelta(days=i),
                previous_close=previous_close,
                price_at_prediction=price,
                actual_price=actual,
                predicted_price=predicted_price,
            )
        )
        previous_close, price = price, actual
    return days


def binomial_tail(k: int, n: int, p: float) -> float:
    """Reference one-sided p-value P(X >= k), X ~ Binomial(n, p), via scipy."""
    scipy_stats = pytest.importorskip("scipy.stats")
    return float(scipy_stats.binomtest(k, n, p, alternative="greater").pvalue)


# --- Scenario: Baselines are computed over the same evaluated days as the model ---


def test_baselines_cover_exactly_the_evaluated_days():
    # Given a model evaluated on 200 days
    directions = "UUDUD" * 40
    days = days_from_directions(directions, predicted="U" * 200)

    # When metrics are computed
    report = evaluate_baselines(days)

    # Then the baselines are computed on exactly those 200 days
    assert report.n_days == 200
    assert report.always_up_accuracy == pytest.approx(directions.count("U") / 200)
    # persistence needs a previous direction: every day has one except the first
    assert report.persistence_n_days == 199


def test_baselines_ignore_days_outside_the_given_list():
    days = days_from_directions("UUDU" * 10)

    assert evaluate_baselines(days[:10]).n_days == 10
    assert evaluate_baselines(days[10:]).n_days == 30


# --- Scenario Outline: Baseline direction accuracy matches a hand-checked series ---


@pytest.mark.parametrize(
    ("directions", "baseline", "accuracy"),
    [
        ("UUDU", "always_up", 0.75),
        ("UDUD", "persistence", 0.0),
    ],
)
def test_baseline_accuracy_hand_checked(directions, baseline, accuracy):
    report = evaluate_baselines(days_from_directions(directions))

    value = {
        "always_up": report.always_up_accuracy,
        "persistence": report.persistence_accuracy,
    }[baseline]
    assert value == accuracy


def test_persistence_scores_a_trending_series_perfectly():
    # after the first day, every day repeats the previous direction
    report = evaluate_baselines(days_from_directions("UUUUU"))

    assert report.persistence_accuracy == 1.0
    assert report.persistence_n_days == 4


def test_persistence_skips_days_without_previous_close():
    days = days_from_directions("UDUD")
    # the first day has no previous close, so persistence is scored on three days
    assert days[0].previous_close is None

    report = evaluate_baselines(days)

    assert report.n_days == 4
    assert report.persistence_n_days == 3


def test_flat_day_counts_as_up_like_the_evaluator():
    # evaluator rule: actual UP iff actual_price >= price_at_prediction
    day = EvaluatedDay(
        predicted_for=START,
        previous_close=Decimal("99"),
        price_at_prediction=Decimal("100"),
        actual_price=Decimal("100"),
        predicted_price=None,
    )

    report = evaluate_baselines([day])

    assert report.always_up_accuracy == 1.0
    assert report.persistence_accuracy == 1.0


# --- Scenario: Buy-and-hold PnL is reported for the same period ---


def test_buy_and_hold_pnl_between_two_dates():
    # Given a model evaluated between two dates: bought at 100, ended at 103
    days = days_from_directions("UUDU")  # 100 -> 101 -> 102 -> 101 -> 102
    days = [
        EvaluatedDay(d.predicted_for, d.previous_close, p, a, None)
        for d, p, a in zip(
            days,
            [Decimal(x) for x in ("100", "101", "102", "101")],
            [Decimal(x) for x in ("101", "102", "101", "103")],
            strict=True,
        )
    ]

    # When metrics are computed
    report = evaluate_baselines(days)

    # Then buy-and-hold PnL between those dates is included
    assert report.buy_and_hold_pnl == Decimal("3")


def test_buy_and_hold_equals_always_up_pnl_on_contiguous_days():
    report = evaluate_baselines(days_from_directions("UDDUUDU"))

    assert report.always_up_pnl == report.buy_and_hold_pnl


def test_buy_and_hold_uses_chronological_order_not_input_order():
    days = days_from_directions("UUU")

    report = evaluate_baselines(list(reversed(days)))

    assert report.buy_and_hold_pnl == Decimal("3")


def test_persistence_pnl_trades_only_after_an_up_day():
    # UDUD, first day unscored: day 2 follows an up day -> long, loses 1;
    # day 3 follows a down day -> cash; day 4 follows an up day -> long, loses 1
    report = evaluate_baselines(days_from_directions("UDUD"))

    assert report.persistence_pnl == Decimal("-2")


# --- Scenario: The edge over the best baseline is reported with its sample size ---


def test_edge_reports_sample_size_and_p_value():
    # Given a model with 100 evaluated days and 70 correct directions
    directions = "UUDUD" * 20  # 60 up days; always-up accuracy 0.60
    predicted = ["U" if d == "U" else "D" for d in directions]
    for i in range(30):  # 30 wrong days -> 70 correct
        predicted[i] = "D" if predicted[i] == "U" else "U"
    days = days_from_directions(directions, predicted="".join(predicted))

    # When metrics are computed
    report = evaluate_baselines(days)

    # Then the result includes the sample size and a significance measure of the edge
    assert report.n_days == 100
    assert report.model_accuracy == pytest.approx(0.70)
    best = max(report.always_up_accuracy, report.persistence_accuracy)
    assert report.edge == pytest.approx(0.70 - best)
    assert report.p_value == pytest.approx(binomial_tail(70, 100, best), rel=1e-9)
    assert report.significant is (report.p_value < 0.05)


def test_best_baseline_is_named():
    # trending series: persistence beats always-up when ups and downs come in runs
    report = evaluate_baselines(
        days_from_directions("UUUDDDUUUDDD", predicted="U" * 12)
    )

    assert report.best_baseline == "persistence"
    assert report.persistence_accuracy > report.always_up_accuracy


def test_model_that_equals_the_baseline_has_no_edge_and_is_not_significant():
    directions = "UUDUD" * 20
    days = days_from_directions(directions, predicted="U" * 100)  # always-up model

    report = evaluate_baselines(days)

    assert report.best_baseline == "always_up"
    assert report.model_accuracy == report.always_up_accuracy
    assert report.edge == pytest.approx(0.0)
    assert report.significant is False


def test_significance_level_is_configurable():
    directions = "UUDUD" * 20
    predicted = directions  # perfect model
    days = days_from_directions(directions, predicted=predicted)

    strict = evaluate_baselines(days, significance_level=1e-300)
    loose = evaluate_baselines(days, significance_level=0.5)

    assert strict.p_value == loose.p_value
    assert loose.significant is True


# --- Scenario: No evaluated days yields no misleading numbers ---


def test_no_evaluated_days_is_unavailable_not_zero():
    # Given a model with zero evaluated predictions
    report = evaluate_baselines([])

    # Then baselines and edge are reported as unavailable instead of zero
    assert report.n_days == 0
    assert report.always_up_accuracy is None
    assert report.persistence_accuracy is None
    assert report.always_up_pnl is None
    assert report.persistence_pnl is None
    assert report.buy_and_hold_pnl is None
    assert report.best_baseline is None
    assert report.model_accuracy is None
    assert report.edge is None
    assert report.p_value is None
    assert report.significant is None


def test_one_day_has_no_persistence_but_has_always_up():
    report = evaluate_baselines(days_from_directions("U"))

    assert report.n_days == 1
    assert report.always_up_accuracy == 1.0
    assert report.persistence_accuracy is None
    assert report.persistence_pnl is None
    assert report.best_baseline == "always_up"


# --- Implementation details ---


def test_model_metrics_are_unavailable_when_a_prediction_is_missing():
    days = days_from_directions("UUDU", predicted="UUDU")
    days[2] = EvaluatedDay(
        days[2].predicted_for,
        days[2].previous_close,
        days[2].price_at_prediction,
        days[2].actual_price,
        None,
    )

    report = evaluate_baselines(days)

    assert report.always_up_accuracy == 0.75
    assert report.model_accuracy is None
    assert report.edge is None
    assert report.p_value is None


def test_model_accuracy_follows_the_evaluator_direction_rule():
    from workers.daily.evaluator import calculate_direction_correct

    cases = [
        # predicted, price_at_prediction, actual
        ("101", "100", "102"),
        ("101", "100", "100"),  # flat actual counts as UP
        ("101", "100", "99"),
        ("100", "100", "101"),  # flat prediction counts as DOWN
        ("99", "100", "99"),
        ("99", "100", "100"),  # flat actual with DOWN prediction is wrong
    ]
    for predicted, price, actual in cases:
        day = EvaluatedDay(
            START,
            Decimal("99"),
            Decimal(price),
            Decimal(actual),
            Decimal(predicted),
        )
        expected = calculate_direction_correct(
            Decimal(predicted), Decimal(price), Decimal(actual)
        )

        assert evaluate_baselines([day]).model_accuracy == float(expected)


@pytest.mark.parametrize(
    ("k", "n", "p"),
    [(70, 100, 0.6), (5, 5, 0.5), (0, 10, 0.3), (550, 1000, 0.511), (3000, 3300, 0.5)],
)
def test_p_value_matches_scipy_binomial_test(k, n, p):
    from shared.baselines import binomial_tail_probability

    assert binomial_tail_probability(k, n, p) == pytest.approx(
        binomial_tail(k, n, p), rel=1e-9, abs=1e-300
    )


@pytest.mark.parametrize(
    ("k", "n", "p", "expected"),
    [(0, 10, 0.0, 1.0), (1, 10, 0.0, 0.0), (10, 10, 1.0, 1.0), (0, 10, 0.5, 1.0)],
)
def test_p_value_handles_degenerate_probabilities(k, n, p, expected):
    from shared.baselines import binomial_tail_probability

    assert binomial_tail_probability(k, n, p) == expected
    assert not math.isnan(binomial_tail_probability(k, n, p))
