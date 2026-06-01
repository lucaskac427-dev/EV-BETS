"""Sync open Kalshi NBA player-prop markets into the markets table.

Kalshi's player-prop markets are binary (YES/NO at a threshold like "35+
points"), one ticker per (player, stat, threshold). The pipeline expects rows
in the `markets` table to scan against; this job pulls every open prop and
upserts it.

Run: `python -m src.kalshi.market_sync`
"""

import asyncio
import re
from datetime import datetime

from src.config import settings
from src.db import close_pool, get_pool
from src.kalshi.client import KalshiClient
from src.logger import configure_logging, log
from src.repositories.markets import upsert_market

# Kalshi series ticker -> internal stat key. Keys must match the values in
# src.providers.pinnacle._STAT_MAP so sharp-book quotes synth the same ticker.
SERIES_TO_STAT: dict[str, str] = {
    "KXNBAPTS": "points",
    "KXNBAAST": "assists",
    "KXNBAREB": "rebounds",
    "KXNBA3PM": "threes",
    "KXNBABLK": "blocks",
    "KXNBASTL": "steals",
    "KXNBAPRA": "pra",
}

# Title pattern, e.g. "Victor Wembanyama: 35+ points" or "Chet Holmgren: 1+ blocks"
_TITLE_RE = re.compile(r"^(.+?):\s*(\d+(?:\.\d+)?)\+?\s+\w+", re.IGNORECASE)

# Game segment is the 2nd dash-delimited chunk, e.g. "26MAY30SASOKC" in
# "KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35".
_TICKER_GAME_RE = re.compile(
    r"^[A-Z0-9]+-(\d{2}[A-Z]{3}\d{2}[A-Z]+)-", re.IGNORECASE
)


def parse_market(m: dict) -> dict | None:
    """Parse a Kalshi market dict into upsert_market kwargs, or None to skip."""
    ticker = m.get("ticker", "")
    series = ticker.split("-", 1)[0] if "-" in ticker else ""
    stat = SERIES_TO_STAT.get(series)
    if not stat:
        return None

    title_match = _TITLE_RE.match(m.get("title", ""))
    if not title_match:
        return None
    player_name = title_match.group(1).strip()
    line = float(title_match.group(2))

    game_match = _TICKER_GAME_RE.match(ticker)
    if not game_match:
        return None
    game_id = game_match.group(1)

    # Kalshi exposes close_time (ISO8601). We don't have a true game-start
    # timestamp on the market endpoint, so we use close_time as the ordering
    # field. Pipeline only reads is_active=true; close_time only affects sort.
    close_ts = m.get("close_time")
    if not close_ts:
        return None
    game_starts_at = datetime.fromisoformat(close_ts.replace("Z", "+00:00"))

    return {
        "sport": "nba",
        "kalshi_ticker": ticker,
        "market_type": "player_prop",
        "player_name": player_name,
        "stat_type": stat,
        "line": line,
        "game_id": game_id,
        "game_starts_at": game_starts_at,
    }


async def sync_nba_player_props() -> int:
    """Pull open NBA player-prop markets from every supported series and
    upsert each into the markets table. Returns count synced."""
    configure_logging(level=settings.log_level)
    pool = await get_pool()
    client = KalshiClient()
    try:
        n_synced = 0
        n_skipped = 0
        for series in SERIES_TO_STAT:
            cursor: str | None = None
            while True:
                r = await client.get_markets(
                    limit=200,
                    series_ticker=series,
                    status="open",
                    cursor=cursor,
                )
                for m in r.get("markets", []):
                    parsed = parse_market(m)
                    if parsed is None:
                        n_skipped += 1
                        continue
                    await upsert_market(pool, **parsed)
                    n_synced += 1
                cursor = r.get("cursor") or None
                if not cursor:
                    break
            log.info("market_sync_series_complete", series=series)
        log.info("market_sync_complete", synced=n_synced, skipped=n_skipped)
        return n_synced
    finally:
        await client.close()
        await close_pool()


if __name__ == "__main__":
    n = asyncio.run(sync_nba_player_props())
    print(f"Synced {n} markets")
