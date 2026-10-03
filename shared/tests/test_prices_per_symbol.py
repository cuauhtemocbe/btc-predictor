"""
Tests for storing prices per asset (issue #100).

Covers the Gherkin criteria:
1. Alembic upgrade and downgrade both run cleanly on a database with data
2. The same timestamp for two symbols succeeds; (symbol, timestamp) twice fails
3. Existing BTC behavior is unchanged (default symbol)
4. The migration deletes the source='coingecko' rows

The migration tests run against a scratch database (``<test db>_migration``) so
they never touch the schema the rest of the suite is using.
"""

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.config import settings
from shared.db.models import DEFAULT_SYMBOL, Model, Price
from testdb import ensure_database

REPO_ROOT = Path(__file__).resolve().parents[2]
REVISION_BEFORE = "a3f7c9e1d2b4"
TIMESTAMP = datetime(2026, 5, 16, 0, 0, tzinfo=UTC)


def _price(symbol: str | None = None, timestamp: datetime = TIMESTAMP) -> Price:
    values = {
        "timestamp": timestamp,
        "open": Decimal("100"),
        "high": Decimal("110"),
        "low": Decimal("90"),
        "close": Decimal("105"),
        "volume": Decimal("1"),
        "source": "binance",
    }
    if symbol is not None:
        values["symbol"] = symbol
    return Price(**values)


def _model(symbol: str | None = None, version: str = "1", **overrides: Any) -> Model:
    values: dict[str, Any] = {
        "name": "linear_v1",
        "version": version,
        "params": {},
        "artifact": b"artifact",
        "trained_at": TIMESTAMP,
        "train_from": date(2026, 1, 1),
        "train_to": date(2026, 5, 1),
        "is_active": False,
        "timeframe": "1d",
    }
    values.update(overrides)
    if symbol is not None:
        values["symbol"] = symbol
    return Model(**values)


class TestSymbolUniqueness:
    """Scenario: Inserting the same timestamp for two different symbols."""

    def test_same_timestamp_for_two_symbols_succeeds(self, db_session: Session) -> None:
        db_session.add_all([_price("BTCUSDT"), _price("PAXGUSDT")])
        db_session.commit()

        symbols = {
            row.symbol
            for row in db_session.query(Price).filter(Price.timestamp == TIMESTAMP)
        }
        assert symbols == {"BTCUSDT", "PAXGUSDT"}

    def test_same_symbol_and_timestamp_twice_is_rejected(
        self, db_session: Session
    ) -> None:
        db_session.add(_price("PAXGUSDT"))
        db_session.commit()

        db_session.add(_price("PAXGUSDT"))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_symbol_defaults_to_btc(self, db_session: Session) -> None:
        db_session.add(_price())
        db_session.commit()

        assert db_session.query(Price).one().symbol == DEFAULT_SYMBOL == "BTCUSDT"


class TestModelSymbolUniqueness:
    """The same model can exist once per asset."""

    def test_same_name_and_version_for_two_symbols_succeeds(
        self, db_session: Session
    ) -> None:
        db_session.add_all([_model("BTCUSDT"), _model("PAXGUSDT")])
        db_session.commit()

        assert db_session.query(Model).count() == 2

    def test_same_symbol_name_and_version_twice_is_rejected(
        self, db_session: Session
    ) -> None:
        db_session.add(_model("PAXGUSDT"))
        db_session.commit()

        db_session.add(_model("PAXGUSDT"))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_one_active_version_per_symbol_name_and_timeframe(
        self, db_session: Session
    ) -> None:
        db_session.add_all(
            [
                _model("BTCUSDT", version="1", is_active=True),
                _model("PAXGUSDT", version="1", is_active=True),
            ]
        )
        db_session.commit()

        db_session.add(_model("PAXGUSDT", version="2", is_active=True))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_symbol_defaults_to_btc(self, db_session: Session) -> None:
        db_session.add(_model())
        db_session.commit()

        assert db_session.query(Model).one().symbol == DEFAULT_SYMBOL


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
    """An empty scratch database, kept between runs and emptied by schema reset.

    Emptying the schema avoids ``DROP DATABASE``, which forces a slow Postgres
    checkpoint.
    """
    url = make_url(settings.database_url)
    url = url.set(database=f"{url.database}_migration")
    ensure_database(url)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    yield url.render_as_string(hide_password=False), engine
    engine.dispose()


