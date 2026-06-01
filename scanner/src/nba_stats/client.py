"""Thin wrapper over nba_api endpoints.

nba_api hits NBA.com's undocumented stats API. It can rate-limit or change
shape without notice, so every call is retried with backoff and returns plain
dicts (not dataframes) so the rest of the system never imports pandas.

Column names come from nba_api's `expected_data` — see
_resources/sports-betting-refs/nba_api/src/nba_api/stats/endpoints/playergamelogs.py
"""

from typing import Any

from nba_api.stats.endpoints import LeagueDashTeamStats, PlayerGameLogs
from nba_api.stats.static import teams as static_teams
from tenacity import retry, stop_after_attempt, wait_exponential

from src.logger import log


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_player_game_logs(
    *, season: str, last_n_games: int = 0
) -> list[dict[str, Any]]:
    """Return player game-log rows as dicts. One row per (player, game).

    last_n_games=0 (default) means the full season — works for historical
    backfills. Pass last_n_games=20 for the nightly recency update.
    """
    endpoint = PlayerGameLogs(
        season_nullable=season,
        last_n_games_nullable=last_n_games,
    )
    df = endpoint.get_data_frames()[0]
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        rows.append(
            {
                "player_id": int(r["PLAYER_ID"]),
                "player_name": str(r["PLAYER_NAME"]),
                "team_abbr": str(r["TEAM_ABBREVIATION"]),
                "game_id": str(r["GAME_ID"]),
                "game_date": str(r["GAME_DATE"])[:10],
                "matchup": str(r["MATCHUP"]),
                "minutes": _num(r.get("MIN")),
                "points": _int(r.get("PTS")),
                "rebounds": _int(r.get("REB")),
                "assists": _int(r.get("AST")),
                "threes": _int(r.get("FG3M")),
                "blocks": _int(r.get("BLK")),
                "steals": _int(r.get("STL")),
            }
        )
    log.info("nba_player_logs_fetched", count=len(rows), season=season)
    return rows


def season_keys(start_year: int = 2000, end_year: int = 2025) -> list[str]:
    """NBA season keys ('YYYY-YY') from start_year-(start_year+1) to
    end_year-(end_year+1). NBA seasons span two calendar years."""
    seasons: list[str] = []
    for y in range(start_year, end_year + 1):
        seasons.append(f"{y}-{str(y + 1)[-2:]}")
    return seasons


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_team_defense(*, season: str) -> list[dict[str, Any]]:
    """Return per-team defensive metrics as dicts.

    The Advanced measure type returns TEAM_ID + TEAM_NAME (no abbreviation) and
    has no opponent-points column, so we map TEAM_ID -> abbreviation via the
    static teams table. opp_pts_per_game is not exposed by Advanced and is not
    used by the projection engine (which keys off def_rating + pace), so it
    defaults to 0.0.
    """
    id_to_abbr = {t["id"]: t["abbreviation"] for t in static_teams.get_teams()}
    endpoint = LeagueDashTeamStats(
        season=season,
        measure_type_detailed_defense="Advanced",
    )
    df = endpoint.get_data_frames()[0]
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        abbr = id_to_abbr.get(int(r["TEAM_ID"]))
        if abbr is None:
            continue
        rows.append(
            {
                "team_abbr": abbr,
                "def_rating": _num(r.get("DEF_RATING")),
                "pace": _num(r.get("PACE")),
                "opp_pts_per_game": 0.0,
            }
        )
    log.info("nba_team_defense_fetched", count=len(rows), season=season)
    return rows


def _num(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None
