"""
BTC Shared Package

Shared components for BTC Predictor services including:
- Database configuration and connection
- Shared models and utilities

Example usage:
    from shared.config import Settings
    from shared.db import engine, SessionLocal, get_db

    # Load configuration
    settings = Settings()
    print(settings.database_url)

    # Use database session
    db = SessionLocal()
    try:
        result = db.execute("SELECT 1")
    finally:
        db.close()

    # Use with FastAPI
    from fastapi import Depends
    @app.get("/users")
    def get_users(db: Session = Depends(get_db)):
        return {"users": []}
"""

__version__ = "0.1.0"

# Export key components for easy importing
from shared.config import Settings, settings
from shared.db import engine, SessionLocal, get_db

__all__ = [
    "__version__",
    "Settings",
    "settings",
    "engine",
    "SessionLocal",
    "get_db",
]
