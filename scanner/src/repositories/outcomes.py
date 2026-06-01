"""Repository for market_outcomes + the snapshot lookups Brier scoring needs."""

from dataclasses import dataclass

import asyncpg

from src.math.devig import devig


@dataclass(frozen=True, slots=True)
class SettledMarket:
    market_id: int
    outcome: str  # 'over' | 'under'


async def upsert_market_outcome(
    pool: asyncpg.Pool, *, market_id: int, outcome: str, actual_value: float | None
) -> None:
    await pool.execute(
        """
        INSERT INTO market_outcomes (market_id, outcome, actual_value)
        VALUES ($1, $2, $3)
        ON CONFLICT (market_id) DO UPDATE SET
            outcome = EXCLUDED.outcome, actual_value = EXCLUDED.actual_value,
            settled_at = now()
        """,
        market_id, outcome, actual_value,
    )


async def settled_over_under_since(pool: asyncpg.Pool, days: int) -> list[SettledMarket]:
    """Markets settled in the last `days` whose outcome is over/under (excludes push/void)."""
    rows = await pool.fetch(
        """
        SELECT market_id, outcome FROM market_outcomes
        WHERE outcome IN ('over', 'under')
          AND settled_at >= now() - ($1::text || ' days')::interval
        """,
        str(days),
    )
    return [SettledMarket(market_id=r["market_id"], outcome=r["outcome"]) for r in rows]


async def book_fair_prob_over(
    pool: asyncpg.Pool, market_id: int, book: str
) -> float | None:
    """Devig a book's latest over/under snapshot pair for a market. None if the
    book didn't quote both sides."""
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (side) side, implied_prob
        FROM odds_snapshots
        WHERE market_id = $1 AND book = $2 AND side IN ('over', 'under')
        ORDER BY side, fetched_at DESC
        """,
        market_id, book,
    )
    by_side = {r["side"]: float(r["implied_prob"]) for r in rows}
    if "over" not in by_side or "under" not in by_side:
        return None
    fair_over, _ = devig(by_side["over"], by_side["under"])
    return fair_over


async def markets_needing_settlement(pool: asyncpg.Pool) -> list[dict]:
    """Player-prop markets whose game has started but have no outcome yet."""
    rows = await pool.fetch(
        """
        SELECT m.id, m.player_name, m.stat_type, m.line, m.game_starts_at
        FROM markets m
        LEFT JOIN market_outcomes o ON o.market_id = m.id
        WHERE o.market_id IS NULL
          AND m.market_type = 'player_prop'
          AND m.game_starts_at < now()
        """
    )
    return [dict(r) for r in rows]
