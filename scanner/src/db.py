"""asyncpg connection pool — single global pool for the scanner service."""

import asyncpg

from src.config import settings
from src.logger import log

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Lazy-init the pool the first time it's requested."""
    global _pool
    if _pool is None:
        # asyncpg expects DSN with `postgresql://` (no `+driver`)
        dsn = settings.database_url.replace("postgresql+psycopg2://", "postgresql://")
        _pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=1,
            max_size=10,
            command_timeout=10,
        )
        log.info("db_pool_initialized", dsn=dsn)
    return _pool


async def close_pool() -> None:
    """Cleanup hook for graceful shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
