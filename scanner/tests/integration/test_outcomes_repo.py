"""Integration tests for outcomes repo + reconciliation."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.calibration.reconcile import reconcile_outcomes
from src.repositories.game_logs import upsert_game_logs
from src.repositories.markets import upsert_market
from src.repositories.outcomes import (
    book_fair_prob_over,
    settled_over_under_since,
    upsert_market_outcome,
)
from src.repositories.snapshots import OddsSnapshot, bulk_insert_snapshots

pytestmark = pytest.mark.integration


async def test_upsert_and_query_settled(pool):
    m = await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-T-1", market_type="player_prop",
        game_id="LAL-BOS", game_starts_at=datetime(2025, 11, 20, tzinfo=timezone.utc),
    )
    await upsert_market_outcome(pool, market_id=m.id, outcome="over", actual_value=27.0)
    settled = await settled_over_under_since(pool, days=60)
    assert len(settled) == 1
    assert settled[0].outcome == "over"


async def test_book_fair_prob_over_devigs_snapshots(pool):
    m = await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-T-2", market_type="player_prop",
        game_id="LAL-BOS", game_starts_at=datetime(2025, 11, 20, tzinfo=timezone.utc),
    )
    await bulk_insert_snapshots(pool, [
        OddsSnapshot(m.id, "pinnacle", "over", Decimal("1.91"), Decimal("0.524")),
        OddsSnapshot(m.id, "pinnacle", "under", Decimal("1.91"), Decimal("0.524")),
    ])
    p = await book_fair_prob_over(pool, m.id, "pinnacle")
    assert abs(p - 0.5) < 1e-6


async def test_reconcile_settles_from_game_log(pool):
    game_dt = datetime(2025, 11, 20, 19, 30, tzinfo=timezone.utc)
    m = await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-NBA-LBJ-POINTS-24.5",
        market_type="player_prop", player_name="LeBron James", stat_type="points",
        line=24.5, game_id="LAL-BOS", game_starts_at=game_dt,
    )
    await upsert_game_logs(pool, [{
        "player_id": 2544, "player_name": "LeBron James", "team_abbr": "LAL",
        "game_id": "0022500099", "game_date": "2025-11-20", "matchup": "LAL @ BOS",
        "minutes": 35.0, "points": 30, "rebounds": 8, "assists": 9,
        "threes": 2, "blocks": 1, "steals": 1,
    }])
    # game_starts_at is in the past relative to the test only if we backdate it;
    # markets_needing_settlement filters game_starts_at < now(). Backdate it:
    await pool.execute(
        "UPDATE markets SET game_starts_at = $1 WHERE id = $2",
        datetime.now(timezone.utc) - timedelta(hours=4), m.id,
    )
    # game_date on the log must match the (now backdated) market date:
    await pool.execute(
        "UPDATE player_game_logs SET game_date = $1 WHERE player_id = 2544",
        (datetime.now(timezone.utc) - timedelta(hours=4)).date(),
    )

    settled = await reconcile_outcomes(pool)
    assert settled == 1
    row = await pool.fetchrow("SELECT outcome, actual_value FROM market_outcomes WHERE market_id = $1", m.id)
    assert row["outcome"] == "over"   # 30 > 24.5
    assert float(row["actual_value"]) == 30.0
