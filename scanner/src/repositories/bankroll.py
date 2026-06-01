"""Bankroll repository — current balance from latest event row."""

import asyncpg


async def current_bankroll_cents(pool: asyncpg.Pool, user_id: int = 1) -> int:
    """Return latest balance_cents for the user. 0 if no events yet."""
    row = await pool.fetchrow(
        """
        SELECT balance_cents FROM bankroll_events
        WHERE user_id = $1
        ORDER BY id DESC LIMIT 1
        """,
        user_id,
    )
    return int(row["balance_cents"]) if row else 0
