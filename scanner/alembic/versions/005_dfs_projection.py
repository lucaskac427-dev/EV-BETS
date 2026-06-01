"""Add projection + blended fair prob to dfs_opportunities.

Revision ID: 005
Revises: 004
"""

import sqlalchemy as sa

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dfs_opportunities",
        sa.Column("projection_fair_prob", sa.Numeric(7, 6), nullable=True),
    )
    op.add_column(
        "dfs_opportunities",
        sa.Column("blended_fair_prob", sa.Numeric(7, 6), nullable=True),
    )
    op.add_column(
        "dfs_opportunities",
        sa.Column("projection_sample_size", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dfs_opportunities", "projection_sample_size")
    op.drop_column("dfs_opportunities", "blended_fair_prob")
    op.drop_column("dfs_opportunities", "projection_fair_prob")
