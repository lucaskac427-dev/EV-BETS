"""Reconcile finished games into market_outcomes.

For each player-prop market whose game has started and isn't settled, look up the
player's game log on that game's date and compare the actual stat to the line.

Matching is by player_id + game_date (the date portion of game_starts_at). This
is a baseline heuristic; Plan 3 can tighten it with explicit game_id mapping.
"""

import asyncio

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.projections.engine import StatSample, extract_stat
from src.repositories.game_logs import player_id_by_name, recent_logs_for_player
from src.repositories.outcomes import markets_needing_settlement, upsert_market_outcome


async def reconcile_outcomes(pool) -> int:
    pending = await markets_needing_settlement(pool)
    settled = 0
    for m in pending:
        player_name = m["player_name"]
        stat = m["stat_type"]
        line = float(m["line"]) if m["line"] is not None else None
        if not player_name or not stat or line is None:
            continue

        player_id = await player_id_by_name(pool, player_name)
        if player_id is None:
            continue

        game_date = m["game_starts_at"].date()
        logs = await recent_logs_for_player(pool, player_id, limit=40)
        match = next((l for l in logs if l.game_date == game_date), None)
        if match is None:
            continue  # game log not ingested yet — try again next run

        sample = StatSample(
            points=match.points or 0, rebounds=match.rebounds or 0,
            assists=match.assists or 0, threes=match.threes or 0,
            blocks=match.blocks or 0, steals=match.steals or 0,
        )
        try:
            actual = extract_stat(sample, stat)
        except ValueError:
            continue

        outcome = "over" if actual > line else "under"
        await upsert_market_outcome(
            pool, market_id=m["id"], outcome=outcome, actual_value=float(actual)
        )
        settled += 1

    log.info("reconcile_complete", settled=settled, pending=len(pending))
    return settled


async def main() -> None:
    configure_logging(level=settings.log_level)
    try:
        pool = await get_pool()
        await reconcile_outcomes(pool)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
