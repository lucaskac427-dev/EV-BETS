"""Repository for nba_api cache tables: player_game_logs, team_defense_ratings,
league_averages."""

from dataclasses import dataclass
from datetime import date, datetime as _dt
from decimal import Decimal
from typing import Any

import asyncpg


@dataclass(frozen=True, slots=True)
class GameLog:
    player_id: int
    player_name: str
    team_abbr: str
    game_date: date
    minutes: float | None
    points: int | None
    rebounds: int | None
    assists: int | None
    threes: int | None
    blocks: int | None
    steals: int | None


async def upsert_game_logs(pool: asyncpg.Pool, rows: list[dict[str, Any]]) -> int:
    """Insert game-log rows, ignoring duplicates by (player_id, game_id)."""
    if not rows:
        return 0
    def _to_date(v) -> date:
        if isinstance(v, date):
            return v
        return _dt.strptime(str(v)[:10], "%Y-%m-%d").date()

    records = [
        (
            r["player_id"], r["player_name"], r["team_abbr"], r["game_id"],
            _to_date(r["game_date"]), r["matchup"], r["minutes"], r["points"],
            r["rebounds"], r["assists"], r["threes"], r["blocks"], r["steals"],
        )
        for r in rows
    ]
    await pool.executemany(
        """
        INSERT INTO player_game_logs (
            player_id, player_name, team_abbr, game_id, game_date, matchup,
            minutes, points, rebounds, assists, threes, blocks, steals
        )
        VALUES ($1,$2,$3,$4,$5::date,$6,$7,$8,$9,$10,$11,$12,$13)
        ON CONFLICT (player_id, game_id) DO NOTHING
        """,
        records,
    )
    return len(records)


async def recent_logs_for_player(
    pool: asyncpg.Pool, player_id: int, limit: int = 20
) -> list[GameLog]:
    """Most recent N game logs for a player, newest first."""
    rows = await pool.fetch(
        """
        SELECT player_id, player_name, team_abbr, game_date,
               minutes, points, rebounds, assists, threes, blocks, steals
        FROM player_game_logs
        WHERE player_id = $1
        ORDER BY game_date DESC
        LIMIT $2
        """,
        player_id, limit,
    )
    return [GameLog(**dict(r)) for r in rows]


async def player_id_by_name(pool: asyncpg.Pool, player_name: str) -> int | None:
    """Resolve a player_id from the most recent log with this exact name."""
    row = await pool.fetchrow(
        "SELECT player_id FROM player_game_logs WHERE player_name = $1 "
        "ORDER BY game_date DESC LIMIT 1",
        player_name,
    )
    return int(row["player_id"]) if row else None


async def upsert_team_defense(pool: asyncpg.Pool, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    for r in rows:
        await pool.execute(
            """
            INSERT INTO team_defense_ratings (team_abbr, def_rating, pace, opp_pts_per_game)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (team_abbr) DO UPDATE SET
                def_rating = EXCLUDED.def_rating,
                pace = EXCLUDED.pace,
                opp_pts_per_game = EXCLUDED.opp_pts_per_game,
                refreshed_at = now()
            """,
            r["team_abbr"], r["def_rating"], r["pace"], r["opp_pts_per_game"],
        )
    return len(rows)


async def team_defense(pool: asyncpg.Pool, team_abbr: str) -> dict[str, float] | None:
    row = await pool.fetchrow(
        "SELECT def_rating, pace, opp_pts_per_game FROM team_defense_ratings WHERE team_abbr = $1",
        team_abbr,
    )
    if not row:
        return None
    return {
        "def_rating": float(row["def_rating"]),
        "pace": float(row["pace"]),
        "opp_pts_per_game": float(row["opp_pts_per_game"]),
    }


async def upsert_league_averages(
    pool: asyncpg.Pool, *, season: str, avg_def_rating: float, avg_pace: float
) -> None:
    await pool.execute(
        """
        INSERT INTO league_averages (season, avg_def_rating, avg_pace)
        VALUES ($1, $2, $3)
        ON CONFLICT (season) DO UPDATE SET
            avg_def_rating = EXCLUDED.avg_def_rating,
            avg_pace = EXCLUDED.avg_pace,
            refreshed_at = now()
        """,
        season, avg_def_rating, avg_pace,
    )


async def league_averages(pool: asyncpg.Pool, season: str) -> dict[str, float] | None:
    row = await pool.fetchrow(
        "SELECT avg_def_rating, avg_pace FROM league_averages WHERE season = $1",
        season,
    )
    if not row:
        return None
    return {"avg_def_rating": float(row["avg_def_rating"]), "avg_pace": float(row["avg_pace"])}
