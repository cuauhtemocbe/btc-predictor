"""Helpers that keep the test suite on its own databases (issue #110)."""

from sqlalchemy import create_engine, text


def database_name_for_tests(base_name: str, worker_id: str | None) -> str:
    """Name of the database the tests use, so they never touch the dev one.

    Serial runs use ``<base>_test``; each pytest-xdist worker gets its own
    ``<base>_test_<worker>`` (e.g. ``btcpredictor_test_gw0``) so workers never
    share a schema.
    """
    # Idempotent: xdist workers inherit the controller's already-suffixed URL
    name = f"{base_name.removesuffix('_test')}_test"
    return f"{name}_{worker_id}" if worker_id else name


def ensure_database(url) -> None:
    """Create the database behind ``url`` if it does not exist yet."""
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            ).scalar()
            if not exists:
                # Identifiers cannot be bound parameters; the name is built
                # from our own settings, never from user input.
                connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin.dispose()
