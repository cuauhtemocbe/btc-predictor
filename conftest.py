"""
Root-level pytest configuration for btc-predictor.

Provides centralized DB fixtures with session-scoped schema creation
to eliminate race conditions and reduce DDL overhead.
"""

import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, tzinfo
from typing import Self

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from testdb import database_name_for_tests, ensure_database


def _limit_threads_per_xdist_worker() -> None:
    """Keep numeric libraries to one thread per xdist worker.

    TensorFlow, XGBoost and BLAS each default to one thread per core. With N
    workers that oversubscribes the CPU and makes the parallel run slower than
    the serial one. Must run before those libraries are imported.
    """
    if os.environ.get("PYTEST_XDIST_WORKER"):
        for variable in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "TF_NUM_INTRAOP_THREADS",
            "TF_NUM_INTEROP_THREADS",
        ):
            os.environ.setdefault(variable, "1")


def _point_tests_at_test_database() -> None:
    """Redirect DATABASE_URL to the test database before anything reads it.

    Must run before ``shared.config`` is imported: ``settings`` and the
    module-level engine in ``shared.db.database`` are built at import time,
    and every test module inherits them.
    """
    dev_url = make_url(os.environ["DATABASE_URL"])
    url = dev_url.set(
        database=database_name_for_tests(
            dev_url.database, os.environ.get("PYTEST_XDIST_WORKER")
        )
    )
    ensure_database(url)
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)


_limit_threads_per_xdist_worker()
_point_tests_at_test_database()

from shared.config import settings  # noqa: E402
from shared.db.models import Base, Model, Prediction, Price  # noqa: E402


@pytest.fixture(scope="session")
def db_engine_session():
    """
    Session-scoped SQLAlchemy engine with automatic schema management.

    Creates database schema ONCE at the start of the test session
    and drops it at the end. This eliminates the overhead of creating/
    dropping tables for each test.

    Uses StaticPool for thread safety with pytest-xdist.
    """
    print("\n🔧 [SETUP] Creating test database schema...")
    # drop_all below wipes the schema: never let it run against a dev database
    assert "_test" in make_url(settings.database_url).database, (
        "tests must run against a *_test database"
    )
    engine = create_engine(
        settings.database_url,
        echo=False,
        poolclass=StaticPool,  # Thread-safe for parallel tests
    )

    # Drop all existing tables first (clean slate)
    Base.metadata.drop_all(engine)

    # Create all tables
    Base.metadata.create_all(engine)
    print("🔧 [SETUP] Database schema created successfully!")

    yield engine

    # Cleanup at end of session
    print("\n🔧 [CLEANUP] Dropping test database schema...")
    Base.metadata.drop_all(engine)
    engine.dispose()
    print("🔧 [CLEANUP] Cleanup complete!")


@pytest.fixture(scope="function")
def db_session(db_engine_session):
    """
    Function-scoped database session with automatic rollback.

    Provides test isolation using nested transactions (savepoints).
    Changes made during a test are rolled back automatically,
    ensuring each test starts with a clean state.

    Does NOT recreate the schema - only manages data.
    """
    connection = db_engine_session.connect()
    transaction = connection.begin()

    Session = sessionmaker(bind=connection, expire_on_commit=False)
    session = Session()

    # Clean existing data (not schema)
    session.execute(Prediction.__table__.delete())
    session.execute(Model.__table__.delete())
    session.execute(Price.__table__.delete())
    session.commit()

    # Start a savepoint (nested transaction)
    connection.begin_nested()

    # Whenever a transaction ends -- via commit() OR via rollback() after
    # a caught error (e.g. a test asserting an IntegrityError) -- restart
    # the savepoint. Checking connection.in_nested_transaction() directly
    # (SQLAlchemy's documented pattern for this) is what makes this robust
    # to error-triggered rollbacks: inferring the restart condition from
    # the SQLAlchemy Transaction object's .nested/._parent chain instead
    # (as this used to) does not reliably fire after session.rollback(),
    # which leaves the connection's savepoint dead for the rest of the
    # (session-scoped, StaticPool-shared) test run -- corrupting every
    # later test that reuses this connection.
    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(session, trans):
        if not connection.in_nested_transaction():
            connection.begin_nested()

    yield session

    # Cleanup: rollback all changes
    session.close()
    transaction.rollback()
    connection.close()


# Compatibility alias for tests that use 'session' instead of 'db_session'
@pytest.fixture(scope="function")
def session(db_session):
    """Alias for db_session to support tests that use 'session' parameter."""
    return db_session


# The instant of the #173 scenario: 03:00 UTC on 2026-10-04 is still 2026-10-03
# (21:00) in America/Mexico_City.
FROZEN_UTC_NOW = datetime(2026, 10, 4, 3, 0, tzinfo=UTC)


class _FrozenDatetime(datetime):
    """``datetime`` whose ``now()`` returns ``FROZEN_UTC_NOW``."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Self:
        return cls.fromtimestamp(FROZEN_UTC_NOW.timestamp(), tz)


@pytest.fixture
def mexico_city_at_0300_utc(monkeypatch: pytest.MonkeyPatch) -> Iterator[datetime]:
    """Set ``TZ=America/Mexico_City`` and the clock to 2026-10-04 03:00 UTC.

    Freezes the clock behind ``shared.utils.utc_today`` only, so a job that still
    calls ``date.today()`` sees the real date and the test fails.
    """
    previous_tz = os.environ.get("TZ")
    os.environ["TZ"] = "America/Mexico_City"
    time.tzset()
    monkeypatch.setattr("shared.utils.datetime", _FrozenDatetime)
    try:
        yield FROZEN_UTC_NOW
    finally:
        if previous_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous_tz
        time.tzset()
