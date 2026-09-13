"""add timeframe column to models

Revision ID: a3f7c9e1d2b4
Revises: c0a41e870a5e
Create Date: 2026-08-10 22:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f7c9e1d2b4"
down_revision: str | Sequence[str] | None = "c0a41e870a5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Step 1: Add timeframe column with default '1d' for existing rows
    # (every model trained so far was trained for the 1-day horizon).
    op.add_column(
        "models",
        sa.Column(
            "timeframe",
            sa.String(length=2),
            nullable=False,
            server_default="1d",
            comment=(
                "Prediction horizon this model was trained for: '1h' "
                "(hourly), '1d' (daily), '1w' (weekly). At most one model "
                "per timeframe can be active at a time (enforced by "
                "ix_models_one_active_per_timeframe)."
            ),
        ),
    )

    # Step 2: Remove server default (new rows must provide timeframe explicitly)
    op.alter_column("models", "timeframe", server_default=None)

    # Step 3: Add CHECK constraint for valid timeframe values
    op.create_check_constraint(
        "valid_model_timeframe_values", "models", "timeframe IN ('1h', '1d', '1w')"
    )

    # Step 4: Partial unique index -- at most one active version per
    # (name, timeframe). This is what actually makes activation atomic at
    # the database level: a concurrent attempt to activate a second version
    # of the SAME model name/timeframe fails with an IntegrityError instead
    # of silently leaving two rows with is_active=true. Different names
    # (e.g. "linear_v1" and "xgboost_v1") can still be active at the same
    # time within the same timeframe -- that's what powers multi-model
    # prediction mode (US-025), and this index is intentionally scoped so
    # it doesn't touch that.
    op.create_index(
        "ix_models_one_active_version_per_name_timeframe",
        "models",
        ["name", "timeframe"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_models_one_active_version_per_name_timeframe", table_name="models"
    )
    op.drop_constraint("valid_model_timeframe_values", "models", type_="check")
    op.drop_column("models", "timeframe")
