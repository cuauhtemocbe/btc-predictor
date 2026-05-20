"""
Configuration module using pydantic-settings.

Loads environment variables and validates required configuration.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Attributes:
        database_url: PostgreSQL connection string (required)
    """

    database_url: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore extra env vars
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url_not_empty(cls, v: str) -> str:
        """Ensure database_url is not empty or whitespace-only."""
        if not v or not v.strip():
            raise ValueError("database_url cannot be empty")
        return v


# Global settings instance
settings = Settings()
