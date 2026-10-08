"""Tests for the backtest command line (#106)."""

from contextlib import nullcontext
from datetime import date

import pytest
from sqlalchemy.orm import Session

from scripts import backtest
from scripts.backtest_engine import BacktestConfig
from scripts.tests.helpers import DailyRows, params_of
from shared.config import settings
from shared.db.models import BacktestResult

DAY = ["--start-date=2024-06-10", "--end-date=2024-06-12", "--training-window=5"]


def run(db_session: Session, *args: str) -> int:
    return backtest.main(list(args), session_factory=lambda: nullcontext(db_session))


def test_a_run_stores_one_row_per_day_and_exits_zero(
    db_session: Session, seeded_prices: DailyRows
) -> None:
    assert run(db_session, *DAY) == 0

    rows = db_session.query(BacktestResult).all()
    assert sorted(r.predicted_for for r in rows) == [
        date(2024, 6, 10),
        date(2024, 6, 11),
        date(2024, 6, 12),
    ]
    assert {params_of(r)["model_name"] for r in rows} == {"linear"}


def test_training_window_defaults_to_the_production_window() -> None:
    args = backtest.parse_arguments(
        ["--start-date=2024-01-01", "--end-date=2024-01-02"]
    )

    assert (
        args.training_window
        == settings.training_window_days
        == BacktestConfig.default_window()
    )


def test_model_defaults_to_linear_and_rejects_unknown_names(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = backtest.parse_arguments(
        ["--start-date=2024-01-01", "--end-date=2024-01-02"]
    )
    assert args.model == "linear"

    with pytest.raises(SystemExit):
        backtest.parse_arguments(
            ["--start-date=2024-01-01", "--end-date=2024-01-02", "--model=prophet"]
        )


@pytest.mark.parametrize("model", ["xgboost", "lstm", "arima"])
def test_removed_models_exit_two_with_an_invalid_choice_message(
    capsys: pytest.CaptureFixture[str], model: str
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        backtest.parse_arguments(
            ["--start-date=2024-01-01", "--end-date=2024-01-02", f"--model={model}"]
        )

    assert excinfo.value.code == 2
    assert f"invalid choice: '{model}'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--start-date=2024-13-01", "--end-date=2024-06-12"], "Invalid start-date"),
        (["--start-date=2024-06-10", "--end-date=nope"], "Invalid end-date"),
        (["--start-date=2024-06-12", "--end-date=2024-06-10"], "must be before"),
        (
            ["--start-date=2024-06-10", "--end-date=2024-06-12", "--training-window=0"],
            "training-window must be >= 1",
        ),
    ],
)
def test_invalid_arguments_exit_one_without_writing(
    db_session: Session,
    seeded_prices: DailyRows,
    caplog: pytest.LogCaptureFixture,
    args: list[str],
    message: str,
) -> None:
    assert run(db_session, *args) == 1

    assert message in caplog.text
    assert db_session.query(BacktestResult).count() == 0


def test_insufficient_history_exits_one_and_names_the_earliest_start(
    db_session: Session, seeded_prices: DailyRows, caplog: pytest.LogCaptureFixture
) -> None:
    assert (
        run(
            db_session,
            "--start-date=2023-01-02",
            "--end-date=2023-01-05",
            "--training-window=5",
        )
        == 1
    )

    assert "earliest allowed start date is 2023-01-31" in caplog.text
    assert db_session.query(BacktestResult).count() == 0


def test_the_summary_logs_the_pnl_of_every_strategy(
    db_session: Session, seeded_prices: DailyRows, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.INFO)

    assert run(db_session, *DAY) == 0

    for label in (
        "Simple strategy",
        "Long/Short strategy",
        "Threshold strategy",
        "Realistic strategy",
    ):
        assert label in caplog.text


def test_seed_and_retrain_every_reach_the_stored_params(
    db_session: Session, seeded_prices: DailyRows
) -> None:
    assert run(db_session, *DAY, "--seed=9", "--retrain-every=2") == 0

    params = [params_of(r) for r in db_session.query(BacktestResult).all()]
    assert {p["seed"] for p in params} == {9}
    assert {p["retrain_every"] for p in params} == {2}


def test_seed_defaults_to_42_and_retrain_every_to_1() -> None:
    args = backtest.parse_arguments(
        ["--start-date=2024-01-01", "--end-date=2024-01-02"]
    )

    assert (args.seed, args.retrain_every) == (42, 1)


def test_retrain_every_below_one_is_rejected(
    db_session: Session, seeded_prices: DailyRows, caplog: pytest.LogCaptureFixture
) -> None:
    assert run(db_session, *DAY, "--retrain-every=0") == 1

    assert "retrain-every must be >= 1" in caplog.text


def test_the_run_prints_the_report_with_the_test_slice_as_headline(
    db_session: Session, seeded_prices: DailyRows, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(db_session, *DAY) == 0

    out = capsys.readouterr().out
    assert "Headline: test slice (out-of-sample)" in out
    assert "Always-up accuracy:" in out
    assert "Edge over best baseline:" in out


def test_test_start_date_reaches_the_stored_slices(
    db_session: Session, seeded_prices: DailyRows
) -> None:
    assert run(db_session, *DAY, "--test-start-date=2024-06-12") == 0

    slices = {
        r.predicted_for: r.evaluation_slice
        for r in db_session.query(BacktestResult).all()
    }
    assert slices == {
        date(2024, 6, 10): "validation",
        date(2024, 6, 11): "validation",
        date(2024, 6, 12): "test",
    }


def test_test_start_date_outside_the_range_exits_one(
    db_session: Session, seeded_prices: DailyRows, caplog: pytest.LogCaptureFixture
) -> None:
    assert run(db_session, *DAY, "--test-start-date=2024-07-01") == 1

    assert "within the backtest range" in caplog.text
    assert db_session.query(BacktestResult).count() == 0


def test_a_malformed_test_start_date_exits_one(
    db_session: Session, seeded_prices: DailyRows, caplog: pytest.LogCaptureFixture
) -> None:
    assert run(db_session, *DAY, "--test-start-date=soon") == 1

    assert "Invalid test-start-date" in caplog.text


def test_ctrl_c_exits_one(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def interrupted(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(backtest, "run_walk_forward", interrupted)

    assert run(db_session, *DAY) == 1
    assert "interrupted by user" in caplog.text


def test_an_unexpected_error_exits_one_and_is_logged(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database went away")

    monkeypatch.setattr(backtest, "run_walk_forward", broken)

    assert run(db_session, *DAY) == 1
    assert "Backtest failed: database went away" in caplog.text
