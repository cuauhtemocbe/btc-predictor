"""add evaluation_slice to backtest_results

Revision ID: c4d8e1f2a9b3
Revises: b7e2d94c1f30
Create Date: 2026-09-30 22:00:00.000000

Labels each walk-forward backtest row as part of the ``validation`` slice (the only
data allowed to inform choices) or the ``test`` slice (headline, out-of-sample
metrics) (#106). Rows stored before this migration stay NULL ("unsplit").
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d8e1f2a9b3"
down_revision: str | Sequence[str] | None = "b7e2d94c1f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "backtest_results",
        sa.Column(
            "evaluation_slice",
            sa.String(length=10),
            nullable=True,
            comment="'validation' (may inform choices) or 'test' (headline, "
            "out-of-sample); NULL for rows stored before the split existed",
        ),
    )
    op.create_check_constraint(
        "valid_evaluation_slice_values",
        "backtest_results",
        "evaluation_slice IN ('validation', 'test')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "valid_evaluation_slice_values", "backtest_results", type_="check"
    )
    op.drop_column("backtest_results", "evaluation_slice")
