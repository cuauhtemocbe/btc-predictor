# Implementation Plan: Shared Package with Database Configuration

**Spec**: [shared-package-database.md](./shared-package-database.md)  
**Created**: 2026-05-16  
**Status**: draft

---

## Components

### 1. Poetry Package Setup
- **Purpose**: Create `shared/` as standalone Poetry package
- **Files**: 
  - `shared/pyproject.toml`
  - `shared/btc_shared/__init__.py`
- **Effort**: XS (15 min)
- **Dependencies**: None

### 2. Configuration Module
- **Purpose**: Load and validate DATABASE_URL using pydantic-settings
- **Files**:
  - `shared/btc_shared/config.py`
- **Effort**: S (30 min)
- **Dependencies**: Poetry package must exist

### 3. Database Module
- **Purpose**: SQLAlchemy engine, SessionLocal, get_db() dependency
- **Files**:
  - `shared/btc_shared/db/__init__.py`
  - `shared/btc_shared/db/database.py`
- **Effort**: S (45 min)
- **Dependencies**: Configuration module

### 4. Test Suite
- **Purpose**: Unit tests for all Gherkin scenarios
- **Files**:
  - `shared/tests/conftest.py`
  - `shared/tests/test_config.py`
  - `shared/tests/test_database.py`
- **Effort**: M (1.5 hours)
- **Dependencies**: All modules above

---

## Build Order

```
1. Poetry Package Setup (foundation)
   ↓
2. Configuration Module (depends on package)
   ↓
3. Database Module (depends on config)
   ↓
4. Test Suite (verifies everything)
```

**Rationale**: Bottom-up approach. Can't configure DB without settings, can't test without implementation.

---

## Dependencies

### External Python Packages

Add to `shared/pyproject.toml`:
```toml
[tool.poetry.dependencies]
python = "^3.13"
pydantic-settings = "^2.0"
sqlalchemy = "^2.0"
psycopg2-binary = "^2.9"

[tool.poetry.group.dev.dependencies]
pytest = "^7.4"
pytest-cov = "^4.1"
pytest-mock = "^3.12"
```

### System Dependencies

- PostgreSQL 14+ (running in Docker via `docker compose up`)

### Internal Dependencies

None yet (this is the first shared component).

---

## Risks & Assumptions

### Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Poetry workspace not configured** | High - other services can't import shared package | Verify `pyproject.toml` at root has workspace configuration |
| **SQLAlchemy 2.0 API changes** | Medium - syntax differs from 1.4 | Use SQLAlchemy 2.0 docs, avoid deprecated patterns |
| **DATABASE_URL missing in test environment** | Low - tests fail | Mock environment in tests, use `monkeypatch` |

### Assumptions

- ✅ PostgreSQL container is running (`docker compose up -d`)
- ✅ Root `pyproject.toml` exists (created in Iteración 0)
- ✅ Python 3.13 available in Docker container
- ⚠️ Poetry workspace configured correctly (needs verification)

---

## Milestones

- [ ] **M1: Package Structure Created** — `shared/pyproject.toml` exists, `poetry install` works
- [ ] **M2: Configuration Works** — Can import `Settings`, validates DATABASE_URL
- [ ] **M3: Database Connects** — Engine connects to PostgreSQL, sessions work
- [ ] **M4: Tests Pass** — All 4 Gherkin scenarios covered, 90%+ coverage

---

## Tasks

### Foundation (Build First)

#### Task 1: Create Poetry Package Structure
- **Description**: Initialize `shared/` directory as Poetry package
- **Acceptance**: 
  - `shared/pyproject.toml` exists with correct metadata
  - `shared/btc_shared/__init__.py` exists
  - Can run `poetry install` from `shared/` directory without errors
- **Files**:
  - `shared/pyproject.toml` (create)
  - `shared/btc_shared/__init__.py` (create)
  - `shared/README.md` (create - usage docs)
- **Tests**: None (setup task)
- **Effort**: XS

#### Task 2: Add Dependencies to pyproject.toml
- **Description**: Add pydantic-settings, SQLAlchemy, psycopg2-binary to dependencies
- **Acceptance**:
  - Dependencies listed in `[tool.poetry.dependencies]`
  - Dev dependencies (pytest, etc.) in `[tool.poetry.group.dev.dependencies]`
  - `poetry lock` completes successfully
- **Files**:
  - `shared/pyproject.toml` (edit)
  - `shared/poetry.lock` (generated)
- **Tests**: None (setup task)
- **Effort**: XS

---

### Core Implementation (Build Second)

#### Task 3: Implement Configuration Module
- **Description**: Create `config.py` with Settings class using pydantic-settings
- **Acceptance**:
  - `Settings` class loads `database_url` from environment
  - Raises `ValidationError` if `DATABASE_URL` not set
  - Raises `ValidationError` if `DATABASE_URL` is empty string
  - Settings can be instantiated: `settings = Settings()`
- **Files**:
  - `shared/btc_shared/config.py` (create)
- **Tests**: `test_config.py` must cover:
  - Scenario: "Load DATABASE_URL from environment"
  - Scenario: "Missing DATABASE_URL raises error"
  - Edge case: Empty string DATABASE_URL
