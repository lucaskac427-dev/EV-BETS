"""FBref historical ingest via soccerdata.

Complements StatsBomb's cherry-picked tournament data with FBref's full-league
coverage. Pulls per-player per-match summary + defense + goalkeeping stats and
lands them in the same soccer_player_match_stats table.

The soccerdata.FBref class caches scraped HTML to ~/soccerdata locally so
re-runs are cheap.

Common leagues (soccerdata identifiers):
  ENG-Premier League, ESP-La Liga, ITA-Serie A, GER-Bundesliga,
  FRA-Ligue 1, USA-Major League Soccer, INT-World Cup, INT-European
  Championships, INT-FIFA Confederations Cup, ENG-Championship, etc.

Run:
    python -m src.historical.fbref --league "USA-Major League Soccer" --season 2024
    python -m src.historical.fbref --league "ENG-Premier League" --season 2024 2023
"""

import argparse
import asyncio
import math
from datetime import datetime, date
from typing import Any

import soccerdata as sd

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.providers._player_props import _normalize_name


def _clean(v: Any) -> int | None:
    """nan / None / '' → 0; numeric → int (counting stats)."""
    if v is None:
        return 0
    try:
        f = float(v)
        if math.isnan(f):
            return 0
        return int(f)
    except (TypeError, ValueError):
        return 0


def _safe_str(v: Any) -> str:
    return str(v) if v is not None else ""


def _to_date(v: Any) -> date:
    if isinstance(v, date):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        return datetime.fromisoformat(str(v)[:10]).date()
    except Exception:
        return date.today()


def fetch_fbref_match_stats(league: str, seasons: list[str]) -> list[dict[str, Any]]:
    """Return per-player per-match rows ready to upsert. Each row merges
    summary stats with defense + (when present) goalkeeping stats."""
    fb = sd.FBref(leagues=[league], seasons=seasons)

    log.info("fbref_fetch_start", league=league, seasons=seasons)
    summary = fb.read_player_match_stats(stat_type="summary").reset_index()
    defense = fb.read_player_match_stats(stat_type="defense").reset_index()
    log.info(
        "fbref_dataframes_loaded",
        summary_rows=len(summary),
        defense_rows=len(defense),
    )

    # Merge defense onto summary by (game, player). FBref columns are multi-index
    # but reset_index flattens them with underscore separators.
    join_keys = [c for c in ("game", "team", "player") if c in summary.columns]
    if not join_keys:
        log.warning("fbref_no_join_keys", columns=list(summary.columns)[:30])
        return []
    merged = summary.merge(defense, on=join_keys, how="left", suffixes=("", "_def"))

    rows: list[dict[str, Any]] = []
    for _, r in merged.iterrows():
        player_name = _safe_str(r.get("player"))
        if not player_name:
            continue
        team_name = _safe_str(r.get("team"))
        game_str = _safe_str(r.get("game"))
        # game format: "YYYY-MM-DD Home-Away"
        try:
            game_date = datetime.strptime(game_str[:10], "%Y-%m-%d").date()
        except Exception:
            game_date = date.today()
        home_team = away_team = ""
        if " " in game_str[10:]:
            matchup = game_str[10:].strip()
            parts = matchup.split("-", 1)
            if len(parts) == 2:
                home_team, away_team = parts[0].strip(), parts[1].strip()

        rows.append(
            {
                "source": "fbref",
                "competition_name": league,
                "season_name": _safe_str(r.get("season", "")) or seasons[0],
                # FBref doesn't have stable numeric match IDs across leagues,
                # so we synthesize one from (game, player) hashed to int.
                "match_id": abs(hash((game_str, team_name))) % (10**12),
                "match_date": game_date,
                "home_team": home_team,
                "away_team": away_team,
                "player_id": abs(hash(player_name)) % (10**12),
                "player_name": player_name,
                "team_name": team_name,
                "position": _safe_str(r.get("position", "")) or None,
                "minutes_played": _clean(r.get("min") or r.get("minutes")),
                "shots": _clean(r.get(("Performance", "Sh"))) or _clean(r.get("Sh")),
                "shots_on_target": _clean(r.get(("Performance", "SoT")))
                or _clean(r.get("SoT")),
                "goals": _clean(r.get(("Performance", "Gls"))) or _clean(r.get("Gls")),
                "assists": _clean(r.get(("Performance", "Ast")))
                or _clean(r.get("Ast")),
                "xg": None,
                "xa": None,
                "tackles": _clean(r.get(("Tackles", "Tkl")))
                or _clean(r.get("Tkl"))
                or _clean(r.get("Tkl_def")),
                "fouls_committed": _clean(r.get(("Performance", "Fls")))
                or _clean(r.get("Fls")),
                "fouls_won": _clean(r.get(("Performance", "Fld")))
                or _clean(r.get("Fld")),
                "passes_attempted": _clean(r.get(("Passes", "Att")))
                or _clean(r.get("PrgP"))
                or 0,
                "passes_completed": _clean(r.get(("Passes", "Cmp"))) or 0,
                "dribbles_attempted": _clean(r.get(("Take-Ons", "Att"))) or 0,
                "dribbles_completed": _clean(r.get(("Take-Ons", "Succ"))) or 0,
            }
        )
    log.info("fbref_rows_built", count=len(rows))
    return rows


