# BTC Shared Package

Shared package with database configuration and utilities for BTC Predictor services.

## Overview

This package provides centralized configuration and database connectivity for all BTC Predictor services (api, fetch_price, daily). It ensures consistent database connections and configuration across the application.

## Installation

This package is part of a Poetry workspace. Other services depend on it using:

```toml
[tool.poetry.dependencies]
btc-shared = {path = "../shared", develop = true}
```

## Usage

### Configuration

```python
from btc_shared.config import Settings

settings = Settings()
print(settings.database_url)  # Loaded from DATABASE_URL env var
```

### Database Connection

```python
from btc_shared.db.database import engine, SessionLocal, get_db

# Direct session usage
session = SessionLocal()
try:
    # Use session
    result = session.execute("SELECT 1")
finally:
    session.close()

# FastAPI dependency injection
from fastapi import Depends

@app.get("/")
def endpoint(db: Session = Depends(get_db)):
    # db session automatically managed
    return {"status": "ok"}
```

## Environment Variables

Required:
- `DATABASE_URL`: PostgreSQL connection string (e.g., `postgresql://user:pass@localhost/btcdb`)

## Development

```bash
# Install dependencies
cd shared
poetry install

# Run tests
pytest

# Run tests with coverage
pytest --cov=btc_shared --cov-report=term-missing
```

## Project Structure

```
shared/
├── pyproject.toml          # Poetry package definition
├── README.md               # This file
├── btc_shared/
│   ├── __init__.py        # Package exports
│   ├── config.py          # Settings (pydantic-settings)
│   └── db/
│       ├── __init__.py    # DB package exports
│       └── database.py    # Engine, SessionLocal, get_db()
└── tests/
    ├── conftest.py        # Test fixtures
    ├── test_config.py     # Config tests
    └── test_database.py   # Database tests
```

## License

MIT
