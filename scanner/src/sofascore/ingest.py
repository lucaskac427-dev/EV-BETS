"""SofaScore multi-sport event warehouse feed.

SofaScore's unofficial public JSON API (api.sofascore.com) covers EVERY sport —
basketball, soccer ("football"), american-football, tennis, baseball, hockey,
etc. — behind one uniform shape: a per-day scheduled-events list, each event
carrying tournament, both teams, kickoff timestamp, status and live/final score.

This module banks that data into a single `sofascore_events` table keyed by the
SofaScore event id + sport. It starts with NBA (sport='basketball') but the same
`ingest_day(sport, date)` works for any SofaScore sport slug — to add soccer or
the NFL you just pass a different slug, no schema change.

WAREHOUSE ONLY. This is a raw historical data feed. It is deliberately decoupled
from the DFS edge / projection system: nothing here reads or writes the DFS
tables, and the edge pipeline does not depend on this. It exists so we can mine
SofaScore later (alternate score/stat source, cross-checks, new markets) without
re-scraping. Treat it as an append/upsert log of "what SofaScore said happened".

The endpoint is unofficial and aggressively bot-protected (edge layer returns a
JSON 403 to non-browser TLS clients). We are polite — real browser User-Agent,
small jittered delays, capped concurrency, retries with backoff on 403/429/5xx —
and the IPRoyal residential proxy is wired in optionally via
`settings.iproyal_proxy_url`. If SofaScore still hard-blocks (403/429) the run
logs the block cleanly and exits 0 rather than crashing.

Run:
    python -m src.sofascore.ingest --sport basketball --from 2025-12-01 --to 2025-12-10
    python -m src.sofascore.ingest --sport basketball --date 2025-12-10
    python -m src.sofascore.ingest --sport football --from 2025-12-01 --to 2025-12-03
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import tls_requests  # browser-TLS-impersonating client — beats SofaScore's JA3 bot wall

from src.config import settings
from src.db import close_pool, get_pool
from src.logger import configure_logging, log

API_BASE = "https://api.sofascore.com/api/v1"

# A normal desktop-Chrome fingerprint. SofaScore's edge rejects obvious bots, so
# present like a browser hitting its own API (the site fetches these same URLs).
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
}

_MAX_RETRIES = 4
_BACKOFF_BASE = 1.5  # seconds; exponential per attempt
_POLITE_MIN = 0.4  # min jittered delay between requests
_POLITE_MAX = 1.1


class SofaScoreError(Exception):
    """Base for SofaScore ingest failures."""


class SofaScoreBlocked(SofaScoreError):
    """SofaScore refused us (403/429) after exhausting retries — bot block."""


@dataclass(slots=True)
class _DayResult:
    """Outcome of one day's pull, so the CLI can summarise without exceptions."""

    fetched: int
    upserted: int
    blocked: bool


_CREATE = """
CREATE TABLE IF NOT EXISTS sofascore_events (
    sofascore_id     BIGINT      NOT NULL,
    sport            TEXT        NOT NULL,
    tournament       TEXT,
    season           TEXT,
    home_team        TEXT,
    away_team        TEXT,
    start_timestamp  TIMESTAMPTZ,
    status           TEXT,
    home_score       INT,
    away_score       INT,
    raw              JSONB       NOT NULL,
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (sofascore_id, sport)
);
CREATE INDEX IF NOT EXISTS sofascore_events_sport_day_idx
    ON sofascore_events (sport, start_timestamp);
"""


def _daterange(start: date, end: date) -> Iterator[date]:
    """Inclusive day iterator, start..end."""
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _final_score(node: dict | None) -> int | None:
    """Pull the settled score from a homeScore/awayScore node.

    SofaScore nests several period breakdowns; `current` is the running/final
    total. `display` is the same value pre-formatted. We take whichever exists.
    """
    if not node:
        return None
    for key in ("current", "display", "normaltime"):
        val = node.get(key)
        if isinstance(val, int):
            return val
    return None