async def _upsert_row(pool, r: dict[str, Any]) -> None:
    slug = _normalize_name(r["player_name"])
    await pool.execute(
        """
        INSERT INTO soccer_player_match_stats (
            source, competition_name, season_name, match_id, match_date,
            home_team, away_team, player_id, player_name, player_name_slug,
            team_name, position, minutes_played, shots, shots_on_target,
            goals, assists, xg, xa, tackles, fouls_committed, fouls_won,
            passes_attempted, passes_completed, dribbles_attempted,
            dribbles_completed
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,
                $18,$19,$20,$21,$22,$23,$24,$25,$26)
        ON CONFLICT (source, match_id, player_id) DO UPDATE SET
            minutes_played = EXCLUDED.minutes_played,
            shots = EXCLUDED.shots,
            shots_on_target = EXCLUDED.shots_on_target,
            goals = EXCLUDED.goals,
            assists = EXCLUDED.assists,
            tackles = EXCLUDED.tackles,
            fouls_committed = EXCLUDED.fouls_committed,
            fouls_won = EXCLUDED.fouls_won,
            passes_attempted = EXCLUDED.passes_attempted,
            passes_completed = EXCLUDED.passes_completed,
            dribbles_attempted = EXCLUDED.dribbles_attempted,
            dribbles_completed = EXCLUDED.dribbles_completed
        """,
        r["source"], r["competition_name"], r["season_name"], r["match_id"],
        r["match_date"], r["home_team"], r["away_team"], r["player_id"],
        r["player_name"], slug, r["team_name"], r.get("position"),
        r["minutes_played"], r["shots"], r["shots_on_target"], r["goals"],
        r["assists"], r.get("xg"), r.get("xa"), r["tackles"],
        r["fouls_committed"], r["fouls_won"], r["passes_attempted"],
        r["passes_completed"], r["dribbles_attempted"], r["dribbles_completed"],
    )


async def ingest_league(league: str, seasons: list[str]) -> int:
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    try:
        rows = await asyncio.to_thread(fetch_fbref_match_stats, league, seasons)
        for r in rows:
            await _upsert_row(pool, r)
        log.info(
            "fbref_ingest_complete",
            league=league,
            seasons=seasons,
            rows=len(rows),
        )
        return len(rows)
    finally:
        await close_pool()


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league", required=True, help="e.g. 'USA-Major League Soccer'")
    parser.add_argument(
        "--season",
        nargs="+",
        required=True,
        help="One or more season strings, e.g. 2024 or 2324",
    )
    args = parser.parse_args()
    asyncio.run(ingest_league(args.league, args.season))


if __name__ == "__main__":
    _main()
