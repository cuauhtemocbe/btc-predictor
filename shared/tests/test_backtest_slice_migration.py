"""
Tests for backtest_results.evaluation_slice (#106).

The column labels each backtest row as part of the ``validation`` slice (the only
data allowed to inform choices) or the ``test`` slice (headline, out-of-sample
metrics). Rows stored before the column existed stay NULL ("unsplit").
"""

import os
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from shared.config import settings
from shared.db.models import BacktestResult
from testdb import ensure_database

REPO_ROOT = Path(__file__).resolve().parents[2]
REVISION_BEFORE = "b7e2d94c1f30"


def _result(evaluation_slice: str | None = None) -> BacktestResult:
    return BacktestResult(
        backtest_run_id=uuid4(),
        predicted_for=date(2024, 6, 10),
        predicted_at=datetime(2024, 6, 9, tzinfo=UTC),
        price_at_prediction=Decimal("100"),
        predicted_price=Decimal("101"),
        actual_price=Decimal("102"),
        model_params={"model_name": "linear"},
        evaluation_slice=evaluation_slice,
    )


class TestEvaluationSliceColumn:
    @pytest.mark.parametrize("value", ["validation", "test", None])
    def test_accepts_validation_test_and_unsplit(self, db_session, value):
        db_session.add(_result(value))
        db_session.commit()

        assert db_session.query(BacktestResult).one().evaluation_slice == value

    def test_defaults_to_unsplit(self, db_session):
        db_session.add(_result())
        db_session.commit()

        assert db_session.query(BacktestResult).one().evaluation_slice is None

    @pytest.mark.parametrize("value", ["train", "TEST", ""])
    def test_rejects_any_other_value(self, db_session, value):
        db_session.add(_result(value))

        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


def _alembic(database_url: str, *args: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "shared/alembic.ini", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.fixture
def migration_db():
    """A scratch database emptied by schema reset (no slow DROP DATABASE)."""
    url = make_url(settings.database_url)
    url = url.set(database=f"{url.database}_migration")
    ensure_database(url)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    yield url.render_as_string(hide_password=False), engine
    engine.dispose()


INSERT_LEGACY_ROW = text(
    "INSERT INTO backtest_results (backtest_run_id, predicted_for, predicted_at,"
    " price_at_prediction, predicted_price, actual_price)"
    " VALUES (:run_id, '2024-06-10', now(), 100, 101, 102)"
)


def _columns(engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_name = 'backtest_results'"
                )
            ).scalars()
        )


@pytest.mark.slow
class TestMigration:
    def test_upgrade_keeps_legacy_rows_unsplit_and_enforces_the_check(
        self, migration_db
    ):
        url, engine = migration_db
        _alembic(url, "upgrade", REVISION_BEFORE)
        with engine.begin() as connection:
            connection.execute(INSERT_LEGACY_ROW, {"run_id": str(uuid4())})

        _alembic(url, "upgrade", "head")

        with engine.connect() as connection:
            slices = (
                connection.execute(
                    text("SELECT evaluation_slice FROM backtest_results")
                )
                .scalars()
                .all()
            )
        assert slices == [None]
        set_train_slice = text("UPDATE backtest_results SET evaluation_slice = 'train'")
        transaction = engine.begin()
        with pytest.raises(IntegrityError), transaction as connection:
            connection.execute(set_train_slice)

    def test_downgrade_drops_the_column_and_upgrade_restores_it(self, migration_db):
        url, engine = migration_db
        _alembic(url, "upgrade", "head")
        assert "evaluation_slice" in _columns(engine)

        _alembic(url, "downgrade", REVISION_BEFORE)
        assert "evaluation_slice" not in _columns(engine)

        _alembic(url, "upgrade", "head")
        assert "evaluation_slice" in _columns(engine)
