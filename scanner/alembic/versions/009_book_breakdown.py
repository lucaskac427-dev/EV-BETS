"""Per-book quote breakdown on each DFS opportunity (for the dashboard display).

Revision ID: 009
Revises: 008
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # [{book, over_odds, under_odds, fair_over}, ...] for the matched market
    op.add_column("dfs_opportunities", sa.Column("book_breakdown", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("dfs_opportunities", "book_breakdown")
