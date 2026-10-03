import re
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def read_workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text()


def quality_runs() -> list[str]:
    """The ``run`` command of every step of the Docker quality gate, in order."""
    workflow = yaml.safe_load(read_workflow("ci.yml"))
    steps = workflow["jobs"]["quality"]["steps"]
    return [" ".join(step["run"].split()) for step in steps if "run" in step]


def test_ci_runs_docker_quality_gate_on_push_and_pull_request():
    workflow = read_workflow("ci.yml")

    assert "push:" in workflow
    assert "pull_request:" in workflow
    assert "branches:" in workflow
    assert "docker compose up -d --wait" in workflow
    assert "python -m mypy" in workflow
    assert "pytest --cov" in workflow


PRODUCTION_PACKAGES = ["shared", "api", "workers", "scripts"]
MYPY_PATHS = [
    "shared/shared",
    "shared/btc_shared",
    "shared/tests",
    "workers",
    "api",
    "scripts",
]


def tokens_after(command: str, marker: str) -> list[str]:
    """The words that follow ``marker`` in a shell command."""
    assert marker in command, f"{marker!r} not in {command!r}"
    return command.split(marker, 1)[1].split()


def test_ci_lints_and_formats_every_production_package():
    # Scenario "CI checks all production packages"
    runs = quality_runs()
    lint = next(run for run in runs if "ruff check" in run)
    fmt = next(run for run in runs if "ruff format --check" in run)

    assert tokens_after(lint, "ruff check") == PRODUCTION_PACKAGES
    assert tokens_after(fmt, "ruff format --check") == PRODUCTION_PACKAGES


def test_ci_type_checks_every_production_package():
    # Scenario "CI checks all production packages"
    mypy = next(run for run in quality_runs() if "python -m mypy" in run)

    assert tokens_after(mypy, "python -m mypy") == MYPY_PATHS


def test_ci_and_pyproject_type_check_the_same_paths():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    assert pyproject["tool"]["mypy"]["files"] == MYPY_PATHS


def test_the_local_gate_matches_ci_static_checks():
    validate = " ".join((REPO_ROOT / "scripts" / "validate.sh").read_text().split())
    mypy_hook = " ".join(
        (REPO_ROOT / "scripts" / "hooks" / "run-mypy.sh").read_text().split()
    )

    assert " ".join(PRODUCTION_PACKAGES) in validate
    assert "ruff format --check " + " ".join(PRODUCTION_PACKAGES) in validate
    assert " ".join(MYPY_PATHS) in validate
    assert " ".join(MYPY_PATHS) in mypy_hook


@pytest.mark.parametrize(
    "path",
    [
        "shared/shared/utils.py",
        "api-service/api/main.py",
        "workers/daily/trainer.py",
        "scripts/backtest_engine.py",
    ],
)
def test_pre_commit_lints_and_type_checks_every_production_package(path):
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text())
    hooks = {h["id"]: h for repo in config["repos"] for h in repo["hooks"]}

    for hook_id in ("ruff", "ruff-format", "mypy-docker"):
        assert re.search(hooks[hook_id]["files"], path), (hook_id, path)


def test_ci_checks_per_module_coverage_right_after_the_coverage_run():
    # Scenario "Missing worker coverage fails the gate": the gate reuses the
    # coverage.xml of the pytest step instead of running the suite again
    runs = quality_runs()
    pytest_index = next(i for i, run in enumerate(runs) if "pytest --cov" in run)

    assert (
        "scripts/check_coverage_thresholds.py /tmp/coverage.xml"
        in runs[pytest_index + 1]
    )
    assert runs[pytest_index + 1].startswith("docker compose exec -T api python")
    assert sum("pytest" in run for run in runs) == 1


def test_ci_keeps_the_required_check_name():
    workflow = yaml.safe_load(read_workflow("ci.yml"))

    assert workflow["jobs"]["quality"]["name"] == "Docker quality gate"


def test_ci_builds_with_the_default_docker_builder():
    # setup-buildx makes the 4.5 GB api image go through a tarball export and
    # import (~130 s per run); the default builder does not
    workflow = yaml.safe_load(read_workflow("ci.yml"))
    actions = [step.get("uses", "") for step in workflow["jobs"]["quality"]["steps"]]

    assert not any("setup-buildx-action" in action for action in actions)


def test_ci_publishes_coverage_artifact_and_cleans_up():
    workflow = read_workflow("ci.yml")

    assert "--cov-report=xml:/tmp/coverage.xml" in workflow
    assert "actions/upload-artifact@" in workflow
    assert "docker compose down -v" in workflow
    assert "if: always()" in workflow


def test_quality_runs_mutation_testing_weekly_and_manually():
    workflow = read_workflow("quality.yml")

    assert "cron: '0 7 * * 1'" in workflow
    assert "workflow_dispatch:" in workflow
    assert "cosmic-ray init" in workflow
    assert "cosmic-ray exec" in workflow
    assert "cr-report" in workflow


def test_ci_does_not_duplicate_railway_deployment():
    assert not (WORKFLOWS / "deploy.yml").exists()
