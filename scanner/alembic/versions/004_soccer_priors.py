"""Soccer priors — per-player per-match historical stats from StatsBomb open data.

Revision ID: 004
Revises: 003
"""

import sqlalchemy as sa

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "soccer_player_match_stats",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        # Source identity
        sa.Column("source", sa.Text, nullable=False),  # 'statsbomb'
        sa.Column("competition_name", sa.Text, nullable=False),
        sa.Column("season_name", sa.Text, nullable=False),
        sa.Column("match_id", sa.BigInteger, nullable=False),
        sa.Column("match_date", sa.Date, nullable=False),
        sa.Column("home_team", sa.Text, nullable=False),
        sa.Column("away_team", sa.Text, nullable=False),
        # Player
        sa.Column("player_id", sa.BigInteger, nullable=False),
        sa.Column("player_name", sa.Text, nullable=False),
        sa.Column("player_name_slug", sa.Text, nullable=False),  # name-normalized
        sa.Column("team_name", sa.Text, nullable=False),
        sa.Column("position", sa.Text, nullable=True),
        # Minutes
        sa.Column("minutes_played", sa.Integer, nullable=False, server_default="0"),
        # Counting stats
        sa.Column("shots", sa.Integer, nullable=False, server_default="0"),
        sa.Column("shots_on_target", sa.Integer, nullable=False, server_default="0"),
        sa.Column("goals", sa.Integer, nullable=False, server_default="0"),
        sa.Column("assists", sa.Integer, nullable=False, server_default="0"),
        sa.Column("xg", sa.Numeric(6, 4), nullable=True),
        sa.Column("xa", sa.Numeric(6, 4), nullable=True),
        sa.Column("tackles", sa.Integer, nullable=False, server_default="0"),
        sa.Column("fouls_committed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("fouls_won", sa.Integer, nullable=False, server_default="0"),
        sa.Column("passes_attempted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("passes_completed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("dribbles_attempted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("dribbles_completed", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "source", "match_id", "player_id", name="uq_sb_match_player"
        ),
    )
    op.create_index(
        "idx_sb_player_slug",
        "soccer_player_match_stats",
        ["player_name_slug", "match_date"],
    )
    op.create_index(
        "idx_sb_team_match",
        "soccer_player_match_stats",
        ["team_name", "match_date"],
    )


def downgrade() -> None:
    op.drop_table("soccer_player_match_stats")
