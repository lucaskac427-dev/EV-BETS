"""Unified player injury / availability history (NBA + soccer).

Revision ID: 008
Revises: 007
"""

import sqlalchemy as sa

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "injuries",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("sport", sa.Text, nullable=False),           # 'nba' | 'soccer'
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("player_name", sa.Text, nullable=True),
        sa.Column("player_slug", sa.Text, nullable=True),
        sa.Column("team", sa.Text, nullable=True),
        sa.Column("from_date", sa.Date, nullable=True),        # injury onset / went OUT
        sa.Column("end_date", sa.Date, nullable=True),         # returned (null = open/unknown)
        sa.Column("status", sa.Text, nullable=True),           # injured / il / out / returned / questionable
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("days_missed", sa.Integer, nullable=True),
        sa.Column("games_missed", sa.Integer, nullable=True),
        sa.Column("external_player_id", sa.Text, nullable=True),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Fast "was player X unavailable on date D" lookup
    op.create_index("idx_injuries_lookup", "injuries", ["sport", "player_slug", "from_date"])
    op.create_index("idx_injuries_dates", "injuries", ["from_date", "end_date"])


def downgrade() -> None:
    op.drop_table("injuries")
