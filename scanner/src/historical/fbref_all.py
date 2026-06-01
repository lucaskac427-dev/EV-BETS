"""Mass FBref historical ingest — every supported league × many seasons.

soccerdata FBref default leagues are the big-5 + 3 international tournaments.
We ingest every available season for each. To add exotic leagues (MLS, Brazil
Série A, Argentina Primera, etc.), they need explicit FBref URL configs
through soccerdata.add_leagues — left as a follow-up.

Run:
    python -m src.historical.fbref_all
    python -m src.historical.fbref_all --from-season 2010 --to-season 2024
"""

import argparse
import asyncio
import time

import soccerdata as sd

from src.config import settings
from src.historical.fbref import ingest_league
from src.historical.fbref_extras import register_extras
from src.logger import configure_logging, log


# Big-5 + major international tournaments (work out of the box) + extras we
# register via fbref_extras (MLS, Brazil, Argentina, Eredivisie, Primeira,
# Liga MX, Championship, UCL, Europa League).
DEFAULT_LEAGUES = [
    # Big 5
    "ENG-Premier League",
    "ESP-La Liga",
    "ITA-Serie A",
    "GER-Bundesliga",
    "FRA-Ligue 1",
    # International
    "INT-World Cup",
    "INT-European Championship",
    # Extras
    "USA-Major League Soccer",
    "BRA-Série A",
    "ARG-Primera División",
    "NED-Eredivisie",
    "POR-Primeira Liga",
    "MEX-Liga MX",
    "ENG-Championship",
    "UEFA-Champions League",
    "UEFA-Europa League",
]


def season_strs(from_year: int, to_year: int) -> list[str]:
    """FBref season strings — 4-digit for international tournaments
    ('2024'), 4-digit YYYY for the second calendar year of European
    league seasons. soccerdata accepts both formats and picks the right
    one based on the league."""
    return [str(y) for y in range(from_year, to_year + 1)]


async def main(from_year: int = 2010, to_year: int = 2024) -> None:
    configure_logging(level=settings.log_level)
    n_extras = register_extras()
    log.info("fbref_extras_registered", count=n_extras)
    seasons = season_strs(from_year, to_year)
    log.info("fbref_mass_start", leagues=DEFAULT_LEAGUES, seasons=seasons)

    grand_total = 0
    for league in DEFAULT_LEAGUES:
        for season in seasons:
            try:
                n = await ingest_league(league, [season])
                grand_total += n
                log.info("fbref_pair_done", league=league, season=season, rows=n)
            except Exception as e:
                log.warning(
                    "fbref_pair_failed",
                    league=league,
                    season=season,
                    error=str(e),
                )
            # FBref rate-limits aggressively
            time.sleep(2.0)
    log.info("fbref_mass_complete", grand_total=grand_total)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-season", type=int, default=2010)
    parser.add_argument("--to-season", type=int, default=2024)
    args = parser.parse_args()
    asyncio.run(main(from_year=args.from_season, to_year=args.to_season))
