"""NBA GAME-LINE projection model (System 2) — predicts each game's TOTAL
points and MARGIN from team form. For TOTALS and SPREADS, never player props.

The model is deliberately simple and honest — an offense-vs-defense points
exchange, the textbook way to project a basketball score:

  league_avg            = mean points a team scores per game (the baseline).
  home_off  = pts_for_l10(home)      - league_avg     # home's offense vs avg
  home_def  = pts_against_l10(home)  - league_avg     # home's defense vs avg
  away_off  = pts_for_l10(away)      - league_avg
  away_def  = pts_against_l10(away)  - league_avg

  exp_home  = league_avg + home_off + away_def + HOME_EDGE/2
  exp_away  = league_avg + away_off + home_def - HOME_EDGE/2

A team's expected points = league baseline, lifted by how good its own offense
is and by how leaky the opponent's defense is, plus a home-court bump. Then:

  projected_total  = exp_home + exp_away
  projected_margin = exp_home - exp_away      # >0 => home favored

That's it. No fitted weights, no opponent-adjustment loops — those would invite
overfitting on a market that's already near-efficient. The whole point of
System 2 is to get an *independent, transparent* fair number we can compare to
the closing line in the backtest; the backtest then tells us, brutally, whether
this signal has any edge (spoiler: game lines are efficient, so expect ~breakeven).

`league_avg` and `HOME_EDGE` are estimated point-in-time from the season's
games BEFORE the game being projected (no leakage), with sane fallbacks early
in a season. Reads team_features (built by features.py); standalone helpers let
the backtest project a game straight from a pair of feature rows.

KNOWN BIAS (measured, not hidden): over the 2023-24 regular season the projected
TOTAL runs ~+6 pts high (MAE ~16.6) because the offense-plus-defense exchange
double-counts strong offenses; projected MARGIN is near-unbiased (MAE ~12).
Both are worse than the closing line, which is why projection_backtest shows the
totals side losing. We keep the model transparent rather than tuning a fudge
factor to fit a market we don't expect to beat.

Run:
    python -m src.projections.nba_game_model --date 2026-05-28
    python -m src.projections.nba_game_model --since 2026-05-01 --limit 20
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import date

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log

# Fallbacks used only when there isn't enough in-season history yet to estimate
# the constants empirically. Modern NBA team scoring is ~114; home edge ~2.5.
DEFAULT_LEAGUE_AVG = 114.0
DEFAULT_HOME_EDGE = 2.5

# Minimum prior games each team needs for the projection to be trustworthy.
MIN_GAMES = 5


@dataclass(frozen=True, slots=True)
class GameProjection:
    game_id: str | None
    game_date: date
    home_abbr: str
    away_abbr: str
    exp_home: float
    exp_away: float
    projected_total: float
    projected_margin: float  # exp_home - exp_away ; >0 => home favored
    league_avg: float
    home_edge: float

    @property
    def fair_home_spread(self) -> float:
        """Spread quoted on the HOME team (negative when home is favored),
        matching how books post it: home -3.5 means home is 3.5 favored."""
        return -round(self.projected_margin, 1)


def project_game(
    *,
    home: dict,
    away: dict,
    league_avg: float = DEFAULT_LEAGUE_AVG,
    home_edge: float = DEFAULT_HOME_EDGE,
    game_id: str | None = None,
    game_date: date | None = None,
) -> GameProjection | None:
    """Project one game from two team_features-shaped dicts (home & away).

    Each dict needs: team_abbr, pts_for_l10, pts_against_l10, games_played
    (falls back to season averages when the L10 columns are NULL early on).
    Returns None if either side lacks the minimum sample."""
    if home.get("games_played", 0) < MIN_GAMES or away.get("games_played", 0) < MIN_GAMES:
        return None

    def form(row: dict, l10_key: str, season_key: str) -> float | None:
        v = row.get(l10_key)
        if v is None:
            v = row.get(season_key)
        return float(v) if v is not None else None

    h_for = form(home, "pts_for_l10", "pts_for_season")
    h_against = form(home, "pts_against_l10", "pts_against_season")
    a_for = form(away, "pts_for_l10", "pts_for_season")
    a_against = form(away, "pts_against_l10", "pts_against_season")
    if None in (h_for, h_against, a_for, a_against):
        return None

    home_off = h_for - league_avg
    home_def = h_against - league_avg
    away_off = a_for - league_avg
    away_def = a_against - league_avg

    exp_home = league_avg + home_off + away_def + home_edge / 2.0
    exp_away = league_avg + away_off + home_def - home_edge / 2.0

    return GameProjection(
        game_id=game_id,
        game_date=game_date or home.get("game_date"),
        home_abbr=home["team_abbr"],
        away_abbr=away["team_abbr"],
        exp_home=round(exp_home, 2),
        exp_away=round(exp_away, 2),
        projected_total=round(exp_home + exp_away, 2),
        projected_margin=round(exp_home - exp_away, 2),
        league_avg=round(league_avg, 2),
        home_edge=round(home_edge, 2),
    )


async def estimate_constants(pool, before: date, season_start: date) -> tuple[float, float]:
    """Estimate (league_avg points/team/game, home_edge) from completed games
    in [season_start, before). Point-in-time: only games strictly before the
    date we're projecting. Falls back to constants until ~30 team-games exist."""
    row = await pool.fetchrow(
        """
        SELECT AVG(pts_scored)::float AS lg,
               AVG(CASE WHEN is_home THEN pts_scored - pts_allowed END)::float AS edge,
               COUNT(*) AS n
        FROM team_features
        WHERE game_date >= $1 AND game_date < $2
          AND pts_scored IS NOT NULL
        """,
        season_start,
        before,
    )
    if not row or row["n"] is None or int(row["n"]) < 30:
        return DEFAULT_LEAGUE_AVG, DEFAULT_HOME_EDGE
    lg = float(row["lg"]) if row["lg"] is not None else DEFAULT_LEAGUE_AVG
    edge = float(row["edge"]) if row["edge"] is not None else DEFAULT_HOME_EDGE
    return lg, edge


