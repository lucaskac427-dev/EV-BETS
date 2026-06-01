"""WNBA outcomes warehouse — per-player per-game box scores via nba_api.

Same library we use for the NBA, with league_id "10" (WNBA) and a SINGLE
4-digit-year season ("2024", NOT "2024-25" — the #1 WNBA gotcha). One call per
(season, season_type) returns every player-game row: points / rebounds /
assists / threes / minutes. This is the OUTCOMES source that grades WNBA DFS
picks and backtests the consensus edge (backtest reads `wnba_game_logs`).

Idempotent upsert keyed on (player_id, game_id) — re-running is safe/resumable.

    python -m src.wnba_stats.ingest                       # current season only
    python -m src.wnba_stats.ingest --backfill 2023 2026  # all seasons + playoffs
"""

import argparse
import asyncio
import time
from datetime import date
from typing import Any

from nba_api.stats.endpoints import PlayerGameLogs
from tenacity import retry, stop_after_attempt, wait_exponential

from src.db import close_pool, get_pool
from src.logger import configure_logging, log

WNBA_LEAGUE_ID = "10"
CURRENT_SEASON = 2026

_CREATE = """
CREATE TABLE IF NOT EXISTS wnba_game_logs (
    player_id   INTEGER NOT NULL,
    player_name TEXT NOT NULL,
    team_abbr   TEXT,
    game_id     TEXT NOT NULL,
    game_date   DATE NOT NULL,
    matchup     TEXT,
    minutes     REAL,
    points      INTEGER,
    rebounds    INTEGER,
    assists     INTEGER,
    threes      INTEGER,
    blocks      INTEGER,
    steals      INTEGER,
    PRIMARY KEY (player_id, game_id)
);
CREATE INDEX IF NOT EXISTS wnba_game_logs_name_date ON wnba_game_logs (player_name, game_date);
"""

_COLS = [
    "player_id", "player_name", "team_abbr", "game_id", "game_date", "matchup",
    "minutes", "points", "rebounds", "assists", "threes", "blocks", "steals",
]

_UPSERT = (
    f"INSERT INTO wnba_game_logs ({', '.join(_COLS)}) "
    f"VALUES ({', '.join('$' + str(i + 1) for i in range(len(_COLS)))}) "
    f"ON CONFLICT (player_id, game_id) DO UPDATE SET "
    + ", ".join(f"{c}=EXCLUDED.{c}" for c in _COLS if c not in ("player_id", "game_id"))
)


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


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=12))
def fetch_wnba_logs(season: str, season_type: str = "Regular Season") -> list[dict[str, Any]]:
    """Every WNBA player game-log row for a 4-digit-year season (league 10)."""
    df = PlayerGameLogs(
        league_id_nullable=WNBA_LEAGUE_ID,
        season_nullable=season,
        season_type_nullable=season_type,
    ).get_data_frames()[0]
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        rows.append({
            "player_id": int(r["PLAYER_ID"]),
            "player_name": str(r["PLAYER_NAME"]),
            "team_abbr": str(r["TEAM_ABBREVIATION"]),
            "game_id": str(r["GAME_ID"]),
            "game_date": date.fromisoformat(str(r["GAME_DATE"])[:10]),
            "matchup": str(r["MATCHUP"]),
            "minutes": _num(r.get("MIN")),
            "points": _int(r.get("PTS")),
            "rebounds": _int(r.get("REB")),
            "assists": _int(r.get("AST")),
            "threes": _int(r.get("FG3M")),
            "blocks": _int(r.get("BLK")),
            "steals": _int(r.get("STL")),
        })
    log.info("wnba_logs_fetched", count=len(rows), season=season, type=season_type)
    return rows


async def _upsert(pool, rows: list[dict]) -> int:
    if not rows:
        return 0
    async with pool.acquire() as con:
        await con.executemany(_UPSERT, [[r[c] for c in _COLS] for r in rows])
    return len(rows)


async def backfill(start_year: int, end_year: int, *, throttle: float = 1.5) -> int:
    """Ingest every WNBA player-game (regular season + playoffs) for the year
    range. stats.nba.com rate-limits hard, so we pace between calls."""
    configure_logging(level="WARNING")
    pool = await get_pool()
    try:
        for stmt in _CREATE.strip().split(";"):
            if stmt.strip():
                await pool.execute(stmt)
        total = 0
        for year in range(start_year, end_year + 1):
            for stype in ("Regular Season", "Playoffs"):
                try:
                    rows = await asyncio.to_thread(fetch_wnba_logs, str(year), stype)
                    n = await _upsert(pool, rows)
                    total += n
                    if n:
                        log.warning("wnba_ingested", season=year, type=stype, rows=n, cumulative=total)
                except Exception as e:
                    log.warning("wnba_season_failed", season=year, type=stype, error=str(e)[:120])
                time.sleep(throttle)
        print(f"wnba backfill {start_year}..{end_year}: {total} player-game rows ingested")
        return total
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--backfill", nargs=2, type=int, metavar=("START", "END"),
                   help="Backfill WNBA seasons START..END (4-digit years, inclusive)")
    p.add_argument("--throttle", type=float, default=1.5)
    a = p.parse_args()
    if a.backfill:
        asyncio.run(backfill(a.backfill[0], a.backfill[1], throttle=a.throttle))
    else:
        asyncio.run(backfill(CURRENT_SEASON, CURRENT_SEASON, throttle=a.throttle))
