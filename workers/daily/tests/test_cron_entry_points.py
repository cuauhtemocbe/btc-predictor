"""
The cron jobs run Linear Regression only, whatever models the code base has (#124).

LSTM, XGBoost and ARIMA are back in the code base and in ``train_all_models``, but
production still trains and predicts with the linear model of ``BTCUSDT``. This test
fails if a cron entry point starts loading the other models; the daily trainer test
that fails if it starts training them is in ``test_return_prediction.py``.
"""

import subprocess
import sys

CRON_ENTRY_POINTS = [
    "workers.fetch_price.main",
    "workers.daily.__main__",
    "workers.daily.evaluator",
    "workers.daily.trainer",
    "workers.daily.predictor",
    "workers.backtest.main",
]


def test_importing_the_cron_entry_points_does_not_load_the_non_linear_libraries() -> (
    None
):
    imports = "; ".join(f"import {module}" for module in CRON_ENTRY_POINTS)
    code = (
        f"import sys; {imports}; "
        "heavy = {'tensorflow', 'xgboost', 'statsmodels'} & set(sys.modules); "
        "print(sorted(heavy)); "
        "sys.exit(1 if heavy else 0)"
    )

    result = subprocess.run([sys.executable, "-c", code], capture_output=True)

    assert result.returncode == 0, result.stdout.decode() + result.stderr.decode()
