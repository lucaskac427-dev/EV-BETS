"""Opportunities repository — append-only inserts; latest-per-market reads."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import asyncpg


@dataclass(frozen=True, slots=True)
class Opportunity:
    id: int
    market_id: int
    kalshi_side: str
    kalshi_decimal_odds: Decimal
    consensus_fair_prob: Decimal
    projection_fair_prob: Decimal | None
    blended_fair_prob: Decimal
    ev_pct: Decimal
    kelly_fraction: Decimal | None
    num_sharp_books: int
    suspicious: bool
    scan_tick_at: datetime


async def insert_opportunity(
    pool: asyncpg.Pool,
    *,
    market_id: int,
    kalshi_side: str,
    kalshi_decimal_odds: Decimal,
    consensus_fair_prob: Decimal,
    projection_fair_prob: Decimal | None,
    blended_fair_prob: Decimal,
    ev_pct: Decimal,
    kelly_fraction: Decimal | None,
    num_sharp_books: int,
    suspicious: bool,
) -> int:
    row = await pool.fetchrow(
        """
        INSERT INTO opportunities (
            market_id, kalshi_side, kalshi_decimal_odds,
            consensus_fair_prob, projection_fair_prob, blended_fair_prob,
            ev_pct, kelly_fraction, num_sharp_books, suspicious
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id
        """,
        market_id, kalshi_side, kalshi_decimal_odds,
        consensus_fair_prob, projection_fair_prob, blended_fair_prob,
        ev_pct, kelly_fraction, num_sharp_books, suspicious,
    )
    return row["id"]


async def fetch_latest_opportunities(
    pool: asyncpg.Pool, *, min_ev: float = 0.01, limit: int = 100
) -> list[Opportunity]:
    """Latest opportunity per market, sorted by EV descending."""
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (market_id)
            id, market_id, kalshi_side, kalshi_decimal_odds,
            consensus_fair_prob, projection_fair_prob, blended_fair_prob,
            ev_pct, kelly_fraction, num_sharp_books, suspicious, scan_tick_at
        FROM opportunities
        WHERE ev_pct >= $1
        ORDER BY market_id, scan_tick_at DESC
        """,
        Decimal(str(min_ev)),
    )
    opps = [Opportunity(**dict(r)) for r in rows]
    opps.sort(key=lambda o: o.ev_pct, reverse=True)
    return opps[:limit]
