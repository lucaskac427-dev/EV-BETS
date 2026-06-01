"""WNBA play-by-play ingest via pbpstats (dblackrun/pbpstats).

pbpstats parses stats.nba.com PBP into possession-level events with on-court
context — the foundation for possession / usage modeling later. We flatten each
event to `wnba_pbp_events`. Per-game web fetches (stats.nba.com rate-limits), so
the backfill is paced and resumable (games already stored are skipped).

    python -m src.wnba_stats.playbyplay --game 1022500286   # one game (test)
    python -m src.wnba_stats.playbyplay --backfill          # every stored WNBA game
"""

import argparse
import asyncio
import time
from typing import Any

from pbpstats.client import Client

from src.db import close_pool, get_pool
from src.logger import configure_logging, log

_SETTINGS = {"Possessions": {"source": "web", "data_provider": "stats_nba"}}

_CREATE = """
CREATE TABLE IF NOT EXISTS wnba_pbp_events (
    game_id      TEXT NOT NULL,
    event_num    INTEGER NOT NULL,
    period       INTEGER,
    clock        TEXT,
    seconds      REAL,
    event_type   TEXT,
    description  TEXT,
    team_id      BIGINT,
    player1_id   BIGINT,
    PRIMARY KEY (game_id, event_num)
);
CREATE INDEX IF NOT EXISTS wnba_pbp_game ON wnba_pbp_events (game_id);
"""

_COLS = ["game_id", "event_num", "period", "clock", "seconds",
         "event_type", "description", "team_id", "player1_id"]

_UPSERT = (
    f"INSERT INTO wnba_pbp_events ({', '.join(_COLS)}) "
    f"VALUES ({', '.join('$' + str(i + 1) for i in range(len(_COLS)))}) "
    f"ON CONFLICT (game_id, event_num) DO NOTHING"
)


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _num(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _g(e: Any, *names: str) -> Any:
    for n in names:
        v = getattr(e, n, None)
        if v is not None:
            return v
    return None


def fetch_pbp(client: Client, game_id: str) -> list[dict]:
    """Flatten one game's pbpstats events to plain row dicts."""
    game = client.Game(game_id)
    rows: list[dict] = []
    for poss in game.possessions.items:
        for e in poss.events:
            rows.append({
                "game_id": str(_g(e, "game_id") or game_id),
                "event_num": _int(_g(e, "event_num")) or 0,
                "period": _int(_g(e, "period")),
                "clock": (str(_g(e, "clock")) or None) if _g(e, "clock") is not None else None,
                "seconds": _num(_g(e, "seconds_remaining")),
                "event_type": type(e).__name__,
                "description": (str(_g(e, "description")) or None) if _g(e, "description") else None,
                "team_id": _int(_g(e, "team_id")),
                "player1_id": _int(_g(e, "player1_id", "player_id")),
            })
    return rows


async def _upsert(pool, rows: list[dict]) -> int:
    if not rows:
        return 0
    async with pool.acquire() as con:
        await con.executemany(_UPSERT, [[r[c] for c in _COLS] for r in rows])
    return len(rows)


async def backfill(*, game_id: str | None = None, throttle: float = 1.2) -> int:
    """Ingest PBP for one game (--game) or every WNBA game we have a box score
    for that isn't already stored. Resumable."""
    configure_logging(level="WARNING")
    pool = await get_pool()
    client = Client(_SETTINGS)
    try:
        for stmt in _CREATE.strip().split(";"):
            if stmt.strip():
                await pool.execute(stmt)
        if game_id:
            gids = [game_id]
        else:
            have = {r["game_id"] for r in await pool.fetch("SELECT DISTINCT game_id FROM wnba_pbp_events")}
            allg = [r["game_id"] for r in await pool.fetch("SELECT DISTINCT game_id FROM wnba_game_logs ORDER BY game_id DESC")]
            gids = [g for g in allg if g not in have]
        log.warning("wnba_pbp_backfill_start", games=len(gids))
        total = 0
        for i, gid in enumerate(gids, 1):
            try:
                rows = await asyncio.to_thread(fetch_pbp, client, gid)
                total += await _upsert(pool, rows)
            except Exception as e:
                log.warning("wnba_pbp_game_failed", game=gid, error=str(e)[:120])
            if i % 25 == 0:
                log.warning("wnba_pbp_progress", done=i, total_games=len(gids), events=total)
            await asyncio.sleep(throttle)
        print(f"wnba pbp: {total} events across {len(gids)} games")
        return total
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--game", help="ingest a single game_id (test)")
    p.add_argument("--backfill", action="store_true", help="all stored WNBA games")
    p.add_argument("--throttle", type=float, default=1.2)
    a = p.parse_args()
    if a.game:
        asyncio.run(backfill(game_id=a.game, throttle=a.throttle))
    elif a.backfill:
        asyncio.run(backfill(throttle=a.throttle))
    else:
        p.error("pass --game <id> or --backfill")
