"""
"The model can be backtested" (#106 Scenario Outline).

The linear model runs on the return features of the production feature builder, with
the same code as the daily trainer (#124). It is the only model since #184.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

import scripts.backtest_engine as engine
from scripts.backtest_engine import BacktestConfig
from scripts.tests.helpers import DailyRows, params_of
from shared.db.models import BacktestResult

START, END = date(2024, 1, 1), date(2024, 3, 31)
WINDOW = 5


@pytest.mark.parametrize("model", ["linear"])
def test_backtest_stores_one_result_per_day(
    db_session: Session, seeded_prices: DailyRows, model: str
) -> None:
    # Given the model, when I backtest 2024-01-01 to 2024-03-31
    run_id = uuid4()
    config = BacktestConfig(
        model_name=model,
        window_days=WINDOW,
        start_date=START,
        end_date=END,
        retrain_every=1,
    )

    engine.run_walk_forward(db_session, config, run_id)

    # Then one result per day is stored in backtest_results
    rows = (
        db_session.query(BacktestResult)
        .filter_by(backtest_run_id=run_id)
        .order_by(BacktestResult.predicted_for)
        .all()
    )
    assert [r.predicted_for for r in rows] == [
        START + timedelta(days=i) for i in range((END - START).days + 1)
    ]
    assert {params_of(r)["model_name"] for r in rows} == {model}
