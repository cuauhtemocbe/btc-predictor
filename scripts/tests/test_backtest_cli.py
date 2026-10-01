"""Tests for the backtest command line (#106)."""

from contextlib import nullcontext
from datetime import date

import pytest

from scripts import backtest
from scripts.backtest_engine import BacktestConfig
from shared.config import settings
from shared.db.models import BacktestResult

DAY = ["--start-date=2024-06-10", "--end-date=2024-06-12", "--training-window=5"]


def run(db_session, *args: str) -> int:
    return backtest.main(list(args), session_factory=lambda: nullcontext(db_session))


def test_a_run_stores_one_row_per_day_and_exits_zero(db_session, seeded_prices):
    assert run(db_session, *DAY) == 0

    rows = db_session.query(BacktestResult).all()
    assert sorted(r.predicted_for for r in rows) == [
        date(2024, 6, 10),
        date(2024, 6, 11),
        date(2024, 6, 12),
    ]
    assert {r.model_params["model_name"] for r in rows} == {"linear"}


def test_training_window_defaults_to_the_production_window():
    args = backtest.parse_arguments(
        ["--start-date=2024-01-01", "--end-date=2024-01-02"]
    )

    assert (
        args.training_window
        == settings.training_window_days
        == BacktestConfig.default_window()
    )


def test_model_defaults_to_linear_and_rejects_unknown_names(capsys):
    args = backtest.parse_arguments(
        ["--start-date=2024-01-01", "--end-date=2024-01-02"]
    )
    assert args.model == "linear"

    with pytest.raises(SystemExit):
        backtest.parse_arguments(
            ["--start-date=2024-01-01", "--end-date=2024-01-02", "--model=prophet"]
        )


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
    db_session, seeded_prices, caplog, args, message
):
    assert run(db_session, *args) == 1

    assert message in caplog.text
    assert db_session.query(BacktestResult).count() == 0


def test_insufficient_history_exits_one_and_names_the_earliest_start(
    db_session, seeded_prices, caplog
):
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


def test_the_summary_logs_the_pnl_of_every_strategy(db_session, seeded_prices, caplog):
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
