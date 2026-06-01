"""Integration tests for the game-logs cache repository."""

import pytest

from src.repositories.game_logs import (
    league_averages,
    player_id_by_name,
    recent_logs_for_player,
    team_defense,
    upsert_game_logs,
    upsert_league_averages,
    upsert_team_defense,
)

pytestmark = pytest.mark.integration


def _log(game_id: str, date_str: str, pts: int) -> dict:
    return {
        "player_id": 2544, "player_name": "LeBron James", "team_abbr": "LAL",
        "game_id": game_id, "game_date": date_str, "matchup": "LAL @ BOS",
        "minutes": 34.0, "points": pts, "rebounds": 8, "assists": 9,
        "threes": 2, "blocks": 1, "steals": 1,
    }


async def test_upsert_and_fetch_logs(pool):
    n = await upsert_game_logs(pool, [_log("G1", "2025-11-18", 28), _log("G2", "2025-11-20", 31)])
    assert n == 2
    logs = await recent_logs_for_player(pool, 2544, limit=20)
    assert len(logs) == 2
    assert logs[0].points == 31  # newest first


async def test_upsert_dedupes_by_game(pool):
    await upsert_game_logs(pool, [_log("G1", "2025-11-18", 28)])
    await upsert_game_logs(pool, [_log("G1", "2025-11-18", 99)])  # same game, ignored
    logs = await recent_logs_for_player(pool, 2544)
    assert len(logs) == 1
    assert logs[0].points == 28


async def test_player_id_by_name(pool):
    await upsert_game_logs(pool, [_log("G1", "2025-11-18", 28)])
    assert await player_id_by_name(pool, "LeBron James") == 2544
    assert await player_id_by_name(pool, "Nobody") is None


async def test_team_defense_roundtrip(pool):
    await upsert_team_defense(pool, [
        {"team_abbr": "BOS", "def_rating": 110.5, "pace": 98.5, "opp_pts_per_game": 108.0},
    ])
    d = await team_defense(pool, "BOS")
    assert d["def_rating"] == 110.5
    assert await team_defense(pool, "ZZZ") is None


async def test_league_averages_roundtrip(pool):
    await upsert_league_averages(pool, season="2025-26", avg_def_rating=113.0, avg_pace=99.0)
    avg = await league_averages(pool, "2025-26")
    assert avg["avg_def_rating"] == 113.0
