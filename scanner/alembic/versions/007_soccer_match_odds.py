"""football-data.co.uk match results + odds, all leagues since 1993.

Revision ID: 007
Revises: 006
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "soccer_match_odds",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text, nullable=False, server_default="football-data"),
        sa.Column("country", sa.Text, nullable=True),
        sa.Column("league_code", sa.Text, nullable=False),
        sa.Column("league_name", sa.Text, nullable=True),
        sa.Column("season", sa.Text, nullable=False),
        sa.Column("match_date", sa.Date, nullable=True),
        sa.Column("home_team", sa.Text, nullable=False),
        sa.Column("away_team", sa.Text, nullable=False),
        # Results
        sa.Column("fthg", sa.Integer, nullable=True),  # full-time home goals
        sa.Column("ftag", sa.Integer, nullable=True),
        sa.Column("ftr", sa.Text, nullable=True),       # H/D/A
        sa.Column("hthg", sa.Integer, nullable=True),
        sa.Column("htag", sa.Integer, nullable=True),
        # 1X2 odds — normalized "best available" + Pinnacle where present
        sa.Column("odds_home", sa.Numeric(8, 3), nullable=True),
        sa.Column("odds_draw", sa.Numeric(8, 3), nullable=True),
        sa.Column("odds_away", sa.Numeric(8, 3), nullable=True),
        sa.Column("pinnacle_home", sa.Numeric(8, 3), nullable=True),
        sa.Column("pinnacle_draw", sa.Numeric(8, 3), nullable=True),
        sa.Column("pinnacle_away", sa.Numeric(8, 3), nullable=True),
        # Totals
        sa.Column("over25", sa.Numeric(8, 3), nullable=True),
        sa.Column("under25", sa.Numeric(8, 3), nullable=True),
        # Asian handicap
        sa.Column("ah_line", sa.Numeric(5, 2), nullable=True),
        sa.Column("ah_home", sa.Numeric(8, 3), nullable=True),
        sa.Column("ah_away", sa.Numeric(8, 3), nullable=True),
        # Everything else verbatim
        sa.Column("raw", JSONB, nullable=True),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "league_code", "season", "match_date", "home_team", "away_team",
            name="uq_soccer_match",
        ),
    )
    op.create_index("idx_soccer_match_date", "soccer_match_odds", ["match_date"])
    op.create_index(
        "idx_soccer_match_league_season", "soccer_match_odds", ["league_code", "season"]
    )
    op.create_index(
        "idx_soccer_match_teams", "soccer_match_odds", ["home_team", "away_team"]
    )


def downgrade() -> None:
    op.drop_table("soccer_match_odds")