def _season_start_for(d: date) -> date:
    """NBA season spans Oct->Jun. A game in Jan 2024 belongs to the season that
    started Oct 2023; a game in Nov 2023 to Oct 2023. Used to bound the
    point-in-time constant estimation to the current season only."""
    return date(d.year if d.month >= 9 else d.year - 1, 10, 1)


async def project_date(pool, game_date: date, *, limit: int | None = None) -> list[GameProjection]:
    """Project every (home) game on a date from team_features. We read the HOME
    rows (is_home) and pull the matching AWAY row by opponent + date."""
    season_start = _season_start_for(game_date)
    league_avg, home_edge = await estimate_constants(pool, game_date, season_start)

    home_rows = await pool.fetch(
        """
        SELECT team_abbr, opponent_abbr, game_id, game_date, games_played,
               pts_for_l10, pts_against_l10, pts_for_season, pts_against_season
        FROM team_features
        WHERE game_date = $1 AND is_home = TRUE
        ORDER BY team_abbr
        """,
        game_date,
    )
    away_rows = await pool.fetch(
        """
        SELECT team_abbr, game_id, games_played,
               pts_for_l10, pts_against_l10, pts_for_season, pts_against_season
        FROM team_features
        WHERE game_date = $1 AND is_home = FALSE
        """,
        game_date,
    )
    away_by_team = {r["team_abbr"]: dict(r) for r in away_rows}

    projections: list[GameProjection] = []
    for hr in home_rows:
        away = away_by_team.get(hr["opponent_abbr"])
        if away is None:
            continue
        proj = project_game(
            home=dict(hr),
            away=away,
            league_avg=league_avg,
            home_edge=home_edge,
            game_id=hr["game_id"],
            game_date=game_date,
        )
        if proj is not None:
            projections.append(proj)
        if limit is not None and len(projections) >= limit:
            break
    return projections


async def project_range(
    *, game_date: date | None = None, since: date | None = None, limit: int | None = None
) -> list[GameProjection]:
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    try:
        if game_date is not None:
            dates = [game_date]
        elif since is not None:
            rows = await pool.fetch(
                "SELECT DISTINCT game_date FROM team_features WHERE game_date >= $1 ORDER BY game_date",
                since,
            )
            dates = [r["game_date"] for r in rows]
        else:
            raise ValueError("project_range needs game_date or since")

        out: list[GameProjection] = []
        for d in dates:
            out.extend(await project_date(pool, d, limit=limit))
            if limit is not None and len(out) >= limit:
                out = out[:limit]
                break
        log.info("game_projections", dates=len(dates), projections=len(out))
        return out
    finally:
        await close_pool()


def _main() -> None:
    p = argparse.ArgumentParser(description="Project NBA game totals / margins.")
    p.add_argument("--date", dest="game_date", type=date.fromisoformat, default=None)
    p.add_argument("--since", type=date.fromisoformat, default=None)
    p.add_argument("--limit", type=int, default=None)
    a = p.parse_args()
    if a.game_date is None and a.since is None:
        a.game_date = date.today()
    projs = asyncio.run(project_range(game_date=a.game_date, since=a.since, limit=a.limit))
    print(f"\nNBA GAME PROJECTIONS  ({len(projs)} games)")
    print("  " + "-" * 70)
    print(f"  {'date':10s} {'matchup':13s} {'proj_total':>10s} {'home_spread':>12s}  exp(H/A)")
    for g in projs:
        print(
            f"  {g.game_date.isoformat():10s} "
            f"{g.away_abbr}@{g.home_abbr:9s} "
            f"{g.projected_total:10.1f} {g.fair_home_spread:+12.1f}  "
            f"{g.exp_home:.1f}/{g.exp_away:.1f}"
        )


if __name__ == "__main__":
    _main()