- **Effort**: S

#### Task 4: Implement Database Module
- **Description**: Create `database.py` with engine, SessionLocal, get_db()
- **Acceptance**:
  - `engine` created using `settings.database_url`
  - `SessionLocal` session factory configured
  - `get_db()` yields session and closes it after use
  - Connection pooling enabled (default SQLAlchemy settings)
- **Files**:
  - `shared/btc_shared/db/__init__.py` (create)
  - `shared/btc_shared/db/database.py` (create)
- **Tests**: `test_database.py` must cover:
  - Scenario: "Create SQLAlchemy engine"
  - Scenario: "Get database session"
  - Edge case: Invalid DATABASE_URL format
- **Effort**: S

---

### Testing (Build Third)

#### Task 5: Write Configuration Tests
- **Description**: Unit tests for config.py covering all Gherkin scenarios
- **Acceptance**:
  - Test passes when DATABASE_URL is set correctly
  - Test passes when DATABASE_URL is missing (expects ValidationError)
  - Test passes when DATABASE_URL is empty string (expects ValidationError)
  - Coverage for config.py >= 95%
- **Files**:
  - `shared/tests/conftest.py` (create - pytest fixtures)
  - `shared/tests/test_config.py` (create)
- **Tests**: This IS the test task
- **Effort**: S

#### Task 6: Write Database Tests
- **Description**: Unit tests for database.py covering all Gherkin scenarios
- **Acceptance**:
  - Test engine creation with mocked DATABASE_URL
  - Test SessionLocal creates sessions
  - Test get_db() yields and closes session (using mock)
  - Test connection failure provides clear error message
  - Coverage for database.py >= 90%
- **Files**:
  - `shared/tests/test_database.py` (create)
- **Tests**: This IS the test task
- **Effort**: M

#### Task 7: Integration Test with Real Database
- **Description**: Test actual connection to PostgreSQL container
- **Acceptance**:
  - Test connects to `postgres` container from Docker Compose
  - Test creates session and executes simple query (SELECT 1)
  - Test verifies connection pool works
  - Test runs inside `api` container via `docker compose exec api pytest`
- **Files**:
  - `shared/tests/test_integration.py` (create)
- **Tests**: This IS the test task
- **Effort**: S

---

### Documentation (Build Last)

#### Task 8: Update Package Documentation
- **Description**: Document usage in README and docstrings
- **Acceptance**:
  - `shared/README.md` explains how to import and use Settings
  - `shared/README.md` shows example of get_db() with FastAPI
  - Docstrings in config.py and database.py explain parameters
  - No credentials shown in examples (use placeholders)
- **Files**:
  - `shared/README.md` (create)
  - `shared/btc_shared/config.py` (add docstrings)
  - `shared/btc_shared/db/database.py` (add docstrings)
- **Tests**: None (documentation task)
- **Effort**: XS

---

## Effort Estimate

**Total Estimated Time**: 4-5 hours (fits within 1-day sprint)

| Phase | Tasks | Effort |
|-------|-------|--------|
| Foundation | Task 1-2 | 30 min |
| Core Implementation | Task 3-4 | 1.25 hours |
| Testing | Task 5-7 | 2.5 hours |
| Documentation | Task 8 | 15 min |

**Buffer**: +30 min for debugging, dependency issues, environment setup

---

## Pre-Implementation Checklist

Before starting Task 1, verify:

- [ ] PostgreSQL container is running: `docker compose ps postgres`
- [ ] Can access container shell: `docker compose exec api bash`
- [ ] Root workspace has Poetry configured (check root `pyproject.toml`)
- [ ] Git branch created: `git checkout -b feat/us-001-shared-package`

---

## Post-Implementation Checklist

After Task 8, verify:

- [ ] All tests pass: `docker compose exec api pytest shared/tests/ -v`
- [ ] Coverage meets target: `docker compose exec api pytest shared/tests/ --cov=btc_shared --cov-report=term-missing`
- [ ] Lint passes: `docker compose exec api ruff check shared/`
- [ ] Format verified: `docker compose exec api ruff format --check shared/`
- [ ] Can import from other packages: `from btc_shared.config import Settings`
- [ ] Commit with good message (use `/commit-writer`)
- [ ] Ready for PR (don't push yet - wait for user)

---

## Notes

### Poetry Workspace Configuration

The root `pyproject.toml` should have:
```toml
[tool.poetry]
packages = [
    { include = "shared" },
    { include = "api" },
    { include = "fetch_price", from = "jobs" },
    { include = "daily", from = "jobs" }
]
```

Then other packages can depend on shared with:
```toml
[tool.poetry.dependencies]
btc-shared = {path = "../shared", develop = true}
```

### SQLAlchemy 2.0 Patterns

Use modern API (not legacy 1.4):
```python
# ✅ Modern (2.0)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

engine = create_engine(url, echo=False)
SessionLocal = sessionmaker(bind=engine)

# ❌ Legacy (1.4)
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
```

### Testing Strategy

- **Unit tests**: Mock environment variables with `monkeypatch`
- **Integration tests**: Use real PostgreSQL container, clean up after tests
- **Coverage target**: 90%+ for infrastructure code (this is foundational)
