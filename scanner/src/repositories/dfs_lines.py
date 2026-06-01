"""DFS lines repository — CRUD for dfs_lines + dfs_opportunities."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import asyncpg


@dataclass(frozen=True, slots=True)
class DfsLine:
    id: int
    source: str
    external_id: str
    sport: str
    player_name: str
    team: str | None
    stat_type: str
    line: float
    odds_type: str
    game_starts_at: datetime
    is_active: bool


async def upsert_dfs_line(
    pool: asyncpg.Pool,
    *,
    source: str,
    external_id: str,
    sport: str,
    player_name: str,
    team: str | None,
    stat_type: str,
    line: float,
    odds_type: str,
    game_starts_at: datetime,
) -> DfsLine:
    row = await pool.fetchrow(
        """
        INSERT INTO dfs_lines (source, external_id, sport, player_name, team,
                               stat_type, line, odds_type, game_starts_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (source, external_id) DO UPDATE SET
            line = EXCLUDED.line,
            odds_type = EXCLUDED.odds_type,
            game_starts_at = EXCLUDED.game_starts_at,
            is_active = true,
            updated_at = NOW()
        RETURNING id, source, external_id, sport, player_name, team,
                  stat_type, line, odds_type, game_starts_at, is_active
        """,
        source, external_id, sport, player_name, team,
        stat_type, line, odds_type, game_starts_at,
    )
    return DfsLine(
        id=row["id"],
        source=row["source"],
        external_id=row["external_id"],
        sport=row["sport"],
        player_name=row["player_name"],
        team=row["team"],
        stat_type=row["stat_type"],
        line=float(row["line"]),
        odds_type=row["odds_type"],
        game_starts_at=row["game_starts_at"],
        is_active=row["is_active"],
    )


async def fetch_active_dfs_lines(
    pool: asyncpg.Pool, *, source: str | None = None
) -> list[DfsLine]:
    """Active lines for one source, or ALL sources when source is None
    (so PrizePicks + Underdog + Sleeper all get scored)."""
    rows = await pool.fetch(
        """
        SELECT id, source, external_id, sport, player_name, team,
               stat_type, line, odds_type, game_starts_at, is_active
        FROM dfs_lines
        WHERE ($1::text IS NULL OR source = $1) AND is_active = true
          AND game_starts_at > NOW() - INTERVAL '2 hours'
        ORDER BY game_starts_at, player_name
        """,
        source,
    )
    return [
        DfsLine(
            id=r["id"],
            source=r["source"],
            external_id=r["external_id"],
            sport=r["sport"],
            player_name=r["player_name"],
            team=r["team"],
            stat_type=r["stat_type"],
            line=float(r["line"]),
            odds_type=r["odds_type"],
            game_starts_at=r["game_starts_at"],
            is_active=r["is_active"],
        )
        for r in rows
    ]


async def sweep_inactive_lines(
    pool: asyncpg.Pool,
    *,
    source: str,
    sport: str,
    seen_external_ids: list[str],
    full_fetch: bool,
) -> int:
    """Mark-and-sweep stale lines so we never show a line that no longer exists.

    Always deactivates lines whose game has already tipped (DFS apps suspend
    props once live, so a pre-game line is stale the moment the ball goes up).
    When `full_fetch` is True (the platform actually returned data this sync),
    also deactivates any line the platform no longer offers. On an empty/failed
    fetch we skip the vanished-line sweep so a rate-limit blip can't wipe the
    whole board. Returns rows deactivated."""
    if full_fetch:
        result = await pool.execute(
            """UPDATE dfs_lines SET is_active = false, updated_at = NOW()
               WHERE source = $1 AND lower(sport) = lower($2) AND is_active = true
                 AND (game_starts_at < NOW() OR external_id != ALL($3::text[]))""",
            source, sport, seen_external_ids,
        )
    else:
        result = await pool.execute(
            """UPDATE dfs_lines SET is_active = false, updated_at = NOW()
               WHERE source = $1 AND lower(sport) = lower($2) AND is_active = true
                 AND game_starts_at < NOW()""",
            source, sport,
        )
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError, AttributeError):
        return 0


async def insert_dfs_opportunity(
    pool: asyncpg.Pool,
    *,
    dfs_line_id: int,
    pick_side: str,
    consensus_fair_prob: float,
    breakeven_per_leg: float,
    edge_pct: float,
    num_sharp_books: int,
    projection_fair_prob: float | None = None,
    blended_fair_prob: float | None = None,
    projection_sample_size: int | None = None,
    book_breakdown: str | None = None,
) -> None:
    await pool.execute(
        """
        INSERT INTO dfs_opportunities (
            dfs_line_id, pick_side, consensus_fair_prob, breakeven_per_leg,
            edge_pct, num_sharp_books, projection_fair_prob, blended_fair_prob,
            projection_sample_size, book_breakdown
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """,
        dfs_line_id,
        pick_side,
        Decimal(str(round(consensus_fair_prob, 6))),
        Decimal(str(round(breakeven_per_leg, 6))),
        Decimal(str(round(edge_pct, 4))),
        num_sharp_books,
        Decimal(str(round(projection_fair_prob, 6))) if projection_fair_prob is not None else None,
        Decimal(str(round(blended_fair_prob, 6))) if blended_fair_prob is not None else None,
        projection_sample_size,
        book_breakdown,
    )
