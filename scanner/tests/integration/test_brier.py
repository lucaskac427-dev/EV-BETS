"""Integration test for Brier weight computation."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.calibration.brier import compute_brier_weights
from src.repositories.markets import upsert_market
from src.repositories.outcomes import upsert_market_outcome
from src.repositories.snapshots import OddsSnapshot, bulk_insert_snapshots

pytestmark = pytest.mark.integration


async def test_insufficient_data_returns_empty(pool):
    # Only a handful of settled markets → below MIN_SETTLED → {}
    weights = await compute_brier_weights(pool, lookback_days=60, min_settled=100)
    assert weights == {}


async def test_better_book_gets_higher_weight(pool):
    # Build 20 settled markets. Pinnacle predicts perfectly; DraftKings predicts
    # the opposite. With min_settled lowered to 10, Pinnacle weight >> DraftKings.
    for i in range(20):
        went_over = i % 2 == 0
        m = await upsert_market(
            pool, sport="NBA", kalshi_ticker=f"SYN-T-{i}", market_type="player_prop",
            game_id="LAL-BOS", game_starts_at=datetime(2025, 11, 20, tzinfo=timezone.utc),
        )
        # Pinnacle: confident & correct (0.99 over when it went over, else 0.01)
        p_over = 0.99 if went_over else 0.01
        # DraftKings: confident & WRONG
        d_over = 0.01 if went_over else 0.99
        await bulk_insert_snapshots(pool, [
            OddsSnapshot(m.id, "pinnacle", "over", Decimal("1.0"), Decimal(str(p_over))),
            OddsSnapshot(m.id, "pinnacle", "under", Decimal("1.0"), Decimal(str(1 - p_over))),
            OddsSnapshot(m.id, "draftkings", "over", Decimal("1.0"), Decimal(str(d_over))),
            OddsSnapshot(m.id, "draftkings", "under", Decimal("1.0"), Decimal(str(1 - d_over))),
        ])
        await upsert_market_outcome(
            pool, market_id=m.id, outcome="over" if went_over else "under", actual_value=1.0
        )

    weights = await compute_brier_weights(pool, lookback_days=60, min_settled=10)
    assert "pinnacle" in weights
    assert "draftkings" in weights
    assert weights["pinnacle"] > weights["draftkings"] * 100  # vastly better
