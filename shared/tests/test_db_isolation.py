"""
Tests for the per-worker test database isolation (issue #110).

The parallel-run scenarios spawn a nested ``pytest -n 2`` against a throwaway
"dev" database, so they never touch the databases the outer run is using.
"""

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import NamedTuple

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from shared.config import settings
from testdb import database_name_for_tests, ensure_database

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_DEV_DATABASE = "isolation_probe"

PROBE_TESTS = textwrap.dedent(
    """
    import os
    import time

    import pytest
    from sqlalchemy import text

    from shared.db.database import engine


    @pytest.mark.parametrize("n", range(4))
    def test_worker_writes_only_its_own_rows(n):
        worker = os.environ["PYTEST_XDIST_WORKER"]
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE IF NOT EXISTS worker_marker (worker text)")
            )
            connection.execute(
                text("INSERT INTO worker_marker VALUES (:worker)"), {"worker": worker}
            )
        time.sleep(1)  # keep both workers busy at the same time
        with engine.begin() as connection:
            seen = {
                row[0]
                for row in connection.execute(text("SELECT worker FROM worker_marker"))
            }
            database = connection.execute(text("SELECT current_database()")).scalar()
        with open(os.environ["PROBE_REPORT"], "a") as report:
            report.write(f"PROBE {worker} {database} {sorted(seen)}\\n")
        assert seen == {worker}
    """
)


def _probe_url(database: str):
    return make_url(settings.database_url).set(database=database)


def _reset_tables(url, *tables: str) -> None:
    """Empty a probe database by dropping tables.

    The probe databases are kept between runs (like ``<db>_test``) because
    ``DROP DATABASE`` forces a Postgres checkpoint and costs seconds each.
    """
    ensure_database(url)
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            for table in tables:
                connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def probe_dev_database():
    """A stand-in for the dev database, holding a sentinel row."""
    dev_url = _probe_url(PROBE_DEV_DATABASE)
    _reset_tables(dev_url, "dev_sentinel")
    for worker in ("gw0", "gw1"):
        _reset_tables(
            _probe_url(database_name_for_tests(PROBE_DEV_DATABASE, worker)),
            "worker_marker",
        )
    engine = create_engine(dev_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE dev_sentinel (id int)"))
        connection.execute(text("INSERT INTO dev_sentinel VALUES (1), (2), (3)"))
    yield dev_url, engine
    engine.dispose()


class ProbeRun(NamedTuple):
    returncode: int
    output: str  # what the nested pytest printed
    report: str  # lines the probe tests wrote from inside the workers


@pytest.fixture(scope="module")
def parallel_probe_run(probe_dev_database, tmp_path_factory):
    """Run the probe tests once under ``pytest -n 2`` against the stand-in dev DB."""
    dev_url, _ = probe_dev_database
    workdir = tmp_path_factory.mktemp("probe")
    probe = workdir / "test_probe.py"
    probe.write_text(PROBE_TESTS)
    report = workdir / "report.txt"

    env = {
        key: value
        for key, value in os.environ.items()
        # A nested run must not think it is an xdist worker or measure coverage
        if not key.startswith(("PYTEST_", "COV_CORE_"))
    }
    env["DATABASE_URL"] = dev_url.render_as_string(hide_password=False)
    env["PROBE_REPORT"] = str(report)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-n",
            "2",
            "-p",
            "conftest",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            "-q",
            str(probe),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return ProbeRun(
        returncode=completed.returncode,
        output=completed.stdout + completed.stderr,
        report=report.read_text() if report.exists() else "",
    )


class TestDatabaseNaming:
    def test_serial_run_uses_a_dedicated_test_database(self):
        assert database_name_for_tests("btcpredictor", None) == "btcpredictor_test"

    def test_each_worker_gets_its_own_database(self):
        names = {
            database_name_for_tests("btcpredictor", worker)
            for worker in ("gw0", "gw1", "gw2")
        }
        assert names == {
            "btcpredictor_test_gw0",
            "btcpredictor_test_gw1",
            "btcpredictor_test_gw2",
        }

    def test_naming_is_idempotent_for_inherited_urls(self):
        """Workers inherit the controller's already-redirected DATABASE_URL."""
        assert (
            database_name_for_tests("btcpredictor_test", "gw0")
            == "btcpredictor_test_gw0"
        )

    def test_suite_never_runs_against_the_dev_database(self):
        assert "_test" in make_url(settings.database_url).database


class TestParallelRun:
    @pytest.mark.slow
    def test_parallel_run_is_green(self, parallel_probe_run):
        """Scenario: Parallel run is green."""
        assert parallel_probe_run.returncode == 0, parallel_probe_run.output
        assert "4 passed" in parallel_probe_run.output

    @pytest.mark.slow
    def test_workers_do_not_share_data(self, parallel_probe_run):
        """Scenario: Workers do not share data."""
        assert parallel_probe_run.returncode == 0, parallel_probe_run.output
        reports = re.findall(
            r"PROBE (gw\d+) (\S+) (\[.*?\])", parallel_probe_run.report
        )
        databases = {worker: database for worker, database, _ in reports}
        assert set(databases) == {"gw0", "gw1"}, "both workers must run tests"
        assert databases == {
            "gw0": f"{PROBE_DEV_DATABASE}_test_gw0",
            "gw1": f"{PROBE_DEV_DATABASE}_test_gw1",
        }
        for worker, _, seen in reports:
            assert seen == f"['{worker}']"

    @pytest.mark.slow
    def test_dev_data_is_untouched(self, probe_dev_database, parallel_probe_run):
        """Scenario: Dev data is untouched."""
        _, engine = probe_dev_database
        assert parallel_probe_run.returncode == 0, parallel_probe_run.output
        with engine.connect() as connection:
            rows = connection.execute(text("SELECT id FROM dev_sentinel ORDER BY id"))
            assert [row[0] for row in rows] == [1, 2, 3]
            tables = connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            ).scalars()
            assert list(tables) == ["dev_sentinel"]
