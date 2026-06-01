"""Tests for the nba_api wrapper — verifies parsing of endpoint dataframes.

We mock the nba_api endpoint classes so tests don't hit the network.
"""

from unittest.mock import MagicMock, patch

import pandas as pd

from src.nba_stats.client import fetch_player_game_logs, fetch_team_defense


@patch("src.nba_stats.client.PlayerGameLogs")
def test_fetch_player_game_logs_parses_rows(mock_endpoint):
    df = pd.DataFrame(
        {
            "PLAYER_ID": [2544, 2544],
            "PLAYER_NAME": ["LeBron James", "LeBron James"],
            "TEAM_ABBREVIATION": ["LAL", "LAL"],
            "GAME_ID": ["0022500001", "0022500002"],
            "GAME_DATE": ["2025-11-18", "2025-11-20"],
            "MATCHUP": ["LAL @ BOS", "LAL vs. DEN"],
            "MIN": [35.0, 33.0],
            "PTS": [28, 31],
            "REB": [8, 7],
            "AST": [9, 11],
            "FG3M": [2, 3],
            "BLK": [1, 0],
            "STL": [2, 1],
        }
    )
    instance = MagicMock()
    instance.get_data_frames.return_value = [df]
    mock_endpoint.return_value = instance

    rows = fetch_player_game_logs(season="2025-26", last_n_games=20)
    assert len(rows) == 2
    assert rows[0]["player_id"] == 2544
    assert rows[0]["points"] == 28
    assert rows[0]["threes"] == 2
    assert rows[0]["matchup"] == "LAL @ BOS"


@patch("src.nba_stats.client.LeagueDashTeamStats")
def test_fetch_team_defense_parses_rows(mock_endpoint):
    # LeagueDashTeamStats(Advanced) returns TEAM_ID (no abbreviation) and no
    # opponent-points column. The client maps TEAM_ID -> abbreviation via the
    # static teams table. 1610612738 = BOS, 1610612743 = DEN.
    df = pd.DataFrame(
        {
            "TEAM_ID": [1610612738, 1610612743],
            "TEAM_NAME": ["Boston Celtics", "Denver Nuggets"],
            "DEF_RATING": [110.5, 114.2],
            "PACE": [98.5, 100.1],
        }
    )
    instance = MagicMock()
    instance.get_data_frames.return_value = [df]
    mock_endpoint.return_value = instance

    rows = fetch_team_defense(season="2025-26")
    assert len(rows) == 2
    by_abbr = {r["team_abbr"]: r for r in rows}
    assert by_abbr["BOS"]["def_rating"] == 110.5
    assert by_abbr["BOS"]["pace"] == 98.5
    # opp_pts_per_game is not exposed by Advanced; defaults to 0.0
    assert by_abbr["BOS"]["opp_pts_per_game"] == 0.0
    assert "DEN" in by_abbr
