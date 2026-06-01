"""Integration tests for repositories — requires Postgres."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.repositories.bankroll import current_bankroll_cents
from src.repositories.markets import fetch_active_markets, upsert_market
from src.repositories.opportunities import fetch_latest_opportunities, insert_opportunity
from src.repositories.snapshots import OddsSnapshot, bulk_insert_snapshots
from src.repositories.telemetry import latest_fetch_per_source, record_event

pytestmark = pytest.mark.integration


async def test_upsert_market_inserts_new(pool):
    market = await upsert_market(
        pool,
        sport="NBA",
        kalshi_ticker="KXNBAGAME-25NOV20-LAL-POINTS-LEBRON",
        market_type="player_prop",
        player_name="LeBron James",
        stat_type="points",
        line=24.5,
        game_id="LAL-BOS-2025-11-20",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )
    assert market.id > 0
    assert market.kalshi_ticker == "KXNBAGAME-25NOV20-LAL-POINTS-LEBRON"


async def test_fetch_active_markets_returns_inserted(pool):
    await upsert_market(
        pool,
        sport="NBA",
        kalshi_ticker="KXNBAGAME-25NOV20-LAL-POINTS-LEBRON",
        market_type="player_prop",
        game_id="LAL-BOS-2025-11-20",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )
    markets = await fetch_active_markets(pool)
    assert len(markets) == 1
    assert markets[0].kalshi_ticker.startswith("KXNBAGAME")


async def _make_market(pool):
    return await upsert_market(
        pool,
        sport="NBA",
        kalshi_ticker="KXTEST-1",
        market_type="player_prop",
        game_id="TEST",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )


async def test_bulk_insert_snapshots(pool):
    m = await _make_market(pool)
    snapshots = [
        OddsSnapshot(m.id, "pinnacle", "over", Decimal("1.91"), Decimal("0.524")),
        OddsSnapshot(m.id, "pinnacle", "under", Decimal("1.91"), Decimal("0.524")),
    ]
    count = await bulk_insert_snapshots(pool, snapshots)
    assert count == 2


async def test_insert_and_fetch_opportunity(pool):
    m = await _make_market(pool)
    opp_id = await insert_opportunity(
        pool,
        market_id=m.id,
        kalshi_side="yes",
        kalshi_decimal_odds=Decimal("2.0833"),
        consensus_fair_prob=Decimal("0.580000"),
        projection_fair_prob=None,
        blended_fair_prob=Decimal("0.580000"),
        ev_pct=Decimal("0.0630"),
        kelly_fraction=Decimal("0.0140"),
        num_sharp_books=2,
        suspicious=False,
    )
    assert opp_id > 0

    opps = await fetch_latest_opportunities(pool, min_ev=0.01)
    assert len(opps) == 1
    assert float(opps[0].ev_pct) > 0.05


async def test_current_bankroll_zero_if_no_events(pool):
    assert await current_bankroll_cents(pool) == 0


async def test_current_bankroll_returns_latest_balance(pool):
    await pool.execute(
        "INSERT INTO bankroll_events (event_type, delta_cents, balance_cents) "
        "VALUES ('deposit', 80000, 80000)"
    )
    assert await current_bankroll_cents(pool) == 80_000


async def test_telemetry_record_and_read(pool):
    await record_event(
        pool, tick_id="abc", source="pinnacle",
        event_type="fetch_success", latency_ms=420,
    )
    latest = await latest_fetch_per_source(pool)
    assert "pinnacle" in latest
