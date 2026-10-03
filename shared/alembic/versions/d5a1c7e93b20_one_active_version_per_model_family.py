"""one active version per model family

Revision ID: d5a1c7e93b20
Revises: c4d8e1f2a9b3
Create Date: 2026-10-03 12:00:00.000000

The trainers name each version "<family>_v<N>" ("linear_v1", "linear_v2"), so the
unique index on (symbol, name, timeframe) never saw two versions of one model as
the same model and ``activate_model`` left the old ones active (#169). The index
now keys on the name without its ``_v<N>`` suffix.

Rows saved before the fix can have several active versions of one family. Before
the index is created, only the newest of each (symbol, family, timeframe) stays
active (latest ``trained_at``, ties broken by the highest ``id``).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5a1c7e93b20"
down_revision: str | Sequence[str] | None = "c4d8e1f2a9b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_models_one_active_version_per_name_timeframe"
# Kept literal on purpose: a migration must not change when the app code does.
FAMILY_SQL = "regexp_replace(name, '_v[0-9]+$', '')"


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        f"""
        UPDATE models SET is_active = false
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY symbol, {FAMILY_SQL}, timeframe
                    ORDER BY trained_at DESC, id DESC
                ) AS rank
                FROM models
                WHERE is_active = true
            ) AS active_models
            WHERE rank > 1
        )
        """
    )
    op.drop_index(INDEX_NAME, table_name="models")
    op.create_index(
        INDEX_NAME,
        "models",
        ["symbol", sa.text(FAMILY_SQL), "timeframe"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    """Downgrade schema.

    The old index is looser (it keys on the full name), so it holds any data
    the new one accepted. Models deactivated by ``upgrade`` stay inactive.
    """
    op.drop_index(INDEX_NAME, table_name="models")
    op.create_index(
        INDEX_NAME,
        "models",
        ["symbol", "name", "timeframe"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
