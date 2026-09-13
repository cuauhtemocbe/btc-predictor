from pathlib import Path


WORKFLOWS = Path(__file__).parents[2] / ".github" / "workflows"


def read_workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text()


def test_ci_runs_docker_quality_gate_on_push_and_pull_request():
    workflow = read_workflow("ci.yml")

    assert "push:" in workflow
    assert "pull_request:" in workflow
    assert "branches:" in workflow
    assert "docker compose up -d --wait" in workflow
    assert "ruff check shared api workers" in workflow
    assert "ruff format --check shared api workers" in workflow
    assert "python -m mypy" in workflow
    assert "pytest --cov" in workflow


def test_ci_publishes_coverage_artifact_and_cleans_up():
    workflow = read_workflow("ci.yml")

    assert "--cov-report=xml:/tmp/coverage.xml" in workflow
    assert "actions/upload-artifact@v4" in workflow
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
