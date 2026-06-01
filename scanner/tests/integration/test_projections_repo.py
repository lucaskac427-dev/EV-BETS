"""Integration tests for the projections repository."""

from datetime import datetime, timezone

import pytest

from src.repositories.markets import upsert_market
from src.repositories.projections import insert_projection, latest_projection_prob

pytestmark = pytest.mark.integration


async def _market(pool):
    return await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-NBA-X-POINTS-24.5",
        market_type="player_prop", game_id="G",
        game_starts_at=datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc),
    )


async def test_insert_and_read_latest(pool):
    m = await _market(pool)
    await insert_projection(
        pool, market_id=m.id, mean=25.4, std_dev=3.2,
        distribution="normal", fair_prob_over=0.58, model_version="baseline-v1",
    )
    assert abs(await latest_projection_prob(pool, m.id) - 0.58) < 1e-6


async def test_latest_returns_newest(pool):
    m = await _market(pool)
    await insert_projection(pool, market_id=m.id, mean=25.0, std_dev=3.0,
                            distribution="normal", fair_prob_over=0.50, model_version="v1")
    await insert_projection(pool, market_id=m.id, mean=26.0, std_dev=3.0,
                            distribution="normal", fair_prob_over=0.62, model_version="v1")
    assert abs(await latest_projection_prob(pool, m.id) - 0.62) < 1e-6


async def test_none_when_no_projection(pool):
    m = await _market(pool)
    assert await latest_projection_prob(pool, m.id) is None
