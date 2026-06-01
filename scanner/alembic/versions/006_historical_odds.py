"""Historical odds snapshots for backtesting.

Revision ID: 006
Revises: 005
"""

import sqlalchemy as sa

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "historical_odds_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text, nullable=False),  # 'odds_api_historical'
        sa.Column("sport_key", sa.Text, nullable=False),
        sa.Column("event_id", sa.Text, nullable=False),
        sa.Column("event_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("home_team", sa.Text, nullable=True),
        sa.Column("away_team", sa.Text, nullable=True),
        sa.Column("snapshot_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("book", sa.Text, nullable=False),
        sa.Column("market_key", sa.Text, nullable=False),
        sa.Column("player_name", sa.Text, nullable=True),
        sa.Column("player_slug", sa.Text, nullable=True),
        sa.Column("line", sa.Numeric(8, 2), nullable=True),
        sa.Column("side", sa.Text, nullable=False),  # 'over' | 'under' | 'yes' | 'no' | home/away/draw
        sa.Column("american_odds", sa.Integer, nullable=False),
        sa.Column("decimal_odds", sa.Numeric(10, 6), nullable=False),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_hist_odds_event",
        "historical_odds_snapshots",
        ["sport_key", "event_id", "snapshot_at"],
    )
    op.create_index(
        "idx_hist_odds_player",
        "historical_odds_snapshots",
        ["player_slug", "market_key", "snapshot_at"],
    )


def downgrade() -> None:
    op.drop_table("historical_odds_snapshots")
