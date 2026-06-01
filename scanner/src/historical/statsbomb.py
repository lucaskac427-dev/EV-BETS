"""StatsBomb open-data ingest.

StatsBomb publishes event-level data for select competitions as static JSON
on GitHub (https://github.com/statsbomb/open-data). No auth, ~hundreds of MB
total. We pull match-by-match event JSON, aggregate per-player per-match
counting stats, and persist to soccer_player_match_stats.

Run:
    python -m src.historical.statsbomb --competition "FIFA World Cup" --season "2022"
    python -m src.historical.statsbomb --competition "UEFA Euro" --season "2024"
    python -m src.historical.statsbomb --competition "Major League Soccer" --season "2023"

Use --list to see all (competition, season) pairs available.
"""

import argparse
import asyncio
from collections import defaultdict
from datetime import date, datetime
from typing import Any

import httpx

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.providers._player_props import _normalize_name

SB_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"


async def _fetch_json(client: httpx.AsyncClient, path: str) -> Any:
    r = await client.get(f"{SB_BASE}/{path}")
    r.raise_for_status()
    return r.json()


async def list_competitions(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    return await _fetch_json(client, "competitions.json")


async def find_competition(
    client: httpx.AsyncClient, name: str, season: str
) -> dict[str, Any] | None:
    comps = await list_competitions(client)
    for c in comps:
        if (
            c.get("competition_name", "").lower() == name.lower()
            and c.get("season_name") == season
        ):
            return c
    return None


def _aggregate_match_events(
    events: list[dict], match_meta: dict[str, Any]
) -> list[dict[str, Any]]:
    """Walk all events, accumulate per-player counting stats. Returns one row
    per player who touched the ball, ready for upsert."""
    # Player + team
    player_team: dict[int, str] = {}
    player_name: dict[int, str] = {}
    player_position: dict[int, str | None] = {}
    minutes_at_event: dict[int, int] = defaultdict(int)
    first_event_min: dict[int, int] = {}
    last_event_min: dict[int, int] = {}

    counts: dict[int, dict[str, float]] = defaultdict(
        lambda: {
            "shots": 0,
            "shots_on_target": 0,
            "goals": 0,
            "assists": 0,
            "xg": 0.0,
            "xa": 0.0,
            "tackles": 0,
            "fouls_committed": 0,
            "fouls_won": 0,
            "passes_attempted": 0,
            "passes_completed": 0,
            "dribbles_attempted": 0,
            "dribbles_completed": 0,
        }
    )

    for e in events:
        player = e.get("player") or {}
        pid = player.get("id")
        if pid is None:
            continue
        team = (e.get("team") or {}).get("name")
        if team:
            player_team[pid] = team
        if "name" in player:
            player_name[pid] = player["name"]
        pos = (e.get("position") or {}).get("name")
        if pos and pid not in player_position:
            player_position[pid] = pos

        minute = e.get("minute") or 0
        if pid not in first_event_min:
            first_event_min[pid] = minute
        last_event_min[pid] = minute

        et = (e.get("type") or {}).get("name")
        if et == "Shot":
            counts[pid]["shots"] += 1
            shot = e.get("shot") or {}
            outcome = (shot.get("outcome") or {}).get("name")
            # Shots on target: anything that hit the keeper / scored
            if outcome in ("Saved", "Goal", "Saved To Post"):
                counts[pid]["shots_on_target"] += 1
            if outcome == "Goal":
                counts[pid]["goals"] += 1
            xg_val = shot.get("statsbomb_xg")
            if xg_val is not None:
                counts[pid]["xg"] += float(xg_val)
            # Assist credit: shot.key_pass_id -> previous Pass.assisted_shot_id
            # tracking handled via the Pass event below.
        elif et == "Pass":
            counts[pid]["passes_attempted"] += 1
            p = e.get("pass") or {}
            if not p.get("outcome"):
                counts[pid]["passes_completed"] += 1
            # Assists: if this pass is the goal_assist
            if p.get("goal_assist"):
                counts[pid]["assists"] += 1
        elif et == "Duel":
            duel = (e.get("duel") or {}).get("type") or {}
            if duel.get("name") == "Tackle":
                counts[pid]["tackles"] += 1
        elif et == "Foul Committed":
            counts[pid]["fouls_committed"] += 1
        elif et == "Foul Won":
            counts[pid]["fouls_won"] += 1
        elif et == "Dribble":
            counts[pid]["dribbles_attempted"] += 1
            if ((e.get("dribble") or {}).get("outcome") or {}).get("name") == "Complete":
                counts[pid]["dribbles_completed"] += 1

    rows: list[dict[str, Any]] = []
    for pid, stats in counts.items():
        # Rough minutes played = (last_event_min - first_event_min). Capped 90.
        mins = max(
            0,
            min(120, last_event_min.get(pid, 0) - first_event_min.get(pid, 0)),
        )
        rows.append(
            {
                "player_id": pid,
                "player_name": player_name.get(pid, ""),
                "team_name": player_team.get(pid, ""),
                "position": player_position.get(pid),
                "minutes_played": mins,
                **{k: int(v) if k not in ("xg", "xa") else v for k, v in stats.items()},
                **match_meta,
            }
        )
    return rows


async def ingest_competition(
    competition_name: str, season_name: str
) -> int:
    """Ingest every match in a (competition, season) into the priors table."""
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    n_rows = 0
    n_matches = 0
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            comp = await find_competition(client, competition_name, season_name)
            if not comp:
                log.warning(
                    "statsbomb_competition_not_found",
                    competition=competition_name,
                    season=season_name,
                )
                return 0

            cid = comp["competition_id"]
            sid = comp["season_id"]
            matches = await _fetch_json(client, f"matches/{cid}/{sid}.json")
            log.info(
                "statsbomb_competition_loaded",
                competition=competition_name,
                season=season_name,
                matches=len(matches),
            )

            for m in matches:
                match_id = m.get("match_id")
                if match_id is None:
                    continue
                try:
                    events = await _fetch_json(client, f"events/{match_id}.json")
                except Exception as e:
                    log.warning(
                        "statsbomb_events_fetch_failed",
                        match_id=match_id,
                        error=str(e),
                    )
                    continue

                match_date_str = m.get("match_date")
                try:
                    match_date = (
                        datetime.fromisoformat(match_date_str).date()
                        if match_date_str
                        else date.today()
                    )
                except ValueError:
                    match_date = date.today()

                meta = {
                    "source": "statsbomb",
                    "competition_name": competition_name,
                    "season_name": season_name,
                    "match_id": int(match_id),
                    "match_date": match_date,
                    "home_team": (m.get("home_team") or {}).get("home_team_name", ""),
                    "away_team": (m.get("away_team") or {}).get("away_team_name", ""),
                }
                rows = _aggregate_match_events(events, meta)
                for r in rows:
                    await _upsert_row(pool, r)
                    n_rows += 1
                n_matches += 1
                if n_matches % 10 == 0:
                    log.info(
                        "statsbomb_progress",
                        matches_done=n_matches,
                        rows_written=n_rows,
                    )

        log.info(
            "statsbomb_ingest_complete",
            competition=competition_name,
            season=season_name,
            matches=n_matches,
            rows=n_rows,
        )
    finally:
        await close_pool()
    return n_rows


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
            xg = EXCLUDED.xg,
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


async def list_available() -> None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        comps = await list_competitions(client)
    by = defaultdict(list)
    for c in comps:
        by[c["competition_name"]].append(c["season_name"])
    for name in sorted(by):
        print(f"  {name}")
        for s in sorted(by[name]):
            print(f"    - {s}")


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--competition", help="Competition name (case-insensitive)")
    parser.add_argument("--season", help="Season name e.g. '2022' or '2023/2024'")
    parser.add_argument("--list", action="store_true", help="List available pairs")
    args = parser.parse_args()
    if args.list:
        asyncio.run(list_available())
        return
    if not args.competition or not args.season:
        parser.error("--competition and --season required (or use --list)")
    asyncio.run(ingest_competition(args.competition, args.season))


if __name__ == "__main__":
    _main()
