---
title: Shared Package with Database Configuration
status: completed
created: 2026-05-16
updated: 2026-05-16
issue: #2
---

# Shared Package with Database Configuration

## Objective

Create a centralized `shared` package that provides database configuration and SQLAlchemy engine setup for all services (api, fetch_price, daily) to avoid duplicating DB connection logic across the codebase.

## Context

The btc-predictor project follows a multi-service architecture where three services (api, fetch_price, daily) need to connect to the same PostgreSQL database. Without a shared package, each service would duplicate:
- Environment variable configuration (DATABASE_URL)
- SQLAlchemy engine initialization
- Session factory setup
- Connection pooling configuration

This leads to:
- Code duplication and maintenance burden
- Inconsistent connection settings across services
- Difficulty in updating DB configuration globally

The shared package will be a Poetry package that all other services depend on, providing a single source of truth for database configuration.

## Requirements

### Functional Requirements

- [ ] Load DATABASE_URL from environment variables using pydantic-settings
- [ ] Create SQLAlchemy engine with connection pooling
- [ ] Provide reusable `SessionLocal` session factory
- [ ] Provide `get_db()` dependency for FastAPI dependency injection
- [ ] Validate that DATABASE_URL is present and non-empty
- [ ] Support PostgreSQL connection strings

### Non-Functional Requirements

- [ ] **Testability:** All components must be unit-testable with mocked environment
- [ ] **Security:** DATABASE_URL with credentials must not be logged in plaintext
- [ ] **Reliability:** Connection failures must provide clear error messages
- [ ] **Performance:** Use connection pooling (SQLAlchemy default: pool_size=5)

## Architecture

### Components

```
shared/
├── pyproject.toml              # Poetry package definition
├── btc_shared/
│   ├── __init__.py            # Package exports
│   ├── config.py              # Settings (pydantic-settings)
│   └── db/
│       ├── __init__.py        # DB package exports
│       └── database.py        # Engine, SessionLocal, get_db()
└── tests/
    ├── conftest.py            # Test fixtures
    ├── test_config.py         # Config tests
    └── test_database.py       # Database tests
```

### Data Model

**Settings (config.py):**
```python
class Settings(BaseSettings):
    database_url: str  # Required, e.g., "postgresql://user:pass@host/db"
    
    class Config:
        env_file = ".env"
```

**Database (database.py):**
```python
engine = create_engine(settings.database_url, ...)
SessionLocal = sessionmaker(engine)

def get_db():
    """FastAPI dependency for DB sessions"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### External Dependencies

- **pydantic-settings** (^2.0): Environment variable management
- **SQLAlchemy** (^2.0): Database ORM and engine
- **psycopg2-binary** (^2.9): PostgreSQL driver

## User Stories

Linked to **GitHub Issue #2**: US-001

**As** a backend developer  
**I want** a shared package with database configuration and SQLAlchemy engine  
**In order to** avoid duplicating DB connection logic across services

## Testing Strategy

### Unit Tests

**test_config.py:**
- Test Settings loads DATABASE_URL from environment
- Test Settings raises ValidationError when DATABASE_URL is missing
- Test Settings raises ValidationError when DATABASE_URL is empty string

**test_database.py:**
- Test engine creation with valid DATABASE_URL
- Test SessionLocal creates usable sessions
- Test get_db() yields session and closes it after use
- Test connection failure with invalid DATABASE_URL provides clear error

### Integration Tests

- Test actual connection to test PostgreSQL database
- Test session commit/rollback behavior
- Test connection pool behavior under concurrent access

### Coverage Target

**Minimum: 90% coverage** for shared package (it's foundational infrastructure)

## Boundaries & Constraints

### In Scope
- Configuration management (DATABASE_URL)
- SQLAlchemy engine and session setup
- FastAPI dependency injection helper
- Unit tests with mocked environment

### Out of Scope
- Database models (will be added in US-002)
- Alembic migrations (will be added in US-002)
- CRUD operations (will be added later)
- Multiple database support (PostgreSQL only)
- Connection retry logic (SQLAlchemy handles this)

### Technical Constraints
- **Python**: 3.13
- **SQLAlchemy**: 2.0 (modern async-compatible API)
- **PostgreSQL**: 14+ (deployed on Railway)
- **Poetry workspace**: Shared package must be importable by sibling packages

## Success Criteria

- [ ] `shared/btc_shared/config.py` exports `Settings` with `database_url`
- [ ] `shared/btc_shared/db/database.py` exports `engine`, `SessionLocal`, `get_db()`
- [ ] All 4 Gherkin scenarios have passing automated tests
- [ ] Tests achieve 90%+ code coverage
- [ ] Package can be imported by sibling packages: `from btc_shared.config import Settings`
- [ ] No credentials are logged in plaintext (verified by test)
- [ ] Documentation in README or docstrings explains usage

## Implementation Plan

See: `specs/shared-package-database-plan.md` (to be created in Phase 2)