def _parse_event(ev: dict) -> dict | None:
    """Flatten a SofaScore event node into our column set.

    Returns None for nodes missing an id (defensive — the API shape is uniform
    across sports but unofficial, so we never trust it blindly).
    """
    sid = ev.get("id")
    if not isinstance(sid, int):
        return None

    tournament = ev.get("tournament") or {}
    season = ev.get("season") or {}
    home = ev.get("homeTeam") or {}
    away = ev.get("awayTeam") or {}
    status = ev.get("status") or {}

    ts = ev.get("startTimestamp")
    start = datetime.fromtimestamp(ts).astimezone() if isinstance(ts, (int, float)) else None

    return {
        "sofascore_id": sid,
        "tournament": (tournament.get("uniqueTournament") or tournament).get("name"),
        "season": season.get("name") or season.get("year"),
        "home_team": home.get("name"),
        "away_team": away.get("name"),
        "start_timestamp": start,
        "status": status.get("description") or status.get("type"),
        "home_score": _final_score(ev.get("homeScore")),
        "away_score": _final_score(ev.get("awayScore")),
        "raw": ev,
    }


def _sync_get(url: str):
    """Blocking tls_requests GET with a real browser TLS fingerprint."""
    proxy = settings.iproyal_proxy_url or None
    return tls_requests.get(url, headers=_HEADERS, timeout=25, proxy=proxy)


