"""
Tests for the backtest report (#105 meets #106).

Gherkin "Metrics are computed only on the out-of-sample period": the headline uses
only the test slice; validation metrics sit in a separate labelled section. The
report puts the model next to the baselines, with the sample size and the edge.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from scripts import backtest_report
from scripts.backtest_report import build_report, format_report
from shared.baselines import EvaluatedDay, evaluate_baselines
from shared.db.models import BacktestResult

VALIDATION_DAYS = [date(2024, 6, d) for d in range(1, 11)]  # 10 days
TEST_DAYS = [date(2024, 6, d) for d in range(11, 21)]  # 10 days


def add_rows(db_session, closes, days, evaluation_slice, *, correct, run_id):
    """Store rows whose predicted direction is always right or always wrong."""
    for day in days:
        before, actual = closes[day - timedelta(days=1)], closes[day]
        went_up = actual >= before
        predicted_up = went_up if correct else not went_up
        predicted = before + 1 if predicted_up else before - 1
        db_session.add(
            BacktestResult(
                backtest_run_id=run_id,
                predicted_for=day,
                predicted_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
                price_at_prediction=before,
                predicted_price=predicted,
                actual_price=actual,
                pnl_simple=actual - before if predicted > before else Decimal("0"),
                evaluation_slice=evaluation_slice,
                model_params={
                    "model_name": "linear",
                    "window_days": 5,
                    "seed": 42,
                    "retrain_every": 1,
                    "test_start_date": TEST_DAYS[0].isoformat(),
                },
            )
        )
    db_session.commit()


@pytest.fixture
def closes(seeded_prices):
    return {day: close for day, close, _ in seeded_prices}


@pytest.fixture
def split_run(db_session, closes):
    """A run whose validation slice is all right and whose test slice is all wrong."""
    run_id = uuid4()
    add_rows(
        db_session, closes, VALIDATION_DAYS, "validation", correct=True, run_id=run_id
    )
    add_rows(db_session, closes, TEST_DAYS, "test", correct=False, run_id=run_id)
    return run_id


def independent_days(closes, days, correct):
    """Evaluated days built straight from the prices, not from stored rows."""
    out = []
    for day in days:
        before, actual = closes[day - timedelta(days=1)], closes[day]
        went_up = actual >= before
        predicted_up = went_up if correct else not went_up
        out.append(
            EvaluatedDay(
                day,
                closes[day - timedelta(days=2)],
                before,
                actual,
                before + 1 if predicted_up else before - 1,
            )
        )
    return out


# --- Scenario: Metrics are computed only on the out-of-sample period ---


def test_headline_metrics_use_only_the_test_slice(db_session, split_run):
    # Given a backtest with a validation slice used for tuning and a test slice
    # When the report is produced
    report = build_report(db_session, split_run)

    # Then headline metrics use only the test slice
    assert report.headline.name == "test"
    assert report.headline.baselines.n_days == len(TEST_DAYS)
    assert (
        report.headline.baselines.model_accuracy == 0.0
    )  # the test slice is all wrong
    validation = report.sections["validation"]
    assert validation.baselines.model_accuracy == 1.0
    assert validation.baselines.n_days == len(VALIDATION_DAYS)


def test_the_text_keeps_validation_out_of_the_headline(db_session, split_run):
    text = format_report(build_report(db_session, split_run))

    headline, _, validation = text.partition("Validation slice")
    assert "Headline: test slice (out-of-sample)" in headline
    assert "Model accuracy:" in headline
    assert "0.00%" in headline and "100.00%" not in headline
    assert "100.00%" in validation
    assert "tuning only" in validation.lower()


# --- Baselines next to the model, over the same days ---


def test_baselines_are_computed_on_exactly_the_headline_days(
    db_session, split_run, closes
):
    report = build_report(db_session, split_run)

    expected = evaluate_baselines(independent_days(closes, TEST_DAYS, correct=False))
    assert report.headline.baselines == expected
    assert report.headline.baselines.persistence_n_days == len(TEST_DAYS)
    assert report.headline.baselines.n_days == len(TEST_DAYS)


def test_persistence_covers_every_day_because_previous_close_comes_from_prices(
    db_session, split_run
):
    # a run's first row has no previous row, but its D-2 close is in `prices`
    report = build_report(db_session, split_run)

    assert (
        report.headline.baselines.persistence_n_days == report.headline.baselines.n_days
    )


def test_buy_and_hold_pnl_is_reported_for_the_test_period(
    db_session, split_run, closes
):
    report = build_report(db_session, split_run)

    assert report.headline.baselines.buy_and_hold_pnl == (
        closes[TEST_DAYS[-1]] - closes[TEST_DAYS[0] - timedelta(days=1)]
    )


def test_model_pnl_is_the_sum_of_its_simple_strategy_over_the_slice(
    db_session, split_run
):
    report = build_report(db_session, split_run)

    expected = sum(
        (
            r.pnl_simple
            for r in db_session.query(BacktestResult).filter_by(evaluation_slice="test")
        ),
        Decimal(0),
    )
    assert report.headline.model_pnl == expected


def test_the_report_states_the_sample_size_and_the_edge(db_session, split_run):
    text = format_report(build_report(db_session, split_run))

    assert f"{len(TEST_DAYS)} evaluated days" in text
    assert "Edge over best baseline:" in text
    assert "p =" in text
    assert "not significant" in text
    assert "approximation" in text.lower()


def test_run_configuration_is_part_of_the_report(db_session, split_run):
    text = format_report(build_report(db_session, split_run))

    assert "Model: linear" in text
    assert "window: 5d" in text
    assert "seed: 42" in text
    assert "retrain every: 1 day(s)" in text
    assert "Test slice starts: 2024-06-11" in text


# --- Scenario: no evaluated days, legacy rows ---


def test_an_empty_test_slice_is_unavailable_not_zero(db_session, closes):
    run_id = uuid4()
    add_rows(
        db_session, closes, VALIDATION_DAYS, "validation", correct=True, run_id=run_id
    )

    report = build_report(db_session, run_id)
    text = format_report(report)

    assert report.headline.baselines.n_days == 0
    assert report.headline.baselines.model_accuracy is None
    headline = text.partition("Validation slice")[0]
    assert "unavailable" in headline
    assert "0.00%" not in headline


def test_rows_without_a_slice_are_reported_as_unsplit(db_session, closes):
    run_id = uuid4()
    add_rows(db_session, closes, TEST_DAYS, None, correct=True, run_id=run_id)

    report = build_report(db_session, run_id)
    text = format_report(report)

    assert report.sections["unsplit"].baselines.n_days == len(TEST_DAYS)
    assert "Unsplit" in text
    assert "not out-of-sample" in text
    assert "unavailable" in text.partition("Unsplit")[0]


def test_unknown_run_has_no_report(db_session, seeded_prices):
    with pytest.raises(ValueError, match="No backtest results for run"):
        build_report(db_session, uuid4())


def test_a_day_without_a_previous_close_is_left_out_of_persistence_only(
    db_session, closes
):
    run_id = uuid4()
    first = date(2023, 1, 2)  # D-2 (2022-12-31) is before the loaded history
    db_session.add(
        BacktestResult(
            backtest_run_id=run_id,
            predicted_for=first,
            predicted_at=datetime.combine(first, datetime.min.time(), tzinfo=UTC),
            price_at_prediction=closes[date(2023, 1, 1)],
            predicted_price=closes[date(2023, 1, 1)] + 1,
            actual_price=closes[first],
            evaluation_slice="test",
            model_params={},
        )
    )
    db_session.commit()

    baselines = build_report(db_session, run_id).headline.baselines

    assert baselines.n_days == 1
    assert baselines.persistence_n_days == 0
    assert baselines.persistence_accuracy is None


# --- Command line ---


def test_the_report_command_prints_a_stored_run(db_session, split_run, capsys):
    from contextlib import nullcontext

    code = backtest_report.main(
        ["--run-id", str(split_run)], session_factory=lambda: nullcontext(db_session)
    )

    assert code == 0
    assert "Headline: test slice (out-of-sample)" in capsys.readouterr().out


def test_the_report_command_fails_for_an_unknown_run(db_session, capsys, caplog):
    from contextlib import nullcontext

    code = backtest_report.main(
        ["--run-id", str(uuid4())], session_factory=lambda: nullcontext(db_session)
    )

    assert code == 1
    assert "No backtest results for run" in caplog.text
