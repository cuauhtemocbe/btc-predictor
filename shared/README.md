# shared

Poetry package that `api-service` and `workers` depend on (`shared = {path = "../shared", develop = true}`): configuration, database access, the return features, the baselines and the helpers every service reuses. It keeps one copy of the database setup and of the code that production and the backtest both run.

| Module | What it holds |
|--------|---------------|
| `shared/config.py` | `Settings` (pydantic-settings): `DATABASE_URL`, `TRAINING_WINDOW_DAYS`, `max_bar_age_hours` |
| `shared/db/` | SQLAlchemy models, engine and `SessionLocal`/`get_db`, CRUD |
| `shared/features.py` | Return features and targets, freshness guards |
| `shared/baselines.py` | always-up, persistence, buy-and-hold and the p-value |
| `shared/binance_vision.py` | Daily history and bars from Binance |
| `shared/utils.py` | `utc_today`, PnL strategies, per-family model metrics |
| `alembic/` | Database migrations ([CLAUDE.md](CLAUDE.md)) |

```python
from shared.db.database import SessionLocal, get_db  # get_db is the FastAPI dependency
```

Tests: `docker compose exec api pytest shared/tests/` (never on the host). Licence: MIT.
