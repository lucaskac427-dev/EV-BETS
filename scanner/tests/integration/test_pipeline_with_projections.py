"""Pipeline test verifying projections are blended into the opportunity."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from src.kalshi.adapter import KalshiAdapter
from src.pipeline import run_scan_tick
from src.providers.base import OddsQuote
from src.repositories.markets import upsert_market
from src.repositories.projections import insert_projection

pytestmark = pytest.mark.integration


class FakeProvider:
    def __init__(self, name, quotes):
        self.name = name
        self._quotes = quotes

    async def fetch_odds(self, _):
        return self._quotes


async def test_projection_recorded_on_opportunity(pool):
    # line = Kalshi threshold (25+); synth_ticker_for(-0.5) -> sharp "24.5" join key.
    m = await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-NBA-LEBRONJAMES-POINTS-25",
        market_type="player_prop", player_name="LeBron James", stat_type="points",
        line=25.0, game_id="LAL-BOS",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )
    await pool.execute(
        "INSERT INTO bankroll_events (event_type, delta_cents, balance_cents) "
        "VALUES ('deposit', 80000, 80000)"
    )
    # Projection says 'over' is 60% likely
    await insert_projection(
        pool, market_id=m.id, mean=26.0, std_dev=4.0,
        distribution="normal", fair_prob_over=0.60, model_version="baseline-v1",
    )

    sharp = FakeProvider("pinnacle", [
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "pinnacle", "over", Decimal("1.90"), Decimal("0.526")),
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "pinnacle", "under", Decimal("1.90"), Decimal("0.526")),
    ])
    sharp2 = FakeProvider("novig", [
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "novig", "over", Decimal("1.91"), Decimal("0.524")),
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "novig", "under", Decimal("1.91"), Decimal("0.524")),
    ])
    adapter = KalshiAdapter(client=AsyncMock())
    adapter.fetch_odds = AsyncMock(return_value=[
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "kalshi", "yes", Decimal(100)/Decimal(45), Decimal("0.45")),
        OddsQuote("SYN-NBA-LEBRONJAMES-POINTS-24.5", "kalshi", "no", Decimal(100)/Decimal(55), Decimal("0.55")),
    ])

    # days_since_launch=90 → projection weight 0.40 (full)
    n = await run_scan_tick(pool=pool, sharp_providers=[sharp, sharp2], kalshi=adapter,
                            days_since_launch=90)
    assert n >= 1

    row = await pool.fetchrow("SELECT * FROM opportunities ORDER BY id DESC LIMIT 1")
    # projection_fair_prob must be populated now (not NULL)
    assert row["projection_fair_prob"] is not None
    # Blended must sit between consensus (~0.50) and projection (0.60) for the 'yes'/over side
    assert row["kalshi_side"] == "yes"
    assert 0.50 < float(row["blended_fair_prob"]) <= 0.60


async def test_tick_accepts_custom_consensus_weights(pool):
    m = await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-NBA-TESTGUY-POINTS-21",
        market_type="player_prop", player_name="Test Guy", stat_type="points",
        line=21.0, game_id="LAL-BOS",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )
    await pool.execute(
        "INSERT INTO bankroll_events (event_type, delta_cents, balance_cents) "
        "VALUES ('deposit', 80000, 80000)"
    )
    sharp = FakeProvider("pinnacle", [
        OddsQuote("SYN-NBA-TESTGUY-POINTS-20.5", "pinnacle", "over", Decimal("1.90"), Decimal("0.526")),
        OddsQuote("SYN-NBA-TESTGUY-POINTS-20.5", "pinnacle", "under", Decimal("1.90"), Decimal("0.526")),
    ])
    sharp2 = FakeProvider("novig", [
        OddsQuote("SYN-NBA-TESTGUY-POINTS-20.5", "novig", "over", Decimal("1.90"), Decimal("0.526")),
        OddsQuote("SYN-NBA-TESTGUY-POINTS-20.5", "novig", "under", Decimal("1.90"), Decimal("0.526")),
    ])
    adapter = KalshiAdapter(client=AsyncMock())
    adapter.fetch_odds = AsyncMock(return_value=[
        OddsQuote("SYN-NBA-TESTGUY-POINTS-20.5", "kalshi", "yes", Decimal(100)/Decimal(44), Decimal("0.44")),
        OddsQuote("SYN-NBA-TESTGUY-POINTS-20.5", "kalshi", "no", Decimal(100)/Decimal(56), Decimal("0.56")),
    ])
    # Custom weights that only mention pinnacle — novig must get a cold-start fallback,
    # NOT raise a KeyError.
    n = await run_scan_tick(
        pool=pool, sharp_providers=[sharp, sharp2], kalshi=adapter,
        days_since_launch=0, consensus_weights={"pinnacle": 5.0},
    )
    assert n >= 1
