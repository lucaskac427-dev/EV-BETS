"""NBA stats ingest.

Two modes:
  - Default (`run_ingest`): nightly recency update — last 20 games + current
    team defense + league averages for the current season.
  - Historical (`run_historical_backfill`): walk every season from
    start_year..end_year, full game logs each. Used to populate the all-time
    priors. Sleeps between seasons to avoid rate limiting.

Run as:
    python -m src.nba_stats.ingest                       # nightly recency
    python -m src.nba_stats.ingest --backfill 2000 2025  # all-time backfill
"""

import argparse
import asyncio
import time

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.nba_stats.client import (
    fetch_player_game_logs,
    fetch_team_defense,
    season_keys,
)
from src.repositories.game_logs import (
    upsert_game_logs,
    upsert_league_averages,
    upsert_team_defense,
)

CURRENT_SEASON = "2025-26"


async def run_ingest(*, season: str = CURRENT_SEASON, last_n_games: int = 20) -> dict[str, int]:
    pool = await get_pool()
    logs = await asyncio.to_thread(
        fetch_player_game_logs, season=season, last_n_games=last_n_games
    )
    log_count = await upsert_game_logs(pool, logs)

    defense = await asyncio.to_thread(fetch_team_defense, season=season)
    def_count = await upsert_team_defense(pool, defense)

    if defense:
        avg_def = sum(d["def_rating"] or 0 for d in defense) / len(defense)
        avg_pace = sum(d["pace"] or 0 for d in defense) / len(defense)
        await upsert_league_averages(
            pool, season=season, avg_def_rating=avg_def, avg_pace=avg_pace
        )

    log.info(
        "nba_ingest_complete",
        season=season,
        logs=log_count,
        teams=def_count,
    )
    return {"logs": log_count, "teams": def_count}


async def run_historical_backfill(
    *,
    start_year: int = 2000,
    end_year: int = 2025,
    sleep_between_seasons_s: float = 1.5,
) -> dict[str, int]:
    """Backfill every season's full game logs + team defense. Polite delay
    between seasons since stats.nba.com rate-limits aggressively."""
    seasons = season_keys(start_year, end_year)
    totals = {"logs": 0, "teams": 0, "seasons_done": 0}
    for s in seasons:
        try:
            r = await run_ingest(season=s, last_n_games=0)
        except Exception as e:
            log.warning("nba_season_failed", season=s, error=str(e))
            continue
        totals["logs"] += r["logs"]
        totals["teams"] += r["teams"]
        totals["seasons_done"] += 1
        log.info("nba_backfill_progress", **totals)
        time.sleep(sleep_between_seasons_s)
    log.info("nba_backfill_complete", **totals)
    return totals


async def main(*, backfill: tuple[int, int] | None = None) -> None:
    configure_logging(level=settings.log_level)
    try:
        if backfill:
            await run_historical_backfill(
                start_year=backfill[0], end_year=backfill[1]
            )
        else:
            await run_ingest()
    finally:
        await close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backfill",
        nargs=2,
        type=int,
        metavar=("START_YEAR", "END_YEAR"),
        help="Run a historical backfill across NBA seasons START..END (inclusive)",
    )
    args = parser.parse_args()
    asyncio.run(main(backfill=tuple(args.backfill) if args.backfill else None))
