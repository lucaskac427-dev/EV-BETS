"""Odds snapshots repository — append-only bulk insert."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import asyncpg


@dataclass(frozen=True, slots=True)
class OddsSnapshot:
    market_id: int
    book: str
    side: str
    decimal_odds: Decimal
    implied_prob: Decimal


async def bulk_insert_snapshots(
    pool: asyncpg.Pool, snapshots: list[OddsSnapshot]
) -> int:
    """Bulk insert; returns count inserted."""
    if not snapshots:
        return 0
    records = [
        (s.market_id, s.book, s.side, s.decimal_odds, s.implied_prob)
        for s in snapshots
    ]
    await pool.executemany(
        """
        INSERT INTO odds_snapshots (market_id, book, side, decimal_odds, implied_prob)
        VALUES ($1, $2, $3, $4, $5)
        """,
        records,
    )
    return len(records)


async def latest_snapshot_per_book(
    pool: asyncpg.Pool, market_id: int
) -> dict[str, tuple[str, Decimal, Decimal]]:
    """For a given market, return latest (side, decimal_odds, implied_prob) per book.

    Useful for verifying snapshots wrote correctly. Plan 1 actually uses
    in-memory values from the current tick — this is for inspection/tests.
    """
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (book, side)
            book, side, decimal_odds, implied_prob, fetched_at
        FROM odds_snapshots
        WHERE market_id = $1
        ORDER BY book, side, fetched_at DESC
        """,
        market_id,
    )
    out: dict[str, tuple[str, Decimal, Decimal]] = {}
    for r in rows:
        out[f"{r['book']}:{r['side']}"] = (r["side"], r["decimal_odds"], r["implied_prob"])
    return out
