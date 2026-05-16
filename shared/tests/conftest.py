"""
Pytest configuration and fixtures for shared package tests.
"""

import pytest
import os


@pytest.fixture
def clean_env(monkeypatch):
    """
    Fixture that ensures DATABASE_URL is not set in environment.
    Useful for testing validation errors.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture
def mock_database_url(monkeypatch):
    """
    Fixture that sets a valid DATABASE_URL for testing.
    """
    test_url = "postgresql://testuser:testpass@localhost:5432/testdb"
    monkeypatch.setenv("DATABASE_URL", test_url)
    return test_url
