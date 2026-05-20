"""add model_id to unique constraint for multi-model predictions

Revision ID: c0a41e870a5e
Revises: fda7ff646d39
Create Date: 2026-05-19 19:24:40.505899

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0a41e870a5e"
down_revision: str | Sequence[str] | None = "fda7ff646d39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - allow multiple predictions per date from different models."""
    # Only modify constraints if predictions table exists
    # (handles case where we're running migrations from scratch)
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "predictions" in inspector.get_table_names():
        # Drop old constraint (predicted_for, timeframe)
        op.drop_constraint(
            "unique_prediction_per_timeframe", "predictions", type_="unique"
        )

        # Add new constraint (predicted_for, timeframe, model_id)
        op.create_unique_constraint(
            "unique_prediction_per_model_timeframe",
            "predictions",
            ["predicted_for", "timeframe", "model_id"],
        )


def downgrade() -> None:
    """Downgrade schema - revert to single prediction per date."""
    # Only modify constraints if predictions table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "predictions" in inspector.get_table_names():
        # Drop new constraint
        op.drop_constraint(
            "unique_prediction_per_model_timeframe", "predictions", type_="unique"
        )

        # Restore old constraint
        op.create_unique_constraint(
            "unique_prediction_per_timeframe",
            "predictions",
            ["predicted_for", "timeframe"],
        )
