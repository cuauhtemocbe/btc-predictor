"""
Tests for migration d5a1c7e93b20: one active version per model family (#169).

The index on (symbol, name, timeframe) became one on (symbol, family,
timeframe). Rows saved before it can hold several active versions of a family;
the upgrade keeps the newest and deactivates the rest.
"""

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from shared.config import settings
from testdb import ensure_database

REPO_ROOT = Path(__file__).resolve().parents[2]
REVISION_BEFORE = "c4d8e1f2a9b3"
INDEX_NAME = "ix_models_one_active_version_per_name_timeframe"

INSERT_MODEL = text(
    "INSERT INTO models (symbol, name, version, params, artifact, trained_at,"
    " train_from, train_to, is_active, timeframe)"
    " VALUES (:symbol, :name, :version, '{}', 'x', :trained_at, '2024-01-01',"
    " '2024-05-01', :is_active, :timeframe)"
)


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
def migration_db() -> Iterator[tuple[str, Engine]]:
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


def _insert(
    engine: Engine,
    name: str,
    *,
    day: int,
    is_active: bool = True,
    symbol: str = "BTCUSDT",
    timeframe: str = "1d",
) -> None:
    params: dict[str, Any] = {
        "symbol": symbol,
        "name": name,
        "version": f"{name}-{day}-{symbol}-{timeframe}",
        "trained_at": datetime(2024, 6, day, tzinfo=UTC),
        "is_active": is_active,
        "timeframe": timeframe,
    }
    with engine.begin() as connection:
        connection.execute(INSERT_MODEL, params)


def _active(engine: Engine) -> set[tuple[str, str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT symbol, name, timeframe FROM models WHERE is_active ORDER BY id"
            )
        )
        return {(row.symbol, row.name, row.timeframe) for row in rows}


def _index_definition(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"),
                {"name": INDEX_NAME},
            ).scalar_one()
        )


@pytest.mark.slow
class TestMigration:
    def test_upgrade_keeps_only_the_newest_active_version_per_family(
        self, migration_db: tuple[str, Engine]
    ) -> None:
        url, engine = migration_db
        _alembic(url, "upgrade", REVISION_BEFORE)
        _insert(engine, "linear_v1", day=1)
        _insert(engine, "linear_v3", day=3)
        _insert(engine, "linear_v2", day=2)
        _insert(engine, "xgboost_v1", day=1)
        _insert(engine, "linear_v1", day=1, symbol="PAXGUSDT")
        _insert(engine, "linear_v1", day=1, timeframe="1w")
        _insert(engine, "linear_v0", day=4, is_active=False)

        _alembic(url, "upgrade", "head")

        assert _active(engine) == {
            ("BTCUSDT", "linear_v3", "1d"),
            ("BTCUSDT", "xgboost_v1", "1d"),
            ("PAXGUSDT", "linear_v1", "1d"),
            ("BTCUSDT", "linear_v1", "1w"),
        }

    def test_upgrade_breaks_a_trained_at_tie_with_the_highest_id(
        self, migration_db: tuple[str, Engine]
    ) -> None:
        url, engine = migration_db
        _alembic(url, "upgrade", REVISION_BEFORE)
        _insert(engine, "linear_v1", day=5)
        _insert(engine, "linear_v2", day=5)

        _alembic(url, "upgrade", "head")

        assert _active(engine) == {("BTCUSDT", "linear_v2", "1d")}

    def test_upgraded_index_rejects_two_active_versions_of_one_family(
        self, migration_db: tuple[str, Engine]
    ) -> None:
        url, engine = migration_db
        _alembic(url, "upgrade", "head")
        _insert(engine, "linear_v1", day=1)

        with pytest.raises(IntegrityError, match=INDEX_NAME):
            _insert(engine, "linear_v2", day=2)
        _insert(engine, "xgboost_v1", day=2)

    def test_downgrade_restores_the_per_name_index_and_upgrade_the_family_one(
        self, migration_db: tuple[str, Engine]
    ) -> None:
        url, engine = migration_db
        _alembic(url, "upgrade", "head")
        assert "regexp_replace" in _index_definition(engine)

        _alembic(url, "downgrade", REVISION_BEFORE)
        assert "regexp_replace" not in _index_definition(engine)
        _insert(engine, "linear_v1", day=1)
        _insert(engine, "linear_v2", day=2)

        _alembic(url, "upgrade", "head")
        assert "regexp_replace" in _index_definition(engine)
        assert _active(engine) == {("BTCUSDT", "linear_v2", "1d")}
