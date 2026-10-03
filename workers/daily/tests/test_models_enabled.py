"""
LSTM, XGBoost and ARIMA are back in the default run (#124).

Gherkin: "LSTM, XGBoost and ARIMA are back in the default run". The suites of the
three models run with a plain ``pytest``; these tests fail if the skip machinery
of the Linear-only reboot comes back.
"""

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MARKER = "non_" + "linear"  # spelled in two parts so this file does not match itself
SKIP_FLAG = "--run-" + "non-linear"


def _python_files() -> list[Path]:
    ignored = {".git", ".venv", "node_modules", "__pycache__"}
    return [
        path
        for path in REPO_ROOT.rglob("*.py")
        if not ignored & set(path.relative_to(REPO_ROOT).parts)
        and path != Path(__file__).resolve()
    ]


def test_no_test_carries_the_skip_marker_and_no_hook_skips_it() -> None:
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _python_files()
        if f"mark.{MARKER}" in path.read_text() or SKIP_FLAG in path.read_text()
    ]

    assert offenders == []


def test_the_skip_marker_is_not_registered() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    markers = config["tool"]["pytest"]["ini_options"]["markers"]

    assert not [marker for marker in markers if marker.startswith(MARKER)]


def test_no_test_module_is_omitted_from_coverage() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    omitted = config["tool"].get("coverage", {}).get("run", {}).get("omit", [])

    assert omitted == []


def test_the_three_model_suites_exist_next_to_the_trainer_tests() -> None:
    tests = Path(__file__).parent

    for suite in ("lstm_model", "xgboost_model", "arima_model", "all_models"):
        assert (tests / f"test_{suite}.py").is_file()
