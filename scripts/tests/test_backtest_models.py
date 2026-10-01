"""
"Every model type can be backtested" (#106 Scenario Outline).

Linear always runs. xgboost, lstm and arima are marked ``non_linear`` (disabled
during the Linear-only reboot, tracked in #124) and run with ``--run-non-linear``.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest

import scripts.backtest_engine as engine
from scripts.backtest_engine import BacktestConfig
from shared.db.models import BacktestResult

# XGBoost and LSTM still validate X against ``window_days`` columns, while the
# production feature builder (#104) gives them 2 * window_days + 1. The backtest
# runs exactly the production code, so it reproduces the daily trainer's failure
# instead of working around it. Strict: when #124 fixes the models, this xfail
# turns into a failure that says to remove it.
NEEDS_RETURN_FEATURES = pytest.mark.xfail(
    strict=True,
    raises=ValueError,
    reason="model does not accept the return features yet (#124)",
)

START, END = date(2024, 1, 1), date(2024, 3, 31)
WINDOW = 5


@pytest.mark.parametrize(
    "model",
    [
        "linear",
        pytest.param("xgboost", marks=[pytest.mark.non_linear, NEEDS_RETURN_FEATURES]),
        pytest.param("lstm", marks=[pytest.mark.non_linear, NEEDS_RETURN_FEATURES]),
        pytest.param("arima", marks=pytest.mark.non_linear),
    ],
)
def test_backtest_stores_one_result_per_day(db_session, seeded_prices, model):
    # Given the model, when I backtest 2024-01-01 to 2024-03-31
    run_id = uuid4()
    # retraining every 30 days keeps the heavy models fast; the frequency is stored
    # in every row and printed in the report
    config = BacktestConfig(
        model_name=model,
        window_days=WINDOW,
        start_date=START,
        end_date=END,
        retrain_every=1 if model == "linear" else 30,
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
    assert {r.model_params["model_name"] for r in rows} == {model}
