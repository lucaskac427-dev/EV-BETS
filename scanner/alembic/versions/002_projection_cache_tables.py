"""projection cache tables

Revision ID: 002
Revises: 001
Create Date: 2026-05-29

Adds caches populated nightly by nba_stats.ingest, read by the projection engine.
"""

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per-player per-game box score rows (rolling window source).
    op.create_table(
        "player_game_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger, nullable=False),
        sa.Column("player_name", sa.Text, nullable=False),
        sa.Column("team_abbr", sa.Text, nullable=False),
        sa.Column("game_id", sa.Text, nullable=False),
        sa.Column("game_date", sa.Date, nullable=False),
        sa.Column("matchup", sa.Text, nullable=False),       # e.g. "LAL @ BOS"
        sa.Column("minutes", sa.Numeric(5, 2), nullable=True),
        sa.Column("points", sa.Integer, nullable=True),
        sa.Column("rebounds", sa.Integer, nullable=True),
        sa.Column("assists", sa.Integer, nullable=True),
        sa.Column("threes", sa.Integer, nullable=True),
        sa.Column("blocks", sa.Integer, nullable=True),
        sa.Column("steals", sa.Integer, nullable=True),
        sa.Column("ingested_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("player_id", "game_id", name="uq_player_game"),
    )
    op.create_index("idx_game_logs_player_date", "player_game_logs", ["player_id", sa.text("game_date DESC")])

    # Team defensive ratings (opponent adjustment source). One row per team per refresh.
    op.create_table(
        "team_defense_ratings",
        sa.Column("team_abbr", sa.Text, primary_key=True),
        sa.Column("def_rating", sa.Numeric(6, 2), nullable=False),     # points allowed per 100 poss
        sa.Column("pace", sa.Numeric(6, 2), nullable=False),           # possessions per 48
        sa.Column("opp_pts_per_game", sa.Numeric(6, 2), nullable=False),
        sa.Column("refreshed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # League-average reference, single row keyed by season for normalizing adjustments.
    op.create_table(
        "league_averages",
        sa.Column("season", sa.Text, primary_key=True),
        sa.Column("avg_def_rating", sa.Numeric(6, 2), nullable=False),
        sa.Column("avg_pace", sa.Numeric(6, 2), nullable=False),
        sa.Column("refreshed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("league_averages")
    op.drop_table("team_defense_ratings")
    op.drop_table("player_game_logs")
