"""store prices per symbol

Revision ID: b7e2d94c1f30
Revises: a3f7c9e1d2b4
Create Date: 2026-09-26 21:00:00.000000

Renames btc_prices to prices and adds a ``symbol`` column so one pipeline can
serve several assets (BTCUSDT, PAXGUSDT, ...). ``models`` gets ``symbol`` too and
it joins its unique keys; ``predictions`` gets its asset through ``model_id``.

The ``source = 'coingecko'`` rows are deleted: their closes are not comparable
with Binance daily bars and the history is reloaded from Binance (#101).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e2d94c1f30"
down_revision: str | Sequence[str] | None = "a3f7c9e1d2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every row that exists before this migration belongs to the BTC pipeline.
DEFAULT_SYMBOL = "BTCUSDT"


def upgrade() -> None:
    """Upgrade schema."""
    # Step 1: drop the CoinGecko history (decision 1 of #100).
    op.execute("DELETE FROM btc_prices WHERE source = 'coingecko'")

    # Step 2: btc_prices -> prices, renaming the objects Postgres named after it.
    op.rename_table("btc_prices", "prices")
    op.execute("ALTER SEQUENCE btc_prices_id_seq RENAME TO prices_id_seq")
    op.execute("ALTER INDEX btc_prices_pkey RENAME TO prices_pkey")
    op.alter_column(
        "prices",
        "volume",
        existing_type=sa.NUMERIC(precision=18, scale=8),
        existing_nullable=False,
        comment="Trading volume in the base asset",
    )

    # Step 3: symbol column. Existing rows are BTC; new rows must say which
    # asset they belong to (or take the ORM default), so the server default goes.
    op.add_column(
        "prices",
        sa.Column(
            "symbol",
            sa.String(length=20),
            nullable=False,
            server_default=DEFAULT_SYMBOL,
            comment="Asset symbol (e.g., 'BTCUSDT', 'PAXGUSDT')",
        ),
    )
    op.alter_column("prices", "symbol", server_default=None)

    # Step 4: a timestamp is unique per symbol, not globally.
    op.drop_index("ix_btc_prices_timestamp", table_name="prices")
    op.create_index("ix_prices_timestamp", "prices", ["timestamp"], unique=False)
    op.create_unique_constraint(
        "unique_price_per_symbol", "prices", ["symbol", "timestamp"]
    )

    # Step 5: models get the symbol and it joins their unique keys, so the same
    # model name/version can exist once per asset.
    op.add_column(
        "models",
        sa.Column(
            "symbol",
            sa.String(length=20),
            nullable=False,
            server_default=DEFAULT_SYMBOL,
            comment="Asset this model predicts (e.g., 'BTCUSDT', 'PAXGUSDT')",
        ),
    )
    op.alter_column("models", "symbol", server_default=None)

    op.drop_constraint("unique_model_version", "models", type_="unique")
    op.create_unique_constraint(
        "unique_model_version", "models", ["symbol", "name", "version"]
    )

    op.drop_index(
        "ix_models_one_active_version_per_name_timeframe", table_name="models"
    )
    op.create_index(
        "ix_models_one_active_version_per_name_timeframe",
        "models",
        ["symbol", "name", "timeframe"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    """Downgrade schema.

    The old schema cannot hold more than one asset, so rows of any symbol other
    than BTCUSDT are deleted (their predictions go with them through the
    ``model_id`` cascade). The CoinGecko rows deleted by ``upgrade`` are not
    restored.
    """
    op.execute(f"DELETE FROM models WHERE symbol <> '{DEFAULT_SYMBOL}'")
    op.execute(f"DELETE FROM prices WHERE symbol <> '{DEFAULT_SYMBOL}'")

    op.drop_index(
        "ix_models_one_active_version_per_name_timeframe", table_name="models"
    )
    op.create_index(
        "ix_models_one_active_version_per_name_timeframe",
        "models",
        ["name", "timeframe"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
    op.drop_constraint("unique_model_version", "models", type_="unique")
    op.create_unique_constraint("unique_model_version", "models", ["name", "version"])
    op.drop_column("models", "symbol")

    op.drop_constraint("unique_price_per_symbol", "prices", type_="unique")
    op.drop_index("ix_prices_timestamp", table_name="prices")
    op.create_index("ix_btc_prices_timestamp", "prices", ["timestamp"], unique=True)
    op.drop_column("prices", "symbol")
    op.alter_column(
        "prices",
        "volume",
        existing_type=sa.NUMERIC(precision=18, scale=8),
        existing_nullable=False,
        comment="Trading volume in BTC",
    )
    op.execute("ALTER INDEX prices_pkey RENAME TO btc_prices_pkey")
    op.execute("ALTER SEQUENCE prices_id_seq RENAME TO btc_prices_id_seq")
    op.rename_table("prices", "btc_prices")
