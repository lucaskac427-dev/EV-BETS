"""Mass StatsBomb open-data ingest — every available (competition, season).

Pulls competitions.json, iterates every entry, runs the same per-competition
ingest in sequence (skipping already-completed pairs by checking the DB).

Run:
    python -m src.historical.statsbomb_all
    python -m src.historical.statsbomb_all --skip-existing
"""

import argparse
import asyncio
from collections import Counter

import httpx

from src.config import settings
from src.db import close_pool, get_pool
from src.historical.statsbomb import (
    SB_BASE,
    _fetch_json,
    ingest_competition,
)
from src.logger import configure_logging, log


async def _existing_pairs(pool) -> set[tuple[str, str]]:
    rows = await pool.fetch(
        "SELECT DISTINCT competition_name, season_name FROM soccer_player_match_stats WHERE source = 'statsbomb'"
    )
    return {(r["competition_name"], r["season_name"]) for r in rows}


async def main(skip_existing: bool = True) -> None:
    configure_logging(level=settings.log_level)
    pool = await get_pool()

    existing: set[tuple[str, str]] = set()
    if skip_existing:
        existing = await _existing_pairs(pool)
        log.info("statsbomb_existing_pairs", count=len(existing))

    async with httpx.AsyncClient(timeout=30.0) as client:
        comps = await _fetch_json(client, "competitions.json")

    pairs = [
        (c["competition_name"], c["season_name"])
        for c in comps
        if (c["competition_name"], c["season_name"]) not in existing
    ]
    log.info("statsbomb_pairs_to_ingest", total=len(pairs))
    # close pool — ingest_competition opens its own
    await close_pool()

    totals = Counter()
    for i, (comp, season) in enumerate(pairs, 1):
        log.info("statsbomb_mass_progress", i=i, of=len(pairs), comp=comp, season=season)
        try:
            n = await ingest_competition(comp, season)
            totals["rows"] += n
            totals["completed"] += 1
        except Exception as e:
            log.warning(
                "statsbomb_mass_failed",
                comp=comp,
                season=season,
                error=str(e),
            )
            totals["failed"] += 1

    log.info("statsbomb_mass_complete", **dict(totals))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip (competition, season) pairs already in the table",
    )
    parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Re-ingest pairs that are already in the table",
    )
    args = parser.parse_args()
    skip = not args.include_existing
    asyncio.run(main(skip_existing=skip))
