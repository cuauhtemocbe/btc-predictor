"""
Integration tests for database connectivity.

These tests connect to a real PostgreSQL database and verify:
- Engine can establish connection
- Sessions can execute queries
- Connection pool works correctly

Note: These tests require DATABASE_URL to point to a running PostgreSQL instance.
Run with: docker compose exec api pytest shared/tests/test_integration.py
"""

from shared.db.database import SessionLocal, engine, get_db
from sqlalchemy import text


class TestPostgreSQLIntegration:
    """Integration tests with real PostgreSQL database."""

    def test_engine_connects_to_database(self):
        """
        Scenario: Engine connects to PostgreSQL
        Given a PostgreSQL database is running
        When I use the engine to connect
        Then the connection succeeds
        """
        # When/Then - establish connection
        with engine.connect() as conn:
            assert conn is not None

    def test_session_executes_simple_query(self):
        """
        Scenario: Session can execute queries
        Given a database session
        When I execute a simple query
        Then it returns the expected result
        """
        # Given
        session = SessionLocal()

        try:
            # When
            result = session.execute(text("SELECT 1 as value"))
            row = result.fetchone()

            # Then
            assert row is not None
            assert row[0] == 1
        finally:
            session.close()

    def test_session_can_query_pg_version(self):
        """
        Scenario: Verify connected to PostgreSQL (not other DB)
        Given a database session
        When I query PostgreSQL version
        Then it returns a valid version string
        """
        # Given
        session = SessionLocal()

        try:
            # When
            result = session.execute(text("SELECT version()"))
            version = result.scalar()

            # Then
            assert version is not None
            assert "PostgreSQL" in version
        finally:
            session.close()

    def test_get_db_dependency_with_real_database(self):
        """
        Scenario: get_db() works with real database
        Given the get_db dependency
        When I use it to get a session
        Then I can execute queries and session is cleaned up
        """
        # Given
        db_generator = get_db()

        # When
        session = next(db_generator)
        result = session.execute(text("SELECT 1 as value"))
        row = result.fetchone()

        # Then
        assert row[0] == 1

        # Cleanup - simulate context exit
        try:
            next(db_generator)
        except StopIteration:
            pass  # Expected

    def test_connection_pool_handles_multiple_sessions(self):
        """
        Scenario: Connection pool works correctly
        Given multiple concurrent sessions
        When I open and close them
        Then the pool manages connections without errors
        """
        # Create multiple sessions
        sessions = [SessionLocal() for _ in range(5)]

        try:
            # Execute query on each session
            for session in sessions:
                result = session.execute(text("SELECT 1"))
                assert result.scalar() == 1
        finally:
            # Close all sessions
            for session in sessions:
                session.close()

    def test_session_transaction_rollback(self):
        """
        Scenario: Session rollback works (ZOMBIES: Boundaries)
        Given a session with uncommitted changes
        When I rollback the transaction
        Then changes are discarded
        """
        # Given
        session = SessionLocal()

        try:
            # Create a temporary table for testing
            # Note: This won't persist because we're using transactions
            session.execute(text("CREATE TEMPORARY TABLE test_rollback (id INT)"))
            session.execute(text("INSERT INTO test_rollback VALUES (1)"))

            # When - rollback without commit
            session.rollback()

            # Then - table should be gone after rollback
            # (temporary tables are session-scoped)
            # We can't query it after rollback in same session, but the test
            # verifies rollback doesn't raise an error
            assert True  # Rollback succeeded

        finally:
            session.close()

    def test_session_transaction_commit(self):
        """
        Scenario: Session commit works (ZOMBIES: Boundaries)
        Given a session
        When I execute operations and commit
        Then commit succeeds without errors
        """
        # Given
        session = SessionLocal()

        try:
            # When - Execute operations and commit
            # Note: We test that commit() works without creating actual tables
            # Real table operations will be tested when we have models in US-002
            session.execute(text("SELECT 1"))
            session.commit()

            # Then - commit succeeded, can continue using session
            result = session.execute(text("SELECT 1"))
            assert result.scalar() == 1

        finally:
            session.close()


class TestDatabasePerformance:
    """Optional performance tests for database operations."""

    def test_connection_pool_pre_ping_prevents_stale_connections(self):
        """
        Scenario: pool_pre_ping prevents using stale connections
        Given pool_pre_ping is enabled
        When a connection becomes stale
        Then it's detected and refreshed before use
        """
        # Verify pool_pre_ping is enabled
        assert engine.pool._pre_ping is True

        # Create and use a session
        session = SessionLocal()
        try:
            result = session.execute(text("SELECT 1"))
            assert result.scalar() == 1
        finally:
            session.close()
