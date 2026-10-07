"""
The cron jobs run Linear Regression only, whatever the code base holds (#124, #184).

LSTM, XGBoost and ARIMA were removed in #184, so no cron entry point can load them.
This test fails if a cron entry point starts loading a model module other than the
linear one or the libraries of the removed models; the daily trainer test that fails
if it starts training other models is in ``test_return_prediction.py``.
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

ALLOWED_MODEL_MODULES = {
    "workers.daily.models",
    "workers.daily.models.base",
    "workers.daily.models.factory",
    "workers.daily.models.linear",
}


def test_importing_the_cron_entry_points_loads_only_the_linear_model() -> None:
    imports = "; ".join(f"import {module}" for module in CRON_ENTRY_POINTS)
    code = (
        f"import sys; {imports}; "
        "removed = {'tensorflow', 'xgboost', 'statsmodels'} & set(sys.modules); "
        "models = {m for m in sys.modules if m.startswith('workers.daily.models')}; "
        "print(sorted(removed), sorted(models)); "
        f"sys.exit(1 if removed or models - {ALLOWED_MODEL_MODULES!r} else 0)"
    )

    result = subprocess.run([sys.executable, "-c", code], capture_output=True)

    assert result.returncode == 0, result.stdout.decode() + result.stderr.decode()
