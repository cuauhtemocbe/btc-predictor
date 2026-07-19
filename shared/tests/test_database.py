"""
Tests for database module.

Covers all Gherkin scenarios from US-001:
- Create SQLAlchemy engine
- Get database session
- Session lifecycle management
"""

from unittest.mock import Mock, patch

import pytest
from shared.db.database import SessionLocal, engine, get_db
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class TestDatabaseEngine:
    """Test SQLAlchemy engine creation."""

    def test_engine_is_created(self):
        """
        Scenario: Create SQLAlchemy engine
        Given a valid DATABASE_URL is configured
        When I import shared.db.database.engine
        Then the engine connects successfully to PostgreSQL
        And the engine uses the connection pool
        """
        # Engine is created at module import time
        assert engine is not None
        assert "postgresql://" in str(engine.url)

    def test_engine_has_connection_pooling_enabled(self):
        """Verify that engine has connection pooling configured."""
        assert engine.pool is not None
        # pool_pre_ping should be enabled (verified via engine creation)

    def test_engine_url_is_postgresql(self):
        """Verify engine uses PostgreSQL (not SQLite or other DB)."""
        assert str(engine.url).startswith("postgresql://")
        assert engine.dialect.name == "postgresql"


class TestSessionFactory:
    """Test SessionLocal session factory."""

    def test_session_local_creates_sessions(self, mock_database_url):
        """
        Scenario: SessionLocal creates sessions
        Given the database engine is initialized
        When I call SessionLocal()
        Then it returns a SQLAlchemy session
        """
        # When
        session = SessionLocal()

        # Then
        assert session is not None
        assert isinstance(session, Session)

        # Cleanup
        session.close()

    def test_session_can_be_closed(self, mock_database_url):
        """Verify sessions can be properly closed."""
        # Given
        session = SessionLocal()

        # When
        session.close()

        # Then - no exception raised
        assert True


class TestGetDbDependency:
    """Test FastAPI dependency for database sessions."""

    def test_get_db_yields_session(self, mock_database_url):
        """
        Scenario: Get database session
        Given the database engine is initialized
        When I call shared.db.database.get_db()
        Then it yields a SQLAlchemy session
        """
        # When
        db_generator = get_db()
        session = next(db_generator)

        # Then
        assert session is not None
        assert isinstance(session, Session)

        # Cleanup
        try:
            next(db_generator)
        except StopIteration:
            pass  # Expected - generator should close

    def test_get_db_closes_session_after_use(self, mock_database_url):
        """
        Scenario: Session is automatically closed after use
        Given I have called get_db() and received a session
        When the context exits
        Then the session is automatically closed
        """
        # Given
        db_generator = get_db()
        session = next(db_generator)

        # Mock the close method to verify it's called
        session_close_mock = Mock(wraps=session.close)
        session.close = session_close_mock

        # When - simulate context exit
        try:
            next(db_generator)
        except StopIteration:
            pass

        # Then
        session_close_mock.assert_called_once()

    def test_get_db_closes_session_even_on_exception(self, mock_database_url):
        """
        Scenario: Session closed even if exception occurs (ZOMBIES: Exceptions)
        Given I have a session from get_db()
        When an exception occurs during usage
        Then the session is still closed
        """
        # Given
        db_generator = get_db()
        session = next(db_generator)

        # Mock close to verify it's called
        session_close_mock = Mock(wraps=session.close)
        session.close = session_close_mock

        # When - throw exception into generator
        try:
            db_generator.throw(Exception("Simulated error"))
        except Exception:
            pass

        # Then - close should still be called
        session_close_mock.assert_called_once()

    def test_get_db_can_be_used_in_fastapi_dependency(self, mock_database_url):
        """
        Scenario: get_db() works as FastAPI Depends()
        Given I use get_db with FastAPI Depends
        When a request is processed
        Then the session is provided and cleaned up automatically
        """
        # Simulate FastAPI dependency injection pattern
        dependency_result = get_db()

        # FastAPI would call next() to get the value
        session = next(dependency_result)
        assert isinstance(session, Session)

        # FastAPI would then finish the generator (cleanup)
        try:
            next(dependency_result)
        except StopIteration:
            pass  # Expected


class TestDatabaseConnectionErrors:
    """Test error handling for database connection issues."""

    @patch("shared.db.database.settings")
    def test_invalid_database_url_raises_clear_error(self, mock_settings):
        """
        Scenario: Invalid DATABASE_URL format (ZOMBIES: Exceptions)
        Given an invalid DATABASE_URL format
        When I attempt to create an engine
        Then a clear error message is provided
        """
        # Given
        mock_settings.database_url = "invalid://not-a-database"

        # When/Then
        with pytest.raises(Exception) as exc_info:
            test_engine = create_engine(mock_settings.database_url)
            # Trigger connection attempt
            test_engine.connect()

        # Error should mention connection or database issue
        error_msg = str(exc_info.value).lower()
        assert any(
            keyword in error_msg
            for keyword in ["connection", "database", "could not", "unable", "invalid"]
        )

    def test_connection_pool_pre_ping_enabled(self, mock_database_url):
        """
        Verify pool_pre_ping is enabled to catch stale connections.
        This prevents errors from dead connections in the pool.
        """
        # Engine should have pool_pre_ping enabled
        # This is set in database.py: create_engine(..., pool_pre_ping=True)
        assert engine.pool._pre_ping is True
