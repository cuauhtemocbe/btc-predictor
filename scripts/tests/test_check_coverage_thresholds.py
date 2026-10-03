"""Tests for ``scripts/check_coverage_thresholds.py`` (#68).

Gherkin scenarios of the issue "Targeted quality gates":

* Critical modules meet their coverage threshold
* Missing worker coverage fails the gate
* CI checks all production packages (see ``test_ci_workflows.py``)
"""

from pathlib import Path

import pytest

from scripts.check_coverage_thresholds import (
    DEFAULT_CONFIG,
    FileCoverage,
    evaluate,
    load_thresholds,
    main,
    normalize_filename,
    parse_coverage_xml,
)

REPO_ROOT = Path(__file__).parents[2]
TRAINER = "workers/daily/trainer.py"
MODEL = "workers/daily/models/linear.py"


def write_report(path: Path, files: dict[str, tuple[int, int]]) -> Path:
    """Write a coverage.xml where each file has ``(covered, uncovered)`` lines."""
    classes = []
    for number, (filename, (covered, uncovered)) in enumerate(files.items()):
        hits = [1] * covered + [0] * uncovered
        lines = "".join(
            f'<line number="{index + 1}" hits="{hit}"/>'
            for index, hit in enumerate(hits)
        )
        classes.append(
            f'<class name="c{number}" filename="{filename}">'
            f"<methods/><lines>{lines}</lines></class>"
        )
    path.write_text(
        '<?xml version="1.0" ?><coverage><packages><package name=".">'
        f"<classes>{''.join(classes)}</classes></package></packages></coverage>"
    )
    return path


def write_config(path: Path, thresholds: dict[str, object]) -> Path:
    body = "".join(
        f'"{module}" = {minimum}\n' for module, minimum in thresholds.items()
    )
    path.write_text(f"[tool.coverage_thresholds]\n{body}")
    return path


@pytest.fixture
def config(tmp_path):
    return write_config(tmp_path / "pyproject.toml", {TRAINER: 90, MODEL: 80})


def run_gate(report: Path, config: Path) -> int:
    return main([str(report), "--config", str(config)])


# Scenario: Critical modules meet their coverage threshold


def test_gate_passes_when_every_critical_module_meets_its_threshold(
    tmp_path, config, capsys
):
    report = write_report(
        tmp_path / "coverage.xml",
        {TRAINER: (95, 5), MODEL: (85, 15), "other.py": (1, 9)},
    )

    assert run_gate(report, config) == 0
    assert "All 2 critical modules meet their threshold" in capsys.readouterr().out


def test_a_module_exactly_at_its_threshold_passes(tmp_path, config):
    report = write_report(tmp_path / "coverage.xml", {TRAINER: (90, 10), MODEL: (4, 1)})

    assert run_gate(report, config) == 0


def test_the_real_thresholds_pass_on_a_fully_covered_report(tmp_path):
    thresholds = load_thresholds(DEFAULT_CONFIG)
    report = write_report(
        tmp_path / "coverage.xml", {module: (10, 0) for module in thresholds}
    )

    assert main([str(report)]) == 0


# Scenario: Missing worker coverage fails the gate


def test_gate_fails_and_names_a_module_below_its_threshold(tmp_path, config, capsys):
    report = write_report(tmp_path / "coverage.xml", {TRAINER: (50, 50), MODEL: (9, 1)})

    assert run_gate(report, config) == 1
    error = capsys.readouterr().err
    assert f"{TRAINER}: 50.0% covered, minimum 90%" in error
    assert MODEL not in error.split("FAILED")[1]


def test_gate_fails_and_names_a_module_missing_from_the_report(
    tmp_path, config, capsys
):
    report = write_report(tmp_path / "coverage.xml", {MODEL: (10, 0)})

    assert run_gate(report, config) == 1
    assert f"{TRAINER}: not in the coverage report" in capsys.readouterr().err


def test_a_module_with_no_executed_lines_fails_with_zero_coverage(
    tmp_path, config, capsys
):
    report = write_report(tmp_path / "coverage.xml", {TRAINER: (0, 40), MODEL: (10, 0)})

    assert run_gate(report, config) == 1
    assert f"{TRAINER}: 0.0% covered" in capsys.readouterr().err


