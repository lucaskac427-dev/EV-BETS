"""Tests for the DraftKings selections parser."""

from src.providers.draftkings import parse_draftkings_player_props

SAMPLE = {
    "selections": [
        {"participant": "LeBron James", "marketStat": "points", "label": "Over",
         "points": 24.5, "oddsAmerican": "-115"},
        {"participant": "LeBron James", "marketStat": "points", "label": "Under",
         "points": 24.5, "oddsAmerican": "-105"},
        {"participant": "Luka Doncic", "marketStat": "assists", "label": "Over",
         "points": 8.5, "oddsAmerican": "+100"},
        {"participant": "Luka Doncic", "marketStat": "assists", "label": "Under",
         "points": 8.5, "oddsAmerican": "-120"},
    ]
}


def test_parses_grouped_selections():
    quotes = parse_draftkings_player_props(SAMPLE)
    assert len(quotes) == 4
    assert all(q.book == "draftkings" for q in quotes)
    over = next(q for q in quotes if "LEBRONJAMES" in q.market_kalshi_ticker and q.side == "over")
    assert abs(float(over.decimal_odds) - (1 + 100 / 115)) < 1e-4


def test_plus_odds_parse():
    quotes = parse_draftkings_player_props(SAMPLE)
    luka_over = next(q for q in quotes if "LUKADONCIC" in q.market_kalshi_ticker and q.side == "over")
    assert abs(float(luka_over.decimal_odds) - 2.0) < 1e-9  # +100


def test_empty():
    assert parse_draftkings_player_props({}) == []
