"""End-to-end pipeline tick test against Postgres with mocked providers."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from src.kalshi.adapter import KalshiAdapter
from src.pipeline import run_scan_tick
from src.providers.base import OddsQuote
from src.repositories.markets import upsert_market

pytestmark = pytest.mark.integration


class FakeProvider:
    def __init__(self, name: str, quotes: list[OddsQuote]):
        self.name = name
        self._quotes = quotes

    async def fetch_odds(self, _: list[str]) -> list[OddsQuote]:
        return self._quotes


async def test_full_tick_writes_opportunity_when_positive_ev(pool):
    # market.line is the Kalshi THRESHOLD (25+). synth_ticker_for shifts it by
    # -0.5 to the sharp "Over 24.5" namespace, which is where the quotes live.
    await upsert_market(
        pool,
        sport="NBA",
        kalshi_ticker="SYN-NBA-LEBRONJAMES-POINTS-25",
        market_type="player_prop",
        player_name="LeBron James",
        stat_type="points",
        line=25.0,
        game_id="LAL-BOS",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )
    await pool.execute(
        "INSERT INTO bankroll_events (event_type, delta_cents, balance_cents) "
        "VALUES ('deposit', 80000, 80000)"
    )

    sharp_quotes = [
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "pinnacle", "over",
                  Decimal("1.85"), Decimal("0.541")),
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "pinnacle", "under",
                  Decimal("1.95"), Decimal("0.513")),
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "novig", "over",
                  Decimal("1.88"), Decimal("0.532")),
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "novig", "under",
                  Decimal("1.92"), Decimal("0.521")),
    ]
    kalshi_quotes = [
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "kalshi", "yes",
                  Decimal(100) / Decimal(45), Decimal("0.45")),
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "kalshi", "no",
                  Decimal(100) / Decimal(55), Decimal("0.55")),
    ]

    sharp = FakeProvider("pinnacle", [q for q in sharp_quotes if q.book == "pinnacle"])
    sharp2 = FakeProvider("novig", [q for q in sharp_quotes if q.book == "novig"])

    fake_kalshi_client = AsyncMock()
    adapter = KalshiAdapter(client=fake_kalshi_client)
    adapter.fetch_odds = AsyncMock(return_value=kalshi_quotes)

    n = await run_scan_tick(
        pool=pool, sharp_providers=[sharp, sharp2], kalshi=adapter,
        days_since_launch=0,
    )
    assert n >= 1

    row = await pool.fetchrow("SELECT * FROM opportunities ORDER BY id DESC LIMIT 1")
    assert row["kalshi_side"] == "yes"
    assert float(row["ev_pct"]) > 0.01
    assert row["num_sharp_books"] == 2


async def test_tick_skips_market_with_only_one_sharp_book(pool):
    await upsert_market(
        pool, sport="NBA",
        kalshi_ticker="SYN-NBA-XYZ-POINTS-10.5",
        market_type="player_prop",
        game_id="X-Y",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )
    await pool.execute(
        "INSERT INTO bankroll_events (event_type, delta_cents, balance_cents) "
        "VALUES ('deposit', 80000, 80000)"
    )

    sharp = FakeProvider("pinnacle", [
        OddsQuote("SYN-NBA-XYZ-POINTS-10.5", "pinnacle", "over",
                  Decimal("1.85"), Decimal("0.541")),
        OddsQuote("SYN-NBA-XYZ-POINTS-10.5", "pinnacle", "under",
                  Decimal("1.95"), Decimal("0.513")),
    ])
    adapter = KalshiAdapter(client=AsyncMock())
    adapter.fetch_odds = AsyncMock(return_value=[
        OddsQuote("SYN-NBA-XYZ-POINTS-10.5", "kalshi", "yes",
                  Decimal(100) / Decimal(45), Decimal("0.45")),
        OddsQuote("SYN-NBA-XYZ-POINTS-10.5", "kalshi", "no",
                  Decimal(100) / Decimal(55), Decimal("0.55")),
    ])

    n = await run_scan_tick(
        pool=pool, sharp_providers=[sharp], kalshi=adapter, days_since_launch=0,
    )
    assert n == 0
