"""only the daily timeframe

Revision ID: e2b8f4a6c1d7
Revises: d5a1c7e93b20
Create Date: 2026-10-06 12:00:00.000000

The weekly worker and the ``1w`` timeframe were removed (#183), and no worker
ever wrote ``1h`` rows (#179). The upgrade deletes the ``1w`` rows (their
predictions first, then the models) and narrows both CHECK constraints to
``('1d')``. The downgrade restores the wide constraints but not the deleted rows.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2b8f4a6c1d7"
down_revision: str | Sequence[str] | None = "d5a1c7e93b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Kept literal on purpose: a migration must not change when the app code does.
MODEL_CHECK = "valid_model_timeframe_values"
PREDICTION_CHECK = "valid_timeframe_values"


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "DELETE FROM predictions WHERE timeframe = '1w'"
        " OR model_id IN (SELECT id FROM models WHERE timeframe = '1w')"
    )
    op.execute("DELETE FROM models WHERE timeframe = '1w'")
    # Rows with '1h' were never written by any worker; remove them too so the
    # narrower constraint can be created.
    op.execute(
        "DELETE FROM predictions WHERE timeframe = '1h'"
        " OR model_id IN (SELECT id FROM models WHERE timeframe = '1h')"
    )
    op.execute("DELETE FROM models WHERE timeframe = '1h'")
    for table, name in (("models", MODEL_CHECK), ("predictions", PREDICTION_CHECK)):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, "timeframe IN ('1d')")


def downgrade() -> None:
    """Downgrade schema (the deleted rows are not restored)."""
    for table, name in (("models", MODEL_CHECK), ("predictions", PREDICTION_CHECK)):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, "timeframe IN ('1h', '1d', '1w')")
