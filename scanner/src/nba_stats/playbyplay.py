"""NBA play-by-play ingest — the granular event layer under the projection models.

Every shot, rebound, assist, foul, sub — with court coordinates and the running
score — for every game. This is the raw material SofaScore/Action surface, free
from the NBA's own stats feed (nba_api). From it we derive the features that make
a from-scratch projection model sharp: usage rate, shot quality (from x/y), pace,
on/off splits, matchup difficulty, fatigue, clutch splits.

Run:
    python -m src.nba_stats.playbyplay --from-season 2023 --to-season 2026
    python -m src.nba_stats.playbyplay --game 0042500316     # one game
"""

from __future__ import annotations

import argparse
import asyncio

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log

_CREATE = """
CREATE TABLE IF NOT EXISTS pbp_events (
    game_id        TEXT NOT NULL,
    action_number  INT  NOT NULL,
    period         INT,
    clock          TEXT,
    team_id        BIGINT,
    team_tricode   TEXT,
    person_id      BIGINT,
    player_name    TEXT,
    action_type    TEXT,
    sub_type       TEXT,
    description    TEXT,
    x_legacy       INT,
    y_legacy       INT,
    shot_distance  NUMERIC,
    shot_result    TEXT,
    score_home     INT,
    score_away     INT,
    PRIMARY KEY (game_id, action_number)
);
"""


def _fetch_pbp(game_id: str):
    """Blocking nba_api call — run via asyncio.to_thread."""
    from nba_api.stats.endpoints import playbyplayv3

    return playbyplayv3.PlayByPlayV3(game_id=game_id).get_data_frames()[0]


def _i(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


async def ingest_pbp(pool, game_ids: list[str], *, concurrency: int = 3) -> int:
    await pool.execute(_CREATE)
    sem = asyncio.Semaphore(concurrency)
    progress = {"done": 0, "rows": 0}

    async def _one(gid: str) -> int:
        async with sem:
            exists = await pool.fetchval(
                "SELECT 1 FROM pbp_events WHERE game_id=$1 LIMIT 1", gid
            )
            if exists:
                return 0
            try:
                df = await asyncio.to_thread(_fetch_pbp, gid)
            except Exception as e:
                log.warning("pbp_fetch_failed", game_id=gid, error=str(e)[:120])
                return 0
            records = []
            for _, r in df.iterrows():
                records.append((
                    str(r.get("gameId") or gid), _i(r.get("actionNumber")),
                    _i(r.get("period")), str(r.get("clock") or ""),
                    _i(r.get("teamId")), str(r.get("teamTricode") or "") or None,
                    _i(r.get("personId")), str(r.get("playerName") or "") or None,
                    str(r.get("actionType") or "") or None,
                    str(r.get("subType") or "") or None,
                    str(r.get("description") or "") or None,
                    _i(r.get("xLegacy")), _i(r.get("yLegacy")),
                    float(r["shotDistance"]) if r.get("shotDistance") not in (None, "") else None,
                    str(r.get("shotResult") or "") or None,
                    _i(r.get("scoreHome")), _i(r.get("scoreAway")),
                ))
            if not records:
                return 0
            await pool.executemany(
                """INSERT INTO pbp_events (game_id, action_number, period, clock,
                     team_id, team_tricode, person_id, player_name, action_type,
                     sub_type, description, x_legacy, y_legacy, shot_distance,
                     shot_result, score_home, score_away)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
                   ON CONFLICT (game_id, action_number) DO NOTHING""",
                records,
            )
            progress["done"] += 1
            progress["rows"] += len(records)
            if progress["done"] % 50 == 0:
                log.info("pbp_progress", games=progress["done"], rows=progress["rows"])
            return len(records)

    results = await asyncio.gather(*[_one(g) for g in game_ids])
    log.info("pbp_ingest_complete", games_fetched=progress["done"], rows=sum(results))
    return sum(results)


async def _game_ids_for_seasons(pool, from_season: int, to_season: int) -> list[str]:
    rows = await pool.fetch(
        """SELECT DISTINCT game_id FROM player_game_logs
           WHERE game_id IS NOT NULL
             AND game_date >= make_date($1, 10, 1)
             AND game_date <  make_date($2 + 1, 7, 1)
           ORDER BY game_id""",
        from_season, to_season,
    )
    return [r["game_id"] for r in rows]


async def _main() -> None:
    configure_logging(level=settings.log_level)
    p = argparse.ArgumentParser()
    p.add_argument("--from-season", type=int, default=2023)
    p.add_argument("--to-season", type=int, default=2026)
    p.add_argument("--game", help="ingest a single game_id and exit")
    p.add_argument("--concurrency", type=int, default=3)
    a = p.parse_args()
    pool = await get_pool()
    try:
        if a.game:
            n = await ingest_pbp(pool, [a.game], concurrency=1)
            print(f"  {a.game}: {n} events ingested")
        else:
            gids = await _game_ids_for_seasons(pool, a.from_season, a.to_season)
            print(f"  {len(gids)} games {a.from_season}-{a.to_season} to ingest (resumable)…")
            n = await ingest_pbp(pool, gids, concurrency=a.concurrency)
            print(f"  done: {n} play-by-play events ingested")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
