"""Nightly projection job: active markets → projection rows.

Run as `python -m src.projections.job`. Scheduled by projections-cron (Plan 3).
"""

import asyncio

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.projections.engine import StatSample, project
from src.repositories.game_logs import (
    league_averages,
    player_id_by_name,
    recent_logs_for_player,
    team_defense,
)
from src.repositories.markets import Market, fetch_active_markets
from src.repositories.projections import insert_projection

MODEL_VERSION = "baseline-v1"


def _opponent_abbr(market: Market) -> str | None:
    """game_id is 'AWAY-HOME' (e.g. 'LAL-BOS'). The opponent is whichever side
    is NOT the player's team. We don't know the player's team here, so the job
    passes both candidates and picks the one with team_defense data."""
    parts = market.game_id.split("-")
    return parts if len(parts) == 2 else None


async def run_projection_job(pool, *, season: str) -> int:
    markets = await fetch_active_markets(pool)
    avg = await league_averages(pool, season)
    if avg is None:
        log.warning("projection_job_no_league_avg", season=season)
        return 0

    written = 0
    for market in markets:
        if market.market_type != "player_prop" or not market.player_name or not market.stat_type:
            continue
        if market.line is None:
            continue

        player_id = await player_id_by_name(pool, market.player_name)
        if player_id is None:
            continue

        logs = await recent_logs_for_player(pool, player_id, limit=20)
        if not logs:
            continue

        player_team = logs[0].team_abbr
        candidates = _opponent_abbr(market)
        if not candidates:
            continue
        opp_abbr = next((c for c in candidates if c != player_team), None)
        if opp_abbr is None:
            continue
        opp = await team_defense(pool, opp_abbr)
        if opp is None:
            continue

        samples = [
            StatSample(
                points=l.points or 0, rebounds=l.rebounds or 0, assists=l.assists or 0,
                threes=l.threes or 0, blocks=l.blocks or 0, steals=l.steals or 0,
            )
            for l in logs
        ]
        proj = project(
            samples=samples,
            stat=market.stat_type,
            line=float(market.line),
            opp_def_rating=opp["def_rating"],
            league_avg_def_rating=avg["avg_def_rating"],
            opp_pace=opp["pace"],
            league_avg_pace=avg["avg_pace"],
            is_b2b=False,  # Plan 2 doesn't compute rest; Plan 3 can add schedule lookup
        )
        if proj is None:
            continue

        await insert_projection(
            pool, market_id=market.id, mean=proj.mean, std_dev=proj.std,
            distribution=proj.distribution, fair_prob_over=proj.fair_prob_over,
            model_version=MODEL_VERSION,
        )
        written += 1

    log.info("projection_job_complete", written=written)
    return written


async def main() -> None:
    configure_logging(level=settings.log_level)
    try:
        pool = await get_pool()
        await run_projection_job(pool, season="2025-26")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
