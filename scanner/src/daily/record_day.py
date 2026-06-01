"""Daily warehouse recorder — bank every game's data, every day, forever.

This is the "become our own data" engine. Run daily (via cron), it captures the
last few days of completed games across sports and records the full picture:
box scores, play-by-play, and closing odds (props + game lines). Idempotent —
every underlying ingest is resumable, so re-running only fills gaps.

ARCHITECTURE NOTE: this module only BANKS raw data. It is the shared warehouse
that BOTH systems read from — the DFS edge engine (player props, consensus) and
the projection engine (game lines, models) — but it writes neither system's
outputs. Keeping ingestion separate from the two prediction systems is what lets
projections and DFS stay completely independent.

Run:
    python -m src.daily.record_day                 # last 3 days, all sports
    python -m src.daily.record_day --lookback 7
    python -m src.daily.record_day --sport nba
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log

NBA_PROP_MARKETS = (
    "player_points,player_rebounds,player_assists,player_threes,"
    "player_blocks,player_steals"
)
NBA_LINE_MARKETS = "h2h,totals,spreads"


async def record_nba(lookback_days: int) -> dict:
    """Box scores + play-by-play + closing odds for recently-completed NBA games."""
    from src.historical.odds_api_history import ingest_closing_lines
    from src.nba_stats.ingest import run_ingest
    from src.nba_stats.playbyplay import ingest_pbp

    out = {"box_scores": 0, "pbp_rows": 0, "odds_rows": 0}

    # 1) Box scores + team defense (current-season recency update).
    try:
        r = await run_ingest()  # manages its own pool
        out["box_scores"] = r.get("logs", 0)
    except Exception as e:
        log.warning("daily_boxscore_failed", error=str(e)[:160])

    # 2) Play-by-play for games played in the lookback window.
    pool = await get_pool()
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date()
        rows = await pool.fetch(
            """SELECT DISTINCT game_id FROM player_game_logs
               WHERE game_id IS NOT NULL AND game_date >= $1""",
            since,
        )
        out["pbp_rows"] = await ingest_pbp(pool, [r["game_id"] for r in rows])
    except Exception as e:
        log.warning("daily_pbp_failed", error=str(e)[:160])
    finally:
        await close_pool()

    # 3) Closing odds (props + game lines) for the lookback window.
    frm = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    to = datetime.now(timezone.utc) + timedelta(days=1)
    for markets in (NBA_PROP_MARKETS, NBA_LINE_MARKETS):
        try:
            out["odds_rows"] += await ingest_closing_lines(
                "basketball_nba", from_dt=frm, to_dt=to,
                markets=markets.split(","), regions="us",
            )
        except Exception as e:
            log.warning("daily_odds_failed", markets=markets, error=str(e)[:160])
    return out


async def record_soccer(lookback_days: int) -> dict:
    """Refresh the current soccer season's results + odds (football-data updates
    its season CSVs as games finish). Match-level for now; event/xG layers extend
    here as the soccer projection system grows."""
    import httpx

    from src.historical.footballdata import ingest_main

    out = {"matches": 0}
    pool = await get_pool()
    try:
        yr = await pool.fetchval("SELECT extract(year from now())::int")
        mo = await pool.fetchval("SELECT extract(month from now())::int")
        start_year = yr if mo >= 8 else yr - 1  # season spans Aug->May
        async with httpx.AsyncClient(timeout=30.0) as client:
            out["matches"] = await ingest_main(pool, client, start_year, start_year)
    except Exception as e:
        log.warning("daily_soccer_failed", error=str(e)[:160])
    finally:
        await close_pool()
    return out


async def record_sofascore(lookback_days: int) -> dict:
    """Multi-sport SofaScore feed: every sport's events + play-by-play/stats for
    finished games, going forward. The all-sports warehouse layer."""
    from datetime import date, timedelta

    from src.sofascore.ingest import backfill_details, ingest_range

    out: dict[str, int] = {}
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=lookback_days)
    sports = ("basketball", "football", "american-football", "ice-hockey", "baseball", "tennis")
    for sp in sports:
        try:
            s = await ingest_range(sp, start, today, concurrency=4)
            out[f"{sp}_events"] = s["upserted"]
        except Exception as e:
            log.warning("daily_sofascore_events_failed", sport=sp, error=str(e)[:140])
    # Play-by-play + stats for the most recent finished games (bounded per night).
    for sp in ("basketball", "football"):
        try:
            out[f"{sp}_pbp"] = await backfill_details(sp, limit=300, concurrency=3)
        except Exception as e:
            log.warning("daily_sofascore_pbp_failed", sport=sp, error=str(e)[:140])
    return out


async def run(sport: str, lookback_days: int) -> None:
    configure_logging(level=settings.log_level)
    log.info("daily_record_start", sport=sport, lookback_days=lookback_days)
    results: dict[str, dict] = {}
    if sport in ("all", "nba"):
        results["nba"] = await record_nba(lookback_days)
    if sport in ("all", "soccer"):
        results["soccer"] = await record_soccer(lookback_days)
    if sport in ("all", "sofascore"):
        results["sofascore"] = await record_sofascore(lookback_days)
    log.info("daily_record_complete", **{f"{k}_{kk}": vv
             for k, d in results.items() for kk, vv in d.items()})
    print(f"\n  DAILY WAREHOUSE RECORD · {datetime.now(timezone.utc).date()} · lookback {lookback_days}d")
    for sp, d in results.items():
        print(f"    {sp}: " + " · ".join(f"{k}={v}" for k, v in d.items()))


def _main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sport", default="all", choices=["all", "nba", "soccer", "sofascore"])
    p.add_argument("--lookback", type=int, default=3)
    a = p.parse_args()
    asyncio.run(run(a.sport, a.lookback))


if __name__ == "__main__":
    _main()
