"""
Tests for Dev Standards Compliance repo-level artifacts (milestone "Dev
Standards Compliance", issues #43-#47):
- LICENSE exists and is MIT (#46)
- CHANGELOG.md follows Keep a Changelog format and stays in sync with the
  version declared in pyproject.toml (#46)
- Secret scanning (gitleaks) is wired into the pre-commit pipeline (#46)
- mypy --strict is configured for shared/ and wired into pre-commit (#45)
- The pytest coverage gate is configured (#45)
- The Makefile is self-documented and scripts/validate.sh is the single
  source of truth for the local quality gate, reused by the git hooks (#44)
- Production Dockerfile is pinned by digest with a healthcheck; the dev
  image intentionally floats (#43)
"""

import os
import re
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_license_file_is_present_and_mit():
    license_path = REPO_ROOT / "LICENSE"
    assert license_path.exists(), "LICENSE file must exist at repo root"

    content = license_path.read_text()
    assert "MIT License" in content
    assert "Permission is hereby granted, free of charge" in content


def test_changelog_has_unreleased_and_versioned_sections():
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text()

    assert "## [Unreleased]" in changelog

    version_sections = re.findall(
        r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE
    )
    assert version_sections, "CHANGELOG must have at least one versioned section"

    # The most recent versioned section must expose the standard
    # Keep a Changelog subsections.
    first_version_idx = changelog.index(f"## [{version_sections[0]}]")
    next_section_idx = changelog.find("\n## [", first_version_idx + 1)
    section_body = changelog[first_version_idx:next_section_idx]

    for subsection in ("### Added", "### Changed", "### Fixed", "### Removed"):
        assert subsection in section_body, (
            f"Latest versioned CHANGELOG section is missing {subsection}"
        )


def test_changelog_version_matches_pyproject():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    manifest_version = pyproject["tool"]["poetry"]["version"]

    changelog = (REPO_ROOT / "CHANGELOG.md").read_text()
    version_sections = re.findall(
        r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE
    )

    assert version_sections[0] == manifest_version, (
        f"CHANGELOG's latest version ({version_sections[0]}) is out of sync "
        f"with pyproject.toml ({manifest_version})"
    )


def test_gitleaks_hook_configured_in_pre_commit():
    config = (REPO_ROOT / ".pre-commit-config.yaml").read_text()

    assert "gitleaks/gitleaks" in config
    assert "id: gitleaks" in config


def test_mypy_strict_configured_for_shared():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    mypy_config = pyproject["tool"]["mypy"]

    assert mypy_config["strict"] is True
    assert mypy_config["files"] == [
        "shared/shared",
        "shared/btc_shared",
        "shared/tests",
    ]

    test_overrides = [
        o
        for o in pyproject["tool"]["mypy"]["overrides"]
        if o["module"] == "tests.*"
    ]
    assert test_overrides, "Expected a relaxed [[tool.mypy.overrides]] for tests.*"
    assert test_overrides[0]["disallow_untyped_defs"] is False
    assert test_overrides[0]["strict_optional"] is False


def test_mypy_hook_configured_in_pre_commit():
    config = (REPO_ROOT / ".pre-commit-config.yaml").read_text()

    assert "id: mypy-docker" in config


def test_coverage_fail_under_90_configured():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]

    assert "--cov-fail-under=90" in addopts


REQUIRED_MAKE_TARGETS = [
    "build",
    "up",
    "up-d",
    "down",
    "logs",
    "test",
    "test-v",
    "lint",
    "validate",
    "install-local",
    "test-local",
    "lint-local",
]


def test_makefile_default_goal_is_help():
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert ".DEFAULT_GOAL := help" in makefile


def test_makefile_every_target_has_a_description():
    makefile = (REPO_ROOT / "Makefile").read_text()

    for target in REQUIRED_MAKE_TARGETS:
        assert re.search(rf"^{re.escape(target)}:.*##", makefile, re.MULTILINE), (
            f"Makefile target '{target}' is missing a '##' help description"
        )


