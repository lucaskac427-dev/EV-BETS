"""Understat player-match-stats ingest.

Understat is the cleanest free continuous source of per-player per-match
shooting data (shots, xG, xA, key passes, assists, goals, minutes) for the
big-5 European leagues, 2014/15 → present. After FBref's detailed data was
pulled in Jan 2026, this is the primary free spine for the projection model.

Joins read_player_match_stats to read_schedule (by game_id) to attach the
real match date, then upserts into soccer_player_match_stats.

Run:
    python -m src.historical.understat_ingest
    python -m src.historical.understat_ingest --from-season 2014 --to-season 2025
"""

import argparse
import asyncio
import re
import unicodedata

import soccerdata as sd

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log

LEAGUES = [
    "ENG-Premier League",
    "ESP-La Liga",
    "ITA-Serie A",
    "GER-Bundesliga",
    "FRA-Ligue 1",
]

_COMP_LABEL = {
    "ENG-Premier League": "Premier League",
    "ESP-La Liga": "La Liga",
    "ITA-Serie A": "Serie A",
    "GER-Bundesliga": "Bundesliga",
    "FRA-Ligue 1": "Ligue 1",
}


def _slug(name: str) -> str:
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z]+", "", ascii_only).upper()


def _i(v):
    try:
        return int(float(v)) if v is not None and str(v) != "nan" else None
    except (TypeError, ValueError):
        return None


def _f(v):
    try:
        f = float(v)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None


async def _upsert(pool, rec: dict) -> None:
    await pool.execute(
        """
        INSERT INTO soccer_player_match_stats
            (source, competition_name, season_name, match_id, match_date,
             home_team, away_team, player_id, player_name, player_name_slug,
             team_name, position, minutes_played, shots, goals, assists, xg, xa)
        VALUES ('understat',$1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
        ON CONFLICT DO NOTHING
        """,
        rec["competition_name"], rec["season_name"], rec["match_id"],
        rec["match_date"], rec["home_team"], rec["away_team"], rec["player_id"],
        rec["player_name"], rec["player_name_slug"], rec["team_name"],
        rec["position"], rec["minutes_played"], rec["shots"], rec["goals"],
        rec["assists"], rec["xg"], rec["xa"],
    )


async def ingest_league_season(pool, league: str, season: str) -> int:
    try:
        us = sd.Understat(leagues=[league], seasons=[season])
        sched = us.read_schedule().reset_index()
        stats = us.read_player_match_stats().reset_index()
    except Exception as e:
        log.warning("understat_fetch_failed", league=league, season=season, error=str(e)[:120])
        return 0

    # game_id -> (date, home, away)
    date_col = "date" if "date" in sched.columns else None
    game_map: dict = {}
    for _, row in sched.iterrows():
        gid = row.get("game_id")
        if gid is None:
            continue
        game_map[str(gid)] = (
            row.get(date_col).date() if date_col and row.get(date_col) is not None else None,
            row.get("home_team"), row.get("away_team"),
        )

    n = 0
    for _, r in stats.iterrows():
        gid = str(r.get("game_id"))
        md, home, away = game_map.get(gid, (None, None, None))
        pid = _i(r.get("player_id"))
        pname = r.get("player")
        if pname is None:
            continue
        rec = {
            "competition_name": _COMP_LABEL.get(league, league),
            "season_name": str(season),
            "match_id": _i(gid) or 0,
            "match_date": md,
            "home_team": home,
            "away_team": away,
            "player_id": pid,
            "player_name": pname,
            "player_name_slug": _slug(pname),
            "team_name": r.get("team"),
            "position": r.get("position"),
            "minutes_played": _i(r.get("minutes")),
            "shots": _i(r.get("shots")),
            "goals": _i(r.get("goals")),
            "assists": _i(r.get("assists")),
            "xg": _f(r.get("xg")),
            "xa": _f(r.get("xa")),
        }
        if rec["match_date"] is None:
            continue
        await _upsert(pool, rec)
        n += 1
    log.info("understat_league_season_done", league=league, season=season, rows=n)
    return n


async def main(from_season: int = 2014, to_season: int = 2025) -> None:
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    try:
        total = 0
        for league in LEAGUES:
            for yr in range(from_season, to_season + 1):
                total += await ingest_league_season(pool, league, str(yr))
        log.info("understat_ingest_complete", total_rows=total)
        print(f"Understat ingest complete: {total:,} player-match rows")
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--from-season", type=int, default=2014)
    p.add_argument("--to-season", type=int, default=2025)
    a = p.parse_args()
    asyncio.run(main(a.from_season, a.to_season))
