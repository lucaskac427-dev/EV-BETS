"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-29

Implements the 10 tables defined in
docs/superpowers/specs/2026-05-29-kalshi-ev-scanner-design.md Section 6.
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "markets",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("sport", sa.Text, nullable=False),
        sa.Column("kalshi_ticker", sa.Text, nullable=False, unique=True),
        sa.Column("market_type", sa.Text, nullable=False),
        sa.Column("player_name", sa.Text, nullable=True),
        sa.Column("stat_type", sa.Text, nullable=True),
        sa.Column("line", sa.Numeric(6, 2), nullable=True),
        sa.Column("game_id", sa.Text, nullable=False),
        sa.Column("game_starts_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_markets_game", "markets", ["game_id", "is_active"])
    op.create_index(
        "idx_markets_starts",
        "markets",
        ["game_starts_at"],
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "odds_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.BigInteger, sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("book", sa.Text, nullable=False),
        sa.Column("side", sa.Text, nullable=False),
        sa.Column("decimal_odds", sa.Numeric(10, 4), nullable=False),
        sa.Column("implied_prob", sa.Numeric(7, 6), nullable=False),
        sa.Column("fetched_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_snapshots_market_time", "odds_snapshots", ["market_id", sa.text("fetched_at DESC")])
    op.create_index("idx_snapshots_book_time", "odds_snapshots", ["book", sa.text("fetched_at DESC")])

    op.create_table(
        "projections",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.BigInteger, sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("mean", sa.Numeric(8, 3), nullable=False),
        sa.Column("std_dev", sa.Numeric(8, 3), nullable=False),
        sa.Column("distribution", sa.Text, nullable=False),
        sa.Column("fair_prob_over", sa.Numeric(7, 6), nullable=False),
        sa.Column("model_version", sa.Text, nullable=False),
        sa.Column("news_adjusted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("computed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_projections_market_time", "projections", ["market_id", sa.text("computed_at DESC")])

    op.create_table(
        "news_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("player_name", sa.Text, nullable=False),
        sa.Column("team", sa.Text, nullable=True),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("posted_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
    )
    op.create_index("idx_news_player_recent", "news_events", ["player_name", sa.text("posted_at DESC")])

    op.create_table(
        "opportunities",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("market_id", sa.BigInteger, sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("kalshi_side", sa.Text, nullable=False),
        sa.Column("kalshi_decimal_odds", sa.Numeric(10, 4), nullable=False),
        sa.Column("consensus_fair_prob", sa.Numeric(7, 6), nullable=False),
        sa.Column("projection_fair_prob", sa.Numeric(7, 6), nullable=True),
        sa.Column("blended_fair_prob", sa.Numeric(7, 6), nullable=False),
        sa.Column("ev_pct", sa.Numeric(6, 4), nullable=False),
        sa.Column("kelly_fraction", sa.Numeric(6, 4), nullable=True),
        sa.Column("num_sharp_books", sa.SmallInteger, nullable=False),
        sa.Column("suspicious", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("scan_tick_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_opps_recent", "opportunities", [sa.text("scan_tick_at DESC")])
    op.create_index("idx_opps_market_recent", "opportunities", ["market_id", sa.text("scan_tick_at DESC")])

    op.create_table(
        "bets",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("opportunity_id", sa.BigInteger, sa.ForeignKey("opportunities.id"), nullable=True),
        sa.Column("market_id", sa.BigInteger, sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("side", sa.Text, nullable=False),
        sa.Column("stake_cents", sa.Integer, nullable=False),
        sa.Column("decimal_odds", sa.Numeric(10, 4), nullable=False),
        sa.Column("ev_pct_at_bet", sa.Numeric(6, 4), nullable=False),
        sa.Column("placed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("notes", sa.Text, nullable=True),
    )

    op.create_table(
        "bet_results",
        sa.Column("bet_id", sa.BigInteger, sa.ForeignKey("bets.id"), primary_key=True),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("payout_cents", sa.Integer, nullable=False),
        sa.Column("actual_value", sa.Numeric(8, 3), nullable=True),
        sa.Column("settled_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "market_outcomes",
        sa.Column("market_id", sa.BigInteger, sa.ForeignKey("markets.id"), primary_key=True),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("actual_value", sa.Numeric(8, 3), nullable=True),
        sa.Column("settled_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "bankroll_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("delta_cents", sa.Integer, nullable=False),
        sa.Column("balance_cents", sa.Integer, nullable=False),
        sa.Column("related_bet_id", sa.BigInteger, sa.ForeignKey("bets.id"), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_bankroll_user_time", "bankroll_events", ["user_id", sa.text("created_at DESC")])

    op.create_table(
        "scan_telemetry",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tick_id", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("status_detail", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_telemetry_source_time", "scan_telemetry", ["source", sa.text("created_at DESC")])
    op.create_index("idx_telemetry_tick", "scan_telemetry", ["tick_id"])


def downgrade() -> None:
    op.drop_table("scan_telemetry")
    op.drop_table("bankroll_events")
    op.drop_table("market_outcomes")
    op.drop_table("bet_results")
    op.drop_table("bets")
    op.drop_table("opportunities")
    op.drop_table("news_events")
    op.drop_table("projections")
    op.drop_table("odds_snapshots")
    op.drop_table("markets")
