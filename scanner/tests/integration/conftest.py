"""Integration test fixtures — require a running Postgres on localhost:5432.

Run docker compose up -d before invoking these tests.
"""

import pytest_asyncio

from src.config import settings
from src.db import close_pool, get_pool


@pytest_asyncio.fixture(scope="session")
async def pool():
    """Session-scoped asyncpg pool. Torn down at end of session."""
    p = await get_pool()
    yield p
    await close_pool()


@pytest_asyncio.fixture(autouse=True)
async def _clean_db(pool):
    """Truncate all test tables before each test so they don't interfere.

    Hard guard: refuse to truncate unless we're on a test database. This
    fixture has wiped the real kalshi_ev DB before (player_game_logs, etc.);
    never again."""
    if "test" not in settings.database_url:
        raise RuntimeError(
            f"Refusing to TRUNCATE: DATABASE_URL is not a test database "
            f"({settings.database_url!r}). Point tests at kalshi_ev_test "
            f"(see tests/conftest.py)."
        )
    async with pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE markets, odds_snapshots, projections, news_events, "
            "opportunities, bets, bet_results, market_outcomes, "
            "scan_telemetry, player_game_logs, team_defense_ratings, "
            "league_averages RESTART IDENTITY CASCADE"
        )
    yield
