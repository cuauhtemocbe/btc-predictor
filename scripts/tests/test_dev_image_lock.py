"""
The Docker quality gate must test what production runs (#213).

Production installs only the root ``poetry.lock``. ``Dockerfile.dev`` used to run
a second ``poetry install`` from ``api-service/pyproject.toml`` (no lock), which
re-resolved against PyPI and overrode versions the lock pinned, so a green gate
said nothing about the production versions. These tests run inside the dev image
in CI and fail when any package it runs differs from the root lock.
"""

import re
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest
from packaging.markers import Marker
from packaging.utils import canonicalize_name

REPO_ROOT = Path(__file__).resolve().parents[2]

LockPackage = dict[str, Any]


def locked_packages(lock_text: str) -> list[LockPackage]:
    """The ``[[package]]`` entries of a ``poetry.lock``."""
    packages: list[LockPackage] = tomllib.loads(lock_text)["package"]
    return packages


def applies_here(package: LockPackage) -> bool:
    """Whether the lock expects ``package`` on this platform and interpreter.

    The lock records an environment marker (a plain string, or one per group)
    for packages that only some platforms install, such as ``colorama`` on
    Windows. A group without a marker means the package is unconditional there.
    """
    markers = package.get("markers")
    if markers is None:
        return True
    if isinstance(markers, str):
        return Marker(markers).evaluate()
    groups: list[str] = package["groups"]
    return any(
        group not in markers or Marker(markers[group]).evaluate() for group in groups
    )


def version_mismatches(packages: list[LockPackage]) -> list[str]:
    """One line per locked package whose installed version differs from the lock.

    The local ``shared`` package (a path dependency) is not versioned by the
    lock and is skipped, as are packages the lock excludes on this platform.
    """
    problems: list[str] = []
    for package in packages:
        if "source" in package or not applies_here(package):
            continue
        name = package["name"]
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            problems.append(f"{name}: locked {package['version']}, not installed")
            continue
        if installed != package["version"]:
            problems.append(
                f"{name}: locked {package['version']}, installed {installed}"
            )
    return problems


def lock_version(name: str) -> str:
    """The version the root lock pins for ``name``."""
    lock_text = (REPO_ROOT / "poetry.lock").read_text()
    for package in locked_packages(lock_text):
        if canonicalize_name(package["name"]) == canonicalize_name(name):
            version: str = package["version"]
            return version
    raise AssertionError(f"{name} is not in poetry.lock")


@pytest.mark.parametrize("name", ["sqlalchemy", "pytest"])
def test_gate_runs_the_version_the_root_lock_pins(name: str) -> None:
    # The cases that slipped through: SQLAlchemy 2.0.x tested against a 2.1 lock,
    # and pytest 8.4 tested against a 9.1 lock.
    assert metadata.version(name) == lock_version(name)


def test_gate_runs_every_version_the_root_lock_pins() -> None:
    lock_text = (REPO_ROOT / "poetry.lock").read_text()

    assert version_mismatches(locked_packages(lock_text)) == []


def test_mismatch_is_reported_when_the_lock_pins_another_version() -> None:
    # A Dependabot bump of SQLAlchemy to 2.1.x in the root lock, with an image
    # that still runs 2.0.x, must be reported (and so fail the gate).
    installed = metadata.version("sqlalchemy")
    bumped = [{"name": "SQLAlchemy", "version": "2.1.3", "groups": ["main"]}]

    assert version_mismatches(bumped) == [
        f"SQLAlchemy: locked 2.1.3, installed {installed}"
    ]


def test_missing_package_is_reported() -> None:
    absent = [{"name": "not-a-real-dist", "version": "1.0", "groups": ["main"]}]

    assert version_mismatches(absent) == ["not-a-real-dist: locked 1.0, not installed"]


def test_platform_specific_package_is_skipped_when_its_marker_is_false() -> None:
    windows_only: list[LockPackage] = [
        {
            "name": "not-a-real-dist",
            "version": "1.0",
            "groups": ["api", "dev"],
            "markers": {
                "api": 'platform_system == "Windows"',
                "dev": 'sys_platform == "win32"',
            },
        },
        {
            "name": "not-a-real-dist",
            "version": "1.0",
            "groups": ["main"],
            "markers": 'sys_platform == "win32"',
        },
    ]

    assert version_mismatches(windows_only) == []


def test_package_with_an_unmarked_group_is_expected_everywhere() -> None:
    package = {
        "name": "x",
        "version": "1",
        "groups": ["main", "dev"],
        "markers": {"dev": 'sys_platform == "win32"'},
    }

    assert applies_here(package)


def test_dev_dockerfile_installs_only_the_root_lock() -> None:
    dockerfile_dev = (REPO_ROOT / "Dockerfile.dev").read_text()
    install_lines = [
        line for line in dockerfile_dev.splitlines() if "poetry install" in line
    ]

    assert len(install_lines) == 1, "a second install would re-resolve past the lock"
    assert re.search(r"--with api,fetch,ml,dev\b", install_lines[0])
    assert "COPY api-service" not in dockerfile_dev
    assert "WORKDIR /app/api" not in dockerfile_dev
