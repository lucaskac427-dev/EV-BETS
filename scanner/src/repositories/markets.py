"""Markets repository — CRUD for the markets table."""

from dataclasses import dataclass
from datetime import datetime

import asyncpg


@dataclass(frozen=True, slots=True)
class Market:
    id: int
    sport: str
    kalshi_ticker: str
    market_type: str
    player_name: str | None
    stat_type: str | None
    line: float | None
    game_id: str
    game_starts_at: datetime
    is_active: bool


async def upsert_market(
    pool: asyncpg.Pool,
    *,
    sport: str,
    kalshi_ticker: str,
    market_type: str,
    game_id: str,
    game_starts_at: datetime,
    player_name: str | None = None,
    stat_type: str | None = None,
    line: float | None = None,
) -> Market:
    """Insert market or return existing by kalshi_ticker."""
    row = await pool.fetchrow(
        """
        INSERT INTO markets (sport, kalshi_ticker, market_type, player_name,
                             stat_type, line, game_id, game_starts_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (kalshi_ticker) DO UPDATE SET game_starts_at = EXCLUDED.game_starts_at
        RETURNING id, sport, kalshi_ticker, market_type, player_name, stat_type,
                  line, game_id, game_starts_at, is_active
        """,
        sport, kalshi_ticker, market_type, player_name, stat_type,
        line, game_id, game_starts_at,
    )
    return Market(**dict(row))


async def fetch_active_markets(pool: asyncpg.Pool) -> list[Market]:
    """All markets with is_active=true."""
    rows = await pool.fetch(
        """
        SELECT id, sport, kalshi_ticker, market_type, player_name, stat_type,
               line, game_id, game_starts_at, is_active
        FROM markets
        WHERE is_active = true
        ORDER BY game_starts_at
        """
    )
    return [Market(**dict(r)) for r in rows]