def test_makefile_local_targets_are_in_a_distinct_section():
    makefile = (REPO_ROOT / "Makefile").read_text()

    local_section = makefile.index("##@ Local")
    for target in ("install-local", "test-local", "lint-local"):
        assert makefile.index(f"\n{target}:") > local_section, (
            f"'{target}' should be documented after the local-targets section header"
        )


def test_makefile_test_target_waits_for_postgres_before_pytest():
    makefile = (REPO_ROOT / "Makefile").read_text()

    test_recipe = makefile.split("\ntest:")[1].split("\n\n")[0]
    wait_line, pytest_line = None, None
    for i, line in enumerate(test_recipe.splitlines()):
        if "--wait" in line and "postgres" in line:
            wait_line = i
        if "pytest" in line:
            pytest_line = i
    assert wait_line is not None, "'test' target must wait for postgres to be healthy"
    assert pytest_line is not None and wait_line < pytest_line


def test_validate_script_is_reused_by_pre_push_hook():
    validate_script = (REPO_ROOT / "scripts" / "validate.sh").read_text()
    run_tests_hook = (REPO_ROOT / "scripts" / "hooks" / "run-tests.sh").read_text()

    assert "ruff check" in validate_script
    assert "ruff format --check" in validate_script
    assert "pytest --cov" in validate_script
    # The pre-push hook must call validate.sh, not duplicate its checks.
    assert "validate.sh" in run_tests_hook
    assert "ruff check" not in run_tests_hook


def test_validate_script_checks_lockfile_before_tests():
    validate_script = (REPO_ROOT / "scripts" / "validate.sh").read_text()

    lockfile_check = "docker compose exec -T api poetry check --lock"
    assert lockfile_check in validate_script
    assert validate_script.index(lockfile_check) < validate_script.index("pytest --cov")
    assert "Lockfile out of sync" in validate_script


def test_validate_script_stops_before_pytest_when_lockfile_is_stale(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls.log"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> '{calls}'\n"
        "case \"$*\" in\n"
        "  'compose ps') printf 'api running\\n' ;;\n"
        "  *'poetry check --lock'*) exit 1 ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n"
    )
    fake_docker.chmod(0o755)

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "validate.sh")],
        cwd=REPO_ROOT,
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Lockfile out of sync" in result.stderr
    assert "pytest --cov" not in calls.read_text()


def test_production_dockerfile_base_pinned_by_digest():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()

    assert re.search(
        r"^FROM python:3\.13-slim@sha256:[0-9a-f]{64} AS base",
        dockerfile,
        re.MULTILINE,
    ), "Production Dockerfile base stage must be pinned by a sha256 digest"


def test_dev_dockerfile_keeps_floating_tag():
    dockerfile_dev = (REPO_ROOT / "Dockerfile.dev").read_text()

    assert re.search(r"^FROM python:3\.13-slim$", dockerfile_dev, re.MULTILINE), (
        "Dockerfile.dev should intentionally NOT pin a digest"
    )
    assert "@sha256:" not in dockerfile_dev


def test_production_dockerfile_api_stage_has_healthcheck():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()

    api_stage = dockerfile.split("FROM base AS api")[1].split("FROM base AS")[0]
    assert "HEALTHCHECK" in api_stage
    assert "/health" in api_stage


def test_production_dockerfile_batch_stages_have_no_healthcheck():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()

    fetch_stage = dockerfile.split("FROM base AS fetch")[1].split(
        "FROM base AS ml-worker"
    )[0]
    ml_worker_stage = dockerfile.split("FROM base AS ml-worker")[1]

    assert "HEALTHCHECK" not in fetch_stage
    assert "HEALTHCHECK" not in ml_worker_stage


def test_docker_compose_api_service_has_healthcheck():
    compose = (REPO_ROOT / "docker-compose.yml").read_text()

    api_service = compose.split("\n  api:")[1].split("\nvolumes:")[0]
    assert "healthcheck:" in api_service
    assert "/health" in api_service
