"""Repository for the projections table (written nightly, read by pipeline)."""

from dataclasses import dataclass
from decimal import Decimal

import asyncpg


@dataclass(frozen=True, slots=True)
class StoredProjection:
    market_id: int
    fair_prob_over: float
    model_version: str


async def insert_projection(
    pool: asyncpg.Pool,
    *,
    market_id: int,
    mean: float,
    std_dev: float,
    distribution: str,
    fair_prob_over: float,
    model_version: str,
) -> int:
    row = await pool.fetchrow(
        """
        INSERT INTO projections (market_id, mean, std_dev, distribution,
                                 fair_prob_over, model_version)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        market_id, Decimal(str(round(mean, 3))), Decimal(str(round(std_dev, 3))),
        distribution, Decimal(str(round(fair_prob_over, 6))), model_version,
    )
    return row["id"]


async def latest_projection_prob(pool: asyncpg.Pool, market_id: int) -> float | None:
    """Most recent projection's fair_prob_over for a market, or None."""
    row = await pool.fetchrow(
        """
        SELECT fair_prob_over FROM projections
        WHERE market_id = $1
        ORDER BY computed_at DESC LIMIT 1
        """,
        market_id,
    )
    return float(row["fair_prob_over"]) if row else None
