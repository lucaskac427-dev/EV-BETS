"""Pull CURRENT NBA prop odds (every book, incl Bovada) into live_book_odds.

The DFS scan fetches these for consensus but abstracts them to tickers; this keeps
the raw player / line / book / event so the Bovada edge finder runs on LIVE pre-game
prices, not stored closing snapshots. Truncate-and-replace each run = no bloat.
Best-effort: any failure is swallowed so it can never break a page load.

    python -m src.dfs.live_odds
"""

import asyncio
from datetime import datetime, timezone

from src.db import close_pool, get_pool
from src.logger import configure_logging, log
from src.providers.base import american_to_decimal
from src.providers.the_odds_api import OddsAPIProvider

_CREATE = """
CREATE TABLE IF NOT EXISTS live_book_odds (
    event_start  TIMESTAMPTZ,
    book         TEXT NOT NULL,
    market_key   TEXT NOT NULL,
    player_name  TEXT,
    line         NUMERIC,
    side         TEXT NOT NULL,
    decimal_odds NUMERIC NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _ts(s: str | None):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except Exception:
        return None


async def refresh(sport: str = "nba", *, pool=None) -> int:
    owns_pool = pool is None
    if owns_pool:
        configure_logging(level="CRITICAL")
    prov = OddsAPIProvider.for_sport(sport)
    markets_csv = ",".join(prov._config.market_to_stat.keys())
    rows: list[tuple] = []
    try:
        events = await prov._list_events()
        for ev in events:
            eid = ev.get("id")
            start = _ts(ev.get("commence_time"))
            if not eid:
                continue
            try:
                payload = await prov._get_event_odds(eid, markets_csv)
            except Exception as e:
                log.warning("live_odds_event_failed", error=str(e)[:120])
                continue
            for bm in payload.get("bookmakers", []):
                book = bm.get("key")
                for m in bm.get("markets", []):
                    mk = m.get("key")
                    for o in m.get("outcomes", []):
                        side = (o.get("name") or "").lower()
                        player, price, line = o.get("description"), o.get("price"), o.get("point")
                        if side not in ("over", "under") or player is None or price is None or line is None:
                            continue
                        rows.append((start, book, mk, player, float(line), side,
                                     float(american_to_decimal(int(price)))))
    except Exception as e:
        log.warning("live_odds_list_failed", error=str(e)[:120])
    finally:
        await prov.aclose()

    if pool is None:
        pool = await get_pool()
    try:
        await pool.execute(_CREATE)
        async with pool.acquire() as con:
            async with con.transaction():
                await con.execute("TRUNCATE live_book_odds")
                if rows:
                    now = datetime.now(timezone.utc)
                    await con.copy_records_to_table(
                        "live_book_odds",
                        records=[(*r, now) for r in rows],
                        columns=["event_start", "book", "market_key", "player_name",
                                 "line", "side", "decimal_odds", "fetched_at"])
    finally:
        if owns_pool:
            await close_pool()
    return len(rows)


async def _main() -> None:
    n = await refresh("nba")
    print(f"live_book_odds refreshed: {n} quotes")


if __name__ == "__main__":
    asyncio.run(_main())
