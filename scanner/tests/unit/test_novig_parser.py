"""Tests for the NoVig markets parser."""

from src.providers.novig import parse_novig_player_props

SAMPLE = {
    "markets": [
        {
            "player": "LeBron James",
            "stat": "points",
            "line": 24.5,
            "outcomes": [
                {"name": "Over", "price": 1.95},
                {"name": "Under", "price": 1.87},
            ],
        },
        {
            "player": "Jayson Tatum",
            "stat": "rebounds",
            "line": 8.5,
            "outcomes": [
                {"name": "Over", "price": 1.90},
                {"name": "Under", "price": 1.90},
            ],
        },
    ]
}


def test_parses_two_markets_four_quotes():
    quotes = parse_novig_player_props(SAMPLE)
    assert len(quotes) == 4
    assert all(q.book == "novig" for q in quotes)
    over = next(q for q in quotes if "LEBRONJAMES" in q.market_kalshi_ticker and q.side == "over")
    assert abs(float(over.decimal_odds) - 1.95) < 1e-9
    # implied = 1/1.95
    assert abs(float(over.implied_prob) - (1 / 1.95)) < 1e-6


def test_synthetic_ticker_matches_pinnacle_format():
    quotes = parse_novig_player_props(SAMPLE)
    tickers = {q.market_kalshi_ticker for q in quotes}
    assert "SYN-NBA-LEBRONJAMES-POINTS-24.5" in tickers


def test_empty_payload():
    assert parse_novig_player_props({}) == []
