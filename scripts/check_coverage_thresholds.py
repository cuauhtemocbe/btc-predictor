"""Fail when a critical module is below its minimum line coverage (#68).

The global ``--cov-fail-under`` gate can stay green while a trainer, a model or
the backtest code is barely exercised. This script reads the ``coverage.xml``
that ``pytest --cov`` already wrote, compares every module listed in
``[tool.coverage_thresholds]`` of ``pyproject.toml`` with its minimum, and exits
non-zero naming each module that is below it or absent from the report.

Usage (inside the ``api`` container, after the coverage run)::

    python scripts/check_coverage_thresholds.py /tmp/coverage.xml
"""

import argparse
import sys
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "pyproject.toml"
CONFIG_SECTION = "coverage_thresholds"

# Inside the container ``api-service/`` is mounted as ``api/``, so coverage.xml
# names its files ``api/api/main.py``. Map them back to repo paths, exactly as
# the ``sonar-coverage`` Makefile target does.
CONTAINER_PREFIX = "api/"
REPO_PREFIX = "api-service/"


@dataclass(frozen=True)
class FileCoverage:
    """Executable and executed line counts of one source file."""

    covered: int
    total: int

    @property
    def percent(self) -> float:
        # A file without executable lines (an empty ``__init__.py``) has
        # nothing left uncovered.
        return 100.0 if self.total == 0 else 100.0 * self.covered / self.total

    def __add__(self, other: "FileCoverage") -> "FileCoverage":
        return FileCoverage(self.covered + other.covered, self.total + other.total)


@dataclass(frozen=True)
class Failure:
    """One module that does not meet its threshold."""

    module: str
    minimum: float
    coverage: float | None  # None when the module is not in the report

    def describe(self) -> str:
        if self.coverage is None:
            return (
                f"{self.module}: not in the coverage report "
                f"(minimum {self.minimum:g}%); no test imports it or the path is wrong"
            )
        return f"{self.module}: {self.coverage:.1f}% covered, minimum {self.minimum:g}%"


def normalize_filename(filename: str) -> str:
    """Return the repo-relative path for a ``coverage.xml`` ``filename``."""
    if filename.startswith(CONTAINER_PREFIX):
        return REPO_PREFIX + filename[len(CONTAINER_PREFIX) :]
    return filename


def parse_coverage_xml(path: Path) -> dict[str, FileCoverage]:
    """Read per-file line coverage, keyed by repo-relative path."""
    files: dict[str, FileCoverage] = {}
    for cls in ET.parse(path).getroot().iter("class"):
        name = normalize_filename(cls.get("filename", ""))
        lines = cls.findall("./lines/line")
        covered = sum(1 for line in lines if int(line.get("hits", "0")) > 0)
        current = FileCoverage(covered, len(lines))
        files[name] = files[name] + current if name in files else current
    return files


def load_thresholds(path: Path) -> dict[str, float]:
    """Read ``[tool.coverage_thresholds]`` and validate every entry."""
    with path.open("rb") as handle:
        table = tomllib.load(handle).get("tool", {}).get(CONFIG_SECTION)
    if not table:
        raise ValueError(f"{path} has no [tool.{CONFIG_SECTION}] section")
    for module, minimum in table.items():
        is_number = isinstance(minimum, int | float) and not isinstance(minimum, bool)
        if not is_number or not 0 <= minimum <= 100:
            raise ValueError(
                f"threshold for {module} must be a number between 0 and 100, "
                f"got {minimum!r}"
            )
    return {module: float(minimum) for module, minimum in table.items()}


def evaluate(
    thresholds: dict[str, float], coverage: dict[str, FileCoverage]
) -> list[Failure]:
    """List the modules that are below their minimum or missing."""
    failures = []
    for module, minimum in sorted(thresholds.items()):
        measured = coverage.get(module)
        if measured is None:
            failures.append(Failure(module, minimum, None))
        elif measured.percent < minimum:
            failures.append(Failure(module, minimum, measured.percent))
    return failures


def format_report(
    thresholds: dict[str, float],
    coverage: dict[str, FileCoverage],
    failures: list[Failure],
) -> str:
    """Render the per-module table and the verdict."""
    failed = {failure.module for failure in failures}
    width = max(len(module) for module in thresholds)
    rows = []
    for module, minimum in sorted(thresholds.items()):
        measured = coverage.get(module)
        shown = "missing" if measured is None else f"{measured.percent:.1f}%"
        status = "FAIL" if module in failed else "ok"
        rows.append(f"  {status:<4}  {module:<{width}}  {shown:>8}  min {minimum:g}%")
    if not failures:
        verdict = f"All {len(thresholds)} critical modules meet their threshold."
        return "\n".join([*rows, verdict])
    details = [f"  {failure.describe()}" for failure in failures]
    verdict = (
        f"Coverage threshold check FAILED: {len(failures)} of "
        f"{len(thresholds)} critical modules."
    )
    return "\n".join([*rows, "", verdict, *details])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("coverage_xml", type=Path, help="coverage.xml from pytest-cov")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="TOML file with [tool.coverage_thresholds] (default: pyproject.toml)",
    )
    args = parser.parse_args(argv)

    try:
        thresholds = load_thresholds(args.config)
        coverage = parse_coverage_xml(args.coverage_xml)
    except (OSError, ValueError, ET.ParseError) as error:
        print(f"Cannot check coverage thresholds: {error}", file=sys.stderr)
        return 2

    failures = evaluate(thresholds, coverage)
    report = format_report(thresholds, coverage, failures)
    print(report, file=sys.stderr if failures else sys.stdout)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
