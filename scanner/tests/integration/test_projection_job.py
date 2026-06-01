"""Integration test for the nightly projection job."""

from datetime import datetime, timezone

import pytest

from src.projections.job import run_projection_job
from src.repositories.game_logs import (
    upsert_game_logs,
    upsert_league_averages,
    upsert_team_defense,
)
from src.repositories.markets import upsert_market
from src.repositories.projections import latest_projection_prob

pytestmark = pytest.mark.integration


def _log(gid: str, date_str: str, pts: int) -> dict:
    return {
        "player_id": 2544, "player_name": "LeBron James", "team_abbr": "LAL",
        "game_id": gid, "game_date": date_str, "matchup": "LAL @ BOS",
        "minutes": 34.0, "points": pts, "rebounds": 8, "assists": 8,
        "threes": 2, "blocks": 1, "steals": 1,
    }


async def test_job_writes_projection_for_player_prop(pool):
    # Seed 10 game logs for LeBron
    logs = [_log(f"G{i}", f"2025-11-{10+i:02d}", 24 + (i % 5)) for i in range(10)]
    await upsert_game_logs(pool, logs)
    # Seed team defense for opponent BOS + league averages
    await upsert_team_defense(pool, [
        {"team_abbr": "BOS", "def_rating": 113.0, "pace": 99.0, "opp_pts_per_game": 110.0},
    ])
    await upsert_league_averages(pool, season="2025-26", avg_def_rating=113.0, avg_pace=99.0)
    # Market: LeBron points 24.5, game LAL @ BOS (game_id "LAL-BOS")
    await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-NBA-LEBRONJAMES-POINTS-24.5",
        market_type="player_prop", player_name="LeBron James", stat_type="points",
        line=24.5, game_id="LAL-BOS",
        game_starts_at=datetime(2025, 11, 21, 19, 30, tzinfo=timezone.utc),
    )

    written = await run_projection_job(pool, season="2025-26")
    assert written >= 1

    m_id_row = await pool.fetchrow(
        "SELECT id FROM markets WHERE kalshi_ticker = 'SYN-NBA-LEBRONJAMES-POINTS-24.5'"
    )
    prob = await latest_projection_prob(pool, m_id_row["id"])
    assert prob is not None
    assert 0.0 < prob < 1.0


async def test_job_skips_market_without_logs(pool):
    await upsert_league_averages(pool, season="2025-26", avg_def_rating=113.0, avg_pace=99.0)
    await upsert_market(
        pool, sport="NBA", kalshi_ticker="SYN-NBA-NOBODY-POINTS-10.5",
        market_type="player_prop", player_name="Nobody", stat_type="points",
        line=10.5, game_id="LAL-BOS",
        game_starts_at=datetime(2025, 11, 21, 19, 30, tzinfo=timezone.utc),
    )
    written = await run_projection_job(pool, season="2025-26")
    assert written == 0
