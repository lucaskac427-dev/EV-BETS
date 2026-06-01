"""The Odds API historical-odds ingest.

The historical addon adds:
  GET /v4/historical/sports/{sport}/events?date=ISO8601
  GET /v4/historical/sports/{sport}/events/{event_id}/odds?date=ISO8601

Each request returns the snapshot of odds nearest the given date. Snapshots
are typically every ~10 minutes back to 2020 for most sports.

Cost: a request counts as `markets × regions` against your historical quota,
which is separate from the live quota. The addon is +$30/mo on top of the
standard plan; you'll get a separate historical API endpoint base.

This module is designed to no-op gracefully when settings.odds_api_historical
isn't set — that's the flag that says "you've upgraded and have a historical
key now."

Run:
    python -m src.historical.odds_api_history \\
        --sport basketball_nba \\
        --from 2025-04-15T00:00:00Z \\
        --to   2025-04-20T00:00:00Z \\
        --markets player_points,player_rebounds,player_assists
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.providers._player_props import _normalize_name


HISTORICAL_BASE = "https://api.the-odds-api.com/v4/historical"


async def _get_with_retry(
    client: httpx.AsyncClient, url: str, params: dict, attempts: int = 5
) -> httpx.Response:
    """GET that survives transient DNS/network blips + 429s — a long backfill
    must not be wiped by one bad moment on the wire."""
    delay = 1.0
    for i in range(attempts):
        try:
            r = await client.get(url, params=params)
        except httpx.RequestError:
            if i == attempts - 1:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, 20.0)
            continue
        if r.status_code == 429:
            await asyncio.sleep(delay)
            delay = min(delay * 2, 20.0)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError("retries exhausted")


async def _list_events(
    client: httpx.AsyncClient, sport: str, snapshot_at: str
) -> list[dict[str, Any]]:
    r = await _get_with_retry(
        client,
        f"{HISTORICAL_BASE}/sports/{sport}/events",
        {"apiKey": settings.odds_api_key, "date": snapshot_at},
    )
    payload = r.json()
    # Historical endpoints wrap the body in { timestamp, previous_timestamp,
    # next_timestamp, data: [...] }.
    return payload.get("data", payload)


async def _get_event_odds(
    client: httpx.AsyncClient,
    sport: str,
    event_id: str,
    snapshot_at: str,
    markets: str,
    regions: str = "us",
) -> dict[str, Any]:
    r = await _get_with_retry(
        client,
        f"{HISTORICAL_BASE}/sports/{sport}/events/{event_id}/odds",
        {
            "apiKey": settings.odds_api_key,
            "date": snapshot_at,
            "regions": regions,
            "markets": markets,
            "oddsFormat": "american",
        },
    )
    return r.json().get("data", r.json())


def _decimal_odds_from_american(american: int) -> float:
    if american > 0:
        return american / 100.0 + 1.0
    return 100.0 / abs(american) + 1.0


async def _upsert_outcome(
    pool,
    *,
    sport: str,
    event_id: str,
    event_start: datetime,
    home_team: str | None,
    away_team: str | None,
    snapshot_at: datetime,
    book: str,
    market_key: str,
    player_name: str | None,
    line: float | None,
    side: str,
    american: int,
) -> None:
    decimal = _decimal_odds_from_american(american)
    slug = _normalize_name(player_name) if player_name else None
    await pool.execute(
        """
        INSERT INTO historical_odds_snapshots (
            source, sport_key, event_id, event_start, home_team, away_team,
            snapshot_at, book, market_key, player_name, player_slug, line,
            side, american_odds, decimal_odds
        )
        VALUES ('odds_api_historical', $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
        """,
        sport, event_id, event_start, home_team, away_team, snapshot_at,
        book, market_key, player_name, slug, line, side, american, decimal,
    )


async def ingest_window(
    sport: str,
    *,
    from_dt: datetime,
    to_dt: datetime,
    markets: list[str],
    interval_minutes: int = 60,
    regions: str = "us",
) -> int:
    if not settings.odds_api_key:
        log.warning("odds_api_key_missing")
        return 0

    pool = await get_pool()
    n_written = 0
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            cursor = from_dt
            step = timedelta(minutes=interval_minutes)
            markets_csv = ",".join(markets)
            while cursor <= to_dt:
                ts = cursor.isoformat().replace("+00:00", "Z")
                try:
                    events = await _list_events(client, sport, ts)
                except Exception as e:
                    log.warning(
                        "historical_events_failed",
                        sport=sport,
                        snapshot=ts,
                        error=str(e),
                    )
                    cursor += step
                    continue

                for event in events:
                    event_id = event.get("id")
                    if not event_id:
                        continue
                    try:
                        payload = await _get_event_odds(
                            client, sport, event_id, ts, markets_csv, regions
                        )
                    except Exception as e:
                        log.warning(
                            "historical_event_odds_failed",
                            sport=sport,
                            event_id=event_id,
                            snapshot=ts,
                            error=str(e),
                        )
                        continue

                    try:
                        event_start = datetime.fromisoformat(
                            (event.get("commence_time") or "").replace("Z", "+00:00")
                        )
                    except ValueError:
                        event_start = cursor

                    for bm in payload.get("bookmakers", []):
                        book = bm.get("key")
                        if not book:
                            continue
                        for market in bm.get("markets", []):
                            market_key = market.get("key", "")
                            for outcome in market.get("outcomes", []):
                                side = (outcome.get("name") or "").lower()
                                price = outcome.get("price")
                                if price is None:
                                    continue
                                await _upsert_outcome(
                                    pool,
                                    sport=sport,
                                    event_id=event_id,
                                    event_start=event_start,
                                    home_team=event.get("home_team"),
                                    away_team=event.get("away_team"),
                                    snapshot_at=cursor,
                                    book=book,
                                    market_key=market_key,
                                    player_name=outcome.get("description"),
                                    line=outcome.get("point"),
                                    side=side,
                                    american=int(price),
                                )
                                n_written += 1
                log.info(
                    "historical_snapshot_done",
                    sport=sport,
                    snapshot=ts,
                    rows=n_written,
                )
                cursor += step
    finally:
        await close_pool()

    log.info(
        "historical_ingest_complete",
        sport=sport,
        from_dt=str(from_dt),
        to_dt=str(to_dt),
        rows=n_written,
    )
    return n_written


async def ingest_closing_lines(
    sport: str,
    *,
    from_dt: datetime,
    to_dt: datetime,
    markets: list[str],
    regions: str = "us",
    minutes_before: int = 10,
    skip_book: str | None = None,
) -> int:
    """Credit-efficient backfill: ONE snapshot per game, taken ~minutes_before
    tip (the closing line — what you'd actually bet). Enumerates events day by
    day, then pulls each event's odds once. Resumable: events already present
    in historical_odds_snapshots are skipped, so an interrupted run continues
    where it left off. ~markets×regions×10 credits per game (historical pricing)."""
    if not settings.odds_api_key:
        log.warning("odds_api_key_missing")
        return 0

    pool = await get_pool()
    n_written = 0
    markets_csv = ",".join(markets)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1) Enumerate events CONCURRENTLY (one list call per day, 8-way).
            sem_enum = asyncio.Semaphore(8)

            async def _enum_day(d: datetime) -> list:
                ts = d.isoformat().replace("+00:00", "Z")
                async with sem_enum:
                    try:
                        return await _list_events(client, sport, ts)
                    except Exception as e:
                        log.warning("closing_events_failed", sport=sport, snapshot=ts, error=str(e))
                        return []

            days: list[datetime] = []
            d = from_dt
            while d <= to_dt:
                days.append(d)
                d += timedelta(days=1)
            seen: dict[str, tuple[datetime, dict]] = {}
            for evlist in await asyncio.gather(*[_enum_day(x) for x in days]):
                for e in evlist:
                    eid, ct = e.get("id"), e.get("commence_time")
                    if not eid or not ct:
                        continue
                    cdt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                    if from_dt <= cdt <= to_dt + timedelta(days=1):
                        seen[eid] = (cdt, e)
            log.info("closing_events_enumerated", sport=sport, games=len(seen))

            # 2) One closing snapshot per game — fetched CONCURRENTLY (8-way).
            sem = asyncio.Semaphore(8)
            progress = {"n": 0}

            async def _fetch_one(eid: str, cdt: datetime, e: dict) -> int:
                async with sem:
                    # Resumable: skip only if we already have the requested markets.
                    # Resumable. When ADDING a new book (e.g. Pinnacle via a new
                    # region) skip on THAT book's presence, not the market's —
                    # otherwise every game looks "done" from the earlier US fetch.
                    if skip_book:
                        exists = await pool.fetchval(
                            "SELECT 1 FROM historical_odds_snapshots WHERE event_id=$1 AND book=$2 LIMIT 1",
                            eid, skip_book,
                        )
                    else:
                        exists = await pool.fetchval(
                            "SELECT 1 FROM historical_odds_snapshots "
                            "WHERE event_id=$1 AND market_key = ANY($2::text[]) LIMIT 1",
                            eid, markets,
                        )
                    if exists:
                        return 0
                    snap = (cdt - timedelta(minutes=minutes_before)).isoformat().replace("+00:00", "Z")
                    try:
                        payload = await _get_event_odds(client, sport, eid, snap, markets_csv, regions)
                    except Exception as ex:
                        log.warning("closing_odds_failed", sport=sport, event_id=eid, error=str(ex))
                        return 0
                    rows = 0
                    for bm in payload.get("bookmakers", []):
                        book = bm.get("key")
                        if not book:
                            continue
                        for market in bm.get("markets", []):
                            mk = market.get("key", "")
                            for outcome in market.get("outcomes", []):
                                price = outcome.get("price")
                                if price is None:
                                    continue
                                await _upsert_outcome(
                                    pool, sport=sport, event_id=eid, event_start=cdt,
                                    home_team=e.get("home_team"), away_team=e.get("away_team"),
                                    snapshot_at=cdt, book=book, market_key=mk,
                                    player_name=outcome.get("description"), line=outcome.get("point"),
                                    side=(outcome.get("name") or "").lower(), american=int(price),
                                )
                                rows += 1
                    progress["n"] += 1
                    if progress["n"] % 100 == 0:
                        log.info("closing_progress", sport=sport, games_done=progress["n"], total=len(seen))
                    return rows

            results = await asyncio.gather(
                *[_fetch_one(eid, cdt, e) for eid, (cdt, e) in seen.items()]
            )
            n_written = sum(results)
    finally:
        await close_pool()
    log.info("closing_ingest_complete", sport=sport, rows=n_written)
    return n_written


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True, help="e.g. basketball_nba, soccer_epl")
    parser.add_argument("--from", dest="from_", required=True, help="ISO8601 start")
    parser.add_argument("--to", dest="to_", required=True, help="ISO8601 end")
    parser.add_argument(
        "--markets",
        default="h2h,totals",
        help="Comma-separated market keys",
    )
    parser.add_argument("--interval-minutes", type=int, default=60)
    parser.add_argument("--regions", default="us")
    parser.add_argument("--skip-book", default=None,
                        help="When adding a new book, skip games that already have it (resumable)")
    parser.add_argument(
        "--closing",
        action="store_true",
        help="Efficient mode: one closing snapshot per game (resumable). Best for "
        "season backfills — skips the wasteful hourly sweep.",
    )
    args = parser.parse_args()

    configure_logging(level=settings.log_level)
    if args.closing:
        asyncio.run(
            ingest_closing_lines(
                args.sport,
                from_dt=_parse_iso(args.from_),
                to_dt=_parse_iso(args.to_),
                markets=args.markets.split(","),
                regions=args.regions,
                skip_book=args.skip_book,
            )
        )
    else:
        asyncio.run(
            ingest_window(
                args.sport,
                from_dt=_parse_iso(args.from_),
                to_dt=_parse_iso(args.to_),
                markets=args.markets.split(","),
                interval_minutes=args.interval_minutes,
                regions=args.regions,
            )
        )


if __name__ == "__main__":
    _main()
