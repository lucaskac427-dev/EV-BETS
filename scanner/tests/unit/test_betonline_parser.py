"""Tests for the BetOnline props parser."""

from src.providers.betonline import parse_betonline_player_props

SAMPLE = {
    "events": [
        {
            "props": [
                {
                    "playerName": "LeBron James",
                    "category": "points",
                    "line": 24.5,
                    "over": -110,
                    "under": -110,
                },
                {
                    "playerName": "Anthony Davis",
                    "category": "rebounds",
                    "line": 11.5,
                    "over": -120,
                    "under": 100,
                },
            ]
        }
    ]
}


def test_parses_props():
    quotes = parse_betonline_player_props(SAMPLE)
    assert len(quotes) == 4
    assert all(q.book == "betonline" for q in quotes)
    over = next(q for q in quotes if "LEBRONJAMES" in q.market_kalshi_ticker and q.side == "over")
    # -110 → decimal 1 + 100/110
    assert abs(float(over.decimal_odds) - (1 + 100 / 110)) < 1e-4


def test_synthetic_ticker_format():
    quotes = parse_betonline_player_props(SAMPLE)
    assert "SYN-NBA-LEBRONJAMES-POINTS-24.5" in {q.market_kalshi_ticker for q in quotes}


def test_empty():
    assert parse_betonline_player_props({}) == []
