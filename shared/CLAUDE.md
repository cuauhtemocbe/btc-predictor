# shared/ — database migrations (Alembic)

Run inside the container; `alembic.ini` lives in `shared/`.

```bash
# Run migrations
docker compose exec api sh -c "cd shared && alembic upgrade head"

# Create new migration
docker compose exec api sh -c "cd shared && alembic revision --autogenerate -m 'description'"

# Downgrade migration
docker compose exec api sh -c "cd shared && alembic downgrade -1"

# View migration history
docker compose exec api sh -c "cd shared && alembic history"
```
