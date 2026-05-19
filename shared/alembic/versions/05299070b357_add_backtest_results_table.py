"""add_backtest_results_table

Revision ID: 05299070b357
Revises: d176f9ffb6cb
Create Date: 2026-05-18 23:01:21.333914

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision: str = '05299070b357'
down_revision: Union[str, Sequence[str], None] = 'd176f9ffb6cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'backtest_results',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('backtest_run_id', UUID(as_uuid=True), nullable=False),
        sa.Column('predicted_for', sa.Date, nullable=False),
        sa.Column('predicted_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('price_at_prediction', sa.Numeric(15, 2), nullable=False),
        sa.Column('predicted_price', sa.Numeric(15, 2), nullable=False),
        sa.Column('actual_price', sa.Numeric(15, 2), nullable=False),
        sa.Column('pnl_simple', sa.Numeric(15, 2), nullable=True),
        sa.Column('pnl_long_short', sa.Numeric(15, 2), nullable=True),
        sa.Column('pnl_threshold', sa.Numeric(15, 2), nullable=True),
        sa.Column('pnl_realistic', sa.Numeric(15, 2), nullable=True),
        sa.Column('model_params', JSONB, nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )

    # Create indexes for query performance
    op.create_index('idx_backtest_run_id', 'backtest_results', ['backtest_run_id'])
    op.create_index('idx_predicted_for', 'backtest_results', ['predicted_for'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_predicted_for', 'backtest_results')
    op.drop_index('idx_backtest_run_id', 'backtest_results')
    op.drop_table('backtest_results')
