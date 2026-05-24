"""
Root-level pytest configuration for btc-predictor.

Provides centralized DB fixtures with session-scoped schema creation
to eliminate race conditions and reduce DDL overhead.
"""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from shared.config import settings
from shared.db.models import Base, BtcPrice, Model, Prediction


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
    session.execute(BtcPrice.__table__.delete())
    session.commit()

    # Start a savepoint (nested transaction)
    session.begin_nested()

    # When application code calls commit(), restart the savepoint
    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(session, trans):
        if trans.nested and not trans._parent.nested:
            session.begin_nested()

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