def test_the_real_thresholds_fail_naming_an_unexercised_worker(tmp_path, capsys):
    thresholds = load_thresholds(DEFAULT_CONFIG)
    covered = {module: (10, 0) for module in thresholds if module != TRAINER}
    report = write_report(tmp_path / "coverage.xml", covered)

    assert main([str(report)]) == 1
    assert TRAINER in capsys.readouterr().err


def test_api_files_are_matched_after_the_container_path_is_normalized(tmp_path):
    report = write_report(tmp_path / "coverage.xml", {"api/api/main.py": (10, 0)})
    config = write_config(tmp_path / "pyproject.toml", {"api-service/api/main.py": 95})

    assert run_gate(report, config) == 0


# Report parsing and configuration errors


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("api/api/main.py", "api-service/api/main.py"),
        ("api/api/routers/prices.py", "api-service/api/routers/prices.py"),
        ("api-service/api/main.py", "api-service/api/main.py"),
        ("shared/shared/utils.py", "shared/shared/utils.py"),
        ("workers/daily/trainer.py", "workers/daily/trainer.py"),
    ],
)
def test_normalize_filename_matches_the_sonar_coverage_target(filename, expected):
    assert normalize_filename(filename) == expected


def test_parse_coverage_xml_counts_lines_that_were_hit(tmp_path):
    report = write_report(
        tmp_path / "coverage.xml", {TRAINER: (3, 1), "empty.py": (0, 0)}
    )

    parsed = parse_coverage_xml(report)

    assert parsed[TRAINER] == FileCoverage(covered=3, total=4)
    assert parsed["empty.py"].percent == 100.0


def test_evaluate_lists_every_failing_module_in_order():
    coverage = {"b.py": FileCoverage(1, 2), "c.py": FileCoverage(2, 2)}

    failures = evaluate({"c.py": 100, "b.py": 90, "a.py": 50}, coverage)

    assert [(f.module, f.coverage) for f in failures] == [
        ("a.py", None),
        ("b.py", pytest.approx(50.0)),
    ]


@pytest.mark.parametrize("bad_value", ['"95"', "true", "-1", "101"])
def test_a_threshold_outside_0_to_100_is_a_configuration_error(
    tmp_path, bad_value, capsys
):
    config = write_config(tmp_path / "pyproject.toml", {TRAINER: bad_value})
    report = write_report(tmp_path / "coverage.xml", {TRAINER: (10, 0)})

    assert run_gate(report, config) == 2
    assert TRAINER in capsys.readouterr().err


def test_a_config_without_the_section_is_a_configuration_error(tmp_path, capsys):
    config = tmp_path / "pyproject.toml"
    config.write_text("[tool.other]\nx = 1\n")
    report = write_report(tmp_path / "coverage.xml", {TRAINER: (10, 0)})

    assert run_gate(report, config) == 2
    assert "coverage_thresholds" in capsys.readouterr().err


def test_a_missing_report_is_an_error_not_a_pass(tmp_path, config, capsys):
    assert run_gate(tmp_path / "absent.xml", config) == 2
    assert "Cannot check coverage thresholds" in capsys.readouterr().err


# The configuration itself


def test_every_configured_module_exists_in_the_repo():
    orphans = [
        module
        for module in load_thresholds(DEFAULT_CONFIG)
        if not (REPO_ROOT / module).is_file()
    ]

    assert orphans == [], f"thresholds point at files that do not exist: {orphans}"


REQUIRED_CRITICAL_MODULES = [
    "workers/daily/trainer.py",
    "workers/weekly/trainer.py",
    "workers/daily/predictor.py",
    "workers/weekly/predictor.py",
    "workers/daily/evaluator.py",
    "workers/weekly/evaluator.py",
    "workers/daily/models/arima_model.py",
    "workers/daily/models/linear.py",
    "workers/daily/models/lstm_model.py",
    "workers/daily/models/xgboost_model.py",
    "scripts/backtest_engine.py",
    "workers/backtest/main.py",
    "shared/shared/db/crud.py",
    "shared/shared/utils.py",
    "shared/shared/features.py",
    "shared/shared/baselines.py",
]


@pytest.mark.parametrize("module", REQUIRED_CRITICAL_MODULES)
def test_critical_modules_keep_a_threshold(module):
    assert module in load_thresholds(DEFAULT_CONFIG)
