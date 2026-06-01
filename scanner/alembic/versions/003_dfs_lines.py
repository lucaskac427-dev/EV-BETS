"""DFS pick'em lines (PrizePicks, DK Pick6, etc) + their evaluated edges.

Revision ID: 003_dfs_lines
Revises: 002_projection_cache_tables
"""

import sqlalchemy as sa

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dfs_lines",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column("sport", sa.Text, nullable=False),
        sa.Column("player_name", sa.Text, nullable=False),
        sa.Column("team", sa.Text, nullable=True),
        sa.Column("stat_type", sa.Text, nullable=False),
        sa.Column("line", sa.Numeric(8, 2), nullable=False),
        sa.Column("odds_type", sa.Text, nullable=False),
        sa.Column("game_starts_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("source", "external_id", name="uq_dfs_lines_source_ext"),
    )
    op.create_index(
        "idx_dfs_lines_active_game",
        "dfs_lines",
        ["is_active", "game_starts_at"],
    )

    op.create_table(
        "dfs_opportunities",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "dfs_line_id",
            sa.BigInteger,
            sa.ForeignKey("dfs_lines.id"),
            nullable=False,
        ),
        sa.Column("pick_side", sa.Text, nullable=False),  # 'over' | 'under'
        sa.Column("consensus_fair_prob", sa.Numeric(7, 6), nullable=False),
        sa.Column("breakeven_per_leg", sa.Numeric(7, 6), nullable=False),
        sa.Column("edge_pct", sa.Numeric(7, 4), nullable=False),
        sa.Column("num_sharp_books", sa.Integer, nullable=False),
        sa.Column(
            "scan_tick_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_dfs_opps_line_time",
        "dfs_opportunities",
        ["dfs_line_id", sa.text("scan_tick_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("dfs_opportunities")
    op.drop_table("dfs_lines")
