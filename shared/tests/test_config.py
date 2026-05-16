"""
Tests for configuration module.

Covers all Gherkin scenarios from US-001:
- Load DATABASE_URL from environment
- Missing DATABASE_URL raises error
- Empty DATABASE_URL raises error
"""

import pytest
from pydantic import ValidationError
from btc_shared.config import Settings


class TestConfigurationLoading:
    """Test loading configuration from environment variables."""

    def test_load_database_url_from_environment(self, monkeypatch):
        """
        Scenario: Load DATABASE_URL from environment
        Given the environment variable DATABASE_URL is set to "postgresql://user:pass@localhost/btcdb"
        When I import btc_shared.config.Settings
        Then the settings.database_url attribute equals "postgresql://user:pass@localhost/btcdb"
        """
        # Given
        expected_url = "postgresql://user:pass@localhost/btcdb"
        monkeypatch.setenv("DATABASE_URL", expected_url)

        # When
        settings = Settings()

        # Then
        assert settings.database_url == expected_url

    def test_database_url_with_different_formats(self, monkeypatch):
        """Test that various PostgreSQL URL formats are accepted."""
        test_urls = [
            "postgresql://user:pass@localhost/db",
            "postgresql://user:pass@localhost:5432/db",
            "postgresql://user:pass@192.168.1.1:5432/db",
            "postgresql://user@localhost/db",  # No password
        ]

        for url in test_urls:
            monkeypatch.setenv("DATABASE_URL", url)
            settings = Settings()
            assert settings.database_url == url


class TestConfigurationValidation:
    """Test configuration validation and error handling."""

    def test_missing_database_url_raises_validation_error(self, clean_env):
        """
        Scenario: Missing DATABASE_URL raises error
        Given the DATABASE_URL environment variable is not set
        When I attempt to import btc_shared.config.Settings
        Then a ValidationError is raised with message "DATABASE_URL is required"
        """
        # Given: DATABASE_URL is not set (clean_env fixture)

        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            Settings()

        # Verify the error is about database_url field
        error = exc_info.value
        assert "database_url" in str(error).lower()

    def test_empty_database_url_raises_validation_error(self, monkeypatch):
        """
        Scenario: Empty DATABASE_URL raises error (ZOMBIES: Zero case)
        Given the DATABASE_URL environment variable is set to empty string
        When I attempt to create Settings
        Then a ValidationError is raised
        """
        # Given
        monkeypatch.setenv("DATABASE_URL", "")

        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            Settings()

        # Verify the error is about database_url field
        error = exc_info.value
        assert "database_url" in str(error).lower()

    def test_whitespace_only_database_url_raises_validation_error(self, monkeypatch):
        """
        Scenario: Whitespace-only DATABASE_URL raises error (ZOMBIES: Zero case)
        Given the DATABASE_URL is only whitespace
        When I attempt to create Settings
        Then a ValidationError is raised
        """
        # Given
        monkeypatch.setenv("DATABASE_URL", "   ")

        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            Settings()

        error = exc_info.value
        assert "database_url" in str(error).lower()


class TestConfigurationSecurity:
    """Test security-related configuration behavior."""

    def test_settings_can_be_created_with_credentials(self, mock_database_url):
        """
        Scenario: DATABASE_URL with credentials can be loaded (ZOMBIES: Security)
        Given a DATABASE_URL containing credentials
        When I create Settings instance
        Then it should work without exposing credentials in application logs

        Note: Settings repr() will show credentials - developers must be careful
        not to log Settings instances directly. Use logging config to avoid
        accidentally logging credentials.
        """
        # Given/When
        settings = Settings()

        # Then - settings loaded successfully
        assert settings.database_url == mock_database_url
        assert "testuser" in settings.database_url
        assert "testpass" in settings.database_url

        # Document security concern: don't log Settings directly
        # In production, use structured logging and never log connection strings
