"""Scan telemetry repository — append-only event log."""

from datetime import datetime
from typing import Literal

import asyncpg


async def record_event(
    pool: asyncpg.Pool,
    *,
    tick_id: str,
    source: str,
    event_type: Literal["fetch_success", "fetch_failure", "tick_complete", "opps_written"],
    latency_ms: int | None = None,
    status_detail: str | None = None,
) -> None:
    await pool.execute(
        """
        INSERT INTO scan_telemetry (tick_id, source, event_type, latency_ms, status_detail)
        VALUES ($1, $2, $3, $4, $5)
        """,
        tick_id, source, event_type, latency_ms, status_detail,
    )


async def latest_fetch_per_source(pool: asyncpg.Pool) -> dict[str, datetime]:
    """Map source → latest successful fetch timestamp. Used by /health."""
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (source) source, created_at
        FROM scan_telemetry
        WHERE event_type = 'fetch_success'
        ORDER BY source, created_at DESC
        """
    )
    return {r["source"]: r["created_at"] for r in rows}