def _seed_before_migration(engine: Engine) -> None:
    """Rows as they exist in production before the migration."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO btc_prices (timestamp, open, high, low, close, volume,"
                " source) VALUES (:ts, 1, 2, 1, 2, 1, :source)"
            ),
            [
                {"ts": datetime(2026, 5, 14, tzinfo=UTC), "source": "coingecko"},
                {"ts": datetime(2026, 5, 15, tzinfo=UTC), "source": "coingecko"},
                {"ts": datetime(2026, 5, 16, tzinfo=UTC), "source": "binance"},
            ],
        )
        connection.execute(
            text(
                "INSERT INTO models (id, name, version, params, artifact, trained_at,"
                " train_from, train_to, is_active, timeframe) VALUES (1, 'linear_v1',"
                " '1', '{}', 'x', now(), '2026-01-01', '2026-05-01', true, '1d')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO predictions (model_id, predicted_for, timeframe,"
                " predicted_at, price_at_prediction, predicted_price) VALUES"
                " (1, '2026-05-17', '1d', now(), 100, 101)"
            )
        )


@pytest.mark.slow
class TestMigration:
    def test_upgrade_keeps_binance_rows_as_btc_and_drops_coingecko(
        self, migration_db: tuple[str, Engine]
    ) -> None:
        """Scenario: upgrade on a database with data, CoinGecko rows deleted."""
        url, engine = migration_db
        _alembic(url, "upgrade", REVISION_BEFORE)
        _seed_before_migration(engine)

        _alembic(url, "upgrade", "head")

        with engine.connect() as connection:
            prices = connection.execute(
                text("SELECT symbol, source, timestamp FROM prices")
            ).all()
            tables = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables"
                        " WHERE table_schema = 'public'"
                    )
                ).scalars()
            )
            model_rows = connection.execute(text("SELECT symbol FROM models"))
            predictions = connection.execute(
                text("SELECT count(*) FROM predictions")
            ).scalar()
            model_symbols = list(model_rows.scalars())
        assert [(p.symbol, p.source) for p in prices] == [("BTCUSDT", "binance")]
        assert "btc_prices" not in tables
        assert model_symbols == ["BTCUSDT"]
        assert predictions == 1, "predictions survive and keep their model"

    def test_upgraded_schema_enforces_uniqueness_per_symbol(
        self, migration_db: tuple[str, Engine]
    ) -> None:
        url, engine = migration_db
        _alembic(url, "upgrade", "head")

        insert = text(
            "INSERT INTO prices (symbol, timestamp, open, high, low, close, volume,"
            " source) VALUES (:symbol, :ts, 1, 2, 1, 2, 1, 'binance')"
        )
        with engine.begin() as connection:
            connection.execute(insert, {"symbol": "BTCUSDT", "ts": TIMESTAMP})
            connection.execute(insert, {"symbol": "PAXGUSDT", "ts": TIMESTAMP})
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(insert, {"symbol": "BTCUSDT", "ts": TIMESTAMP})

    def test_downgrade_restores_the_single_asset_schema(
        self, migration_db: tuple[str, Engine]
    ) -> None:
        """Scenario: downgrade on a database with data, then upgrade again."""
        url, engine = migration_db
        _alembic(url, "upgrade", "head")
        with engine.begin() as connection:
            for symbol in ("BTCUSDT", "PAXGUSDT"):
                connection.execute(
                    text(
                        "INSERT INTO prices (symbol, timestamp, open, high, low,"
                        " close, volume, source) VALUES (:symbol, :ts, 1, 2, 1, 2,"
                        " 1, 'binance')"
                    ),
                    {"symbol": symbol, "ts": TIMESTAMP},
                )
                connection.execute(
                    text(
                        "INSERT INTO models (symbol, name, version, params, artifact,"
                        " trained_at, train_from, train_to, is_active, timeframe)"
                        " VALUES (:symbol, 'linear_v1', '1', '{}', 'x', now(),"
                        " '2026-01-01', '2026-05-01', true, '1d')"
                    ),
                    {"symbol": symbol},
                )

        _alembic(url, "downgrade", REVISION_BEFORE)

        with engine.connect() as connection:
            tables = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables"
                        " WHERE table_schema = 'public'"
                    )
                ).scalars()
            )
            price_columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_name = 'btc_prices'"
                    )
                ).scalars()
            )
            model_columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_name = 'models'"
                    )
                ).scalars()
            )
            remaining_prices = connection.execute(
                text("SELECT count(*) FROM btc_prices")
            ).scalar()
            remaining_models = connection.execute(
                text("SELECT count(*) FROM models")
            ).scalar()
        assert "prices" not in tables
        assert "btc_prices" in tables
        assert "symbol" not in price_columns | model_columns
        assert remaining_prices == remaining_models == 1, "only BTC rows can survive"

        _alembic(url, "upgrade", "head")