async def _get_json(url: str) -> dict:
    """GET with retries + polite jitter. Raises SofaScoreBlocked on hard block.
    Uses tls_requests (browser TLS) off-thread — plain httpx gets JA3-blocked."""
    last_status: int | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = await asyncio.to_thread(_sync_get, url)
        except Exception as exc:
            log.warning("sofascore_http_error", url=url, attempt=attempt, error=str(exc))
            if attempt == _MAX_RETRIES:
                raise SofaScoreError(f"network error after retries: {exc}") from exc
            await asyncio.sleep(_BACKOFF_BASE * attempt)
            continue

        last_status = resp.status_code
        if resp.status_code == 200:
            await asyncio.sleep(random.uniform(_POLITE_MIN, _POLITE_MAX))
            return resp.json()

        if resp.status_code == 404:
            # No events scheduled / unknown day — empty, not an error.
            return {"events": []}

        if resp.status_code in (403, 429) or resp.status_code >= 500:
            retry_after = resp.headers.get("retry-after")
            wait = (
                float(retry_after)
                if retry_after and retry_after.isdigit()
                else _BACKOFF_BASE * (2 ** (attempt - 1))
            )
            log.warning(
                "sofascore_retry",
                url=url,
                status=resp.status_code,
                attempt=attempt,
                wait=round(wait, 1),
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(wait + random.uniform(0, 0.5))
                continue

        # Out of retries on a blocking status, or an unexpected status.
        break

    if last_status in (403, 429):
        raise SofaScoreBlocked(f"blocked with HTTP {last_status} after {_MAX_RETRIES} tries")
    raise SofaScoreError(f"unexpected HTTP {last_status} for {url}")


async def _upsert_events(pool, sport: str, events: list[dict]) -> int:
    """Idempotent upsert keyed on (sofascore_id, sport). Returns row count."""
    if not events:
        return 0
    rows = [
        (
            e["sofascore_id"],
            sport,
            e["tournament"],
            str(e["season"]) if e["season"] is not None else None,
            e["home_team"],
            e["away_team"],
            e["start_timestamp"],
            e["status"],
            e["home_score"],
            e["away_score"],
            json.dumps(e["raw"]),
        )
        for e in events
    ]
    await pool.executemany(
        """
        INSERT INTO sofascore_events (
            sofascore_id, sport, tournament, season, home_team, away_team,
            start_timestamp, status, home_score, away_score, raw, ingested_at
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb, NOW())
        ON CONFLICT (sofascore_id, sport) DO UPDATE SET
            tournament      = EXCLUDED.tournament,
            season          = EXCLUDED.season,
            home_team       = EXCLUDED.home_team,
            away_team       = EXCLUDED.away_team,
            start_timestamp = EXCLUDED.start_timestamp,
            status          = EXCLUDED.status,
            home_score      = EXCLUDED.home_score,
            away_score      = EXCLUDED.away_score,
            raw             = EXCLUDED.raw,
            ingested_at     = NOW()
        """,
        rows,
    )
    return len(rows)


async def ingest_day(
    sport: str,
    day: date,
    *,
    pool,
) -> _DayResult:
    """Pull one sport's scheduled/finished events for `day` and upsert them.

    Idempotent: re-running the same (sport, day) overwrites with the latest
    SofaScore view (scores fill in once games finish). A SofaScore block is
    caught here and returned as blocked=True so a multi-day run can decide to
    stop politely instead of crashing.
    """
    url = f"{API_BASE}/sport/{sport}/scheduled-events/{day.isoformat()}"
    try:
        payload = await _get_json(url)
    except SofaScoreBlocked as exc:
        log.warning("sofascore_blocked", sport=sport, day=day.isoformat(), error=str(exc))
        return _DayResult(fetched=0, upserted=0, blocked=True)
    except SofaScoreError:
        log.exception("sofascore_day_failed", sport=sport, day=day.isoformat())
        return _DayResult(fetched=0, upserted=0, blocked=False)

    raw_events = payload.get("events") or []
    parsed = [p for ev in raw_events if (p := _parse_event(ev)) is not None]
    upserted = await _upsert_events(pool, sport, parsed)
    log.info(
        "sofascore_day_done",
        sport=sport,
        day=day.isoformat(),
        fetched=len(raw_events),
        upserted=upserted,
    )
    return _DayResult(fetched=len(raw_events), upserted=upserted, blocked=False)


_DETAIL_CREATE = """
CREATE TABLE IF NOT EXISTS sofascore_event_details (
    event_id    BIGINT      NOT NULL,
    sport       TEXT        NOT NULL,
    incidents   JSONB,
    statistics  JSONB,
    lineups     JSONB,
    graph       JSONB,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (event_id, sport)
);
"""

# Per-event endpoints: incidents = the play-by-play, plus stats/lineups/momentum.
_DETAIL_ENDPOINTS = ("incidents", "statistics", "lineups", "graph")


async def ingest_event_details(sport: str, event_id: int, *, pool) -> None:
    """Fetch + bank an event's play-by-play (incidents) + stats + lineups + graph."""
    data: dict[str, dict | None] = {}
    for ep in _DETAIL_ENDPOINTS:
        try:
            data[ep] = await _get_json(f"{API_BASE}/event/{event_id}/{ep}")
        except SofaScoreError:
            data[ep] = None

    def _j(v):
        return json.dumps(v) if v else None

    await pool.execute(
        """INSERT INTO sofascore_event_details
               (event_id, sport, incidents, statistics, lineups, graph)
           VALUES ($1,$2,$3::jsonb,$4::jsonb,$5::jsonb,$6::jsonb)
           ON CONFLICT (event_id, sport) DO UPDATE SET
               incidents=EXCLUDED.incidents, statistics=EXCLUDED.statistics,
               lineups=EXCLUDED.lineups, graph=EXCLUDED.graph, ingested_at=NOW()""",
        event_id, sport, _j(data["incidents"]), _j(data["statistics"]),
        _j(data["lineups"]), _j(data["graph"]),
    )


async def backfill_details(sport: str, *, limit: int = 300, concurrency: int = 3) -> int:
    """Pull play-by-play + stats for finished events that don't have them yet."""
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    sem = asyncio.Semaphore(concurrency)
    try:
        await pool.execute(_DETAIL_CREATE)
        rows = await pool.fetch(
            """SELECT e.sofascore_id FROM sofascore_events e
               LEFT JOIN sofascore_event_details d
                 ON d.event_id=e.sofascore_id AND d.sport=e.sport
               WHERE e.sport=$1 AND e.status='Ended' AND d.event_id IS NULL
               ORDER BY e.start_timestamp DESC LIMIT $2""",
            sport, limit,
        )

        async def _one(eid: int):
            async with sem:
                try:
                    await ingest_event_details(sport, eid, pool=pool)
                except Exception as e:
                    log.warning("sofascore_detail_failed", event_id=eid, error=str(e)[:100])

        await asyncio.gather(*[_one(r["sofascore_id"]) for r in rows])
        log.info("sofascore_details_done", sport=sport, fetched=len(rows))
        return len(rows)
    finally:
        await close_pool()


async def ingest_range(
    sport: str,
    start: date,
    end: date,
    *,
    concurrency: int = 4,
) -> dict[str, int]:
    """Loop days [start, end], concurrency-limited, resilient to blocks.

    Returns a summary dict. Stops early (politely) once SofaScore starts
    blocking us, since hammering past a block is rude and pointless.
    """
    configure_logging(level=settings.log_level)
    proxy = settings.iproyal_proxy_url or None
    if proxy:
        log.info("sofascore_using_proxy")

    pool = await get_pool()
    sem = asyncio.Semaphore(concurrency)
    blocked = asyncio.Event()

    total_fetched = 0
    total_upserted = 0
    days_done = 0

    async def _one(day: date) -> _DayResult:
        async with sem:
            if blocked.is_set():
                return _DayResult(fetched=0, upserted=0, blocked=True)
            res = await ingest_day(sport, day, pool=pool)
            if res.blocked:
                blocked.set()
            return res

    try:
        await pool.execute(_CREATE)
        days = list(_daterange(start, end))
        log.info(
            "sofascore_range_start",
            sport=sport,
            start=start.isoformat(),
            end=end.isoformat(),
            days=len(days),
            concurrency=concurrency,
        )
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(_one(d)) for d in days]
        for t in tasks:
            res = t.result()
            total_fetched += res.fetched
            total_upserted += res.upserted
            if res.fetched or res.upserted:
                days_done += 1

        if blocked.is_set():
            log.warning(
                "sofascore_range_blocked",
                hint="SofaScore bot-blocked this host (403/429). In production route "
                "via a browser-grade fetch (nodriver/Crawlee) or a JA3-spoofing "
                "client; the IPRoyal HTTP proxy alone does not change the TLS "
                "fingerprint. Set IPROYAL_PROXY_URL for IP rotation regardless.",
            )
        log.info(
            "sofascore_range_done",
            sport=sport,
            days_with_data=days_done,
            fetched=total_fetched,
            upserted=total_upserted,
            blocked=blocked.is_set(),
        )
        return {
            "days": len(days),
            "days_with_data": days_done,
            "fetched": total_fetched,
            "upserted": total_upserted,
            "blocked": int(blocked.is_set()),
        }
    finally:
        await close_pool()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SofaScore multi-sport event warehouse ingest")
    p.add_argument(
        "--sport",
        default="basketball",
        help="SofaScore sport slug: basketball, football (soccer), "
        "american-football, tennis, ice-hockey, baseball, ...",
    )
    p.add_argument("--from", dest="date_from", help="start date YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", help="end date YYYY-MM-DD (inclusive)")
    p.add_argument("--date", help="single day YYYY-MM-DD (shortcut for --from==--to)")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--details", type=int, default=0, metavar="N",
                   help="also pull play-by-play + stats + lineups for up to N finished events")
    return p.parse_args()


def _main() -> None:
    a = _parse_args()
    have_dates = bool(a.date or a.date_from)
    if not have_dates and not a.details:
        raise SystemExit("provide --date / --from..--to (events) and/or --details N (play-by-play)")

    if have_dates:
        if a.date:
            start = end = date.fromisoformat(a.date)
        elif a.date_from and a.date_to:
            start = date.fromisoformat(a.date_from)
            end = date.fromisoformat(a.date_to)
        else:
            start = end = date.fromisoformat(a.date_from)
        if end < start:
            raise SystemExit("--to is before --from")
        s = asyncio.run(ingest_range(a.sport, start, end, concurrency=a.concurrency))
        print(
            f"\n  SofaScore · {a.sport} · {start} → {end}\n"
            f"  days={s['days']}  with_data={s['days_with_data']}  "
            f"fetched={s['fetched']}  upserted={s['upserted']}  "
            f"blocked={'yes' if s['blocked'] else 'no'}"
        )

    if a.details:
        n = asyncio.run(backfill_details(a.sport, limit=a.details, concurrency=a.concurrency))
        print(f"  play-by-play + stats pulled for {n} finished {a.sport} events")


if __name__ == "__main__":
    _main()
