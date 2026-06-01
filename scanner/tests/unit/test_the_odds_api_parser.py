"""Tests for the Odds API event-odds parser."""

import math

from src.providers.sport_config import NBA_ODDS
from src.providers.the_odds_api import parse_event_odds


def _event_with(outcomes_by_book: dict) -> dict:
    return {
        "id": "evt1",
        "bookmakers": [
            {
                "key": book,
                "markets": [
                    {"key": market_key, "outcomes": outs}
                    for market_key, outs in markets.items()
                ],
            }
            for book, markets in outcomes_by_book.items()
        ],
    }


def test_parses_one_book_one_market():
    payload = _event_with({
        "draftkings": {
            "player_points": [
                {"name": "Over", "description": "Victor Wembanyama", "price": -125, "point": 24.5},
                {"name": "Under", "description": "Victor Wembanyama", "price": +105, "point": 24.5},
            ]
        }
    })
    quotes = parse_event_odds(payload, NBA_ODDS)
    assert len(quotes) == 2
    over = next(q for q in quotes if q.side == "over")
    assert over.book == "draftkings"
    assert over.market_kalshi_ticker == "SYN-NBA-VICTORWEMBANYAMA-POINTS-24.5"
    # -125 -> 1.80
    assert math.isclose(float(over.decimal_odds), 1.80, abs_tol=1e-4)


def test_emits_one_quote_per_bookmaker():
    """Same player+stat+line at 3 books -> 6 quotes (3 books × over/under)."""
    payload = _event_with({
        book: {
            "player_rebounds": [
                {"name": "Over", "description": "Chet Holmgren", "price": -110, "point": 8.5},
                {"name": "Under", "description": "Chet Holmgren", "price": -110, "point": 8.5},
            ]
        }
        for book in ("draftkings", "fanduel", "betmgm")
    })
    quotes = parse_event_odds(payload, NBA_ODDS)
    assert len(quotes) == 6
    books = {q.book for q in quotes}
    assert books == {"draftkings", "fanduel", "betmgm"}


def test_canonical_book_collapses_hardrock_regions():
    from src.providers.the_odds_api import canonical_book

    assert canonical_book("hardrockbet") == "hardrockbet"
    assert canonical_book("hardrockbet_az") == "hardrockbet"
    assert canonical_book("hardrockbet_fl") == "hardrockbet"
    # 'us' / 'eu' are NOT state codes — leave those books alone
    assert canonical_book("williamhill_us") == "williamhill_us"
    assert canonical_book("unibet_us") == "unibet_us"
    assert canonical_book("betmgm") == "betmgm"


def test_hardrock_regions_count_as_one_book():
    """3 Hard Rock regional variants must collapse to ONE book key so consensus
    + num_sharp_books don't triple-count the same operator."""
    payload = _event_with({
        book: {
            "player_points": [
                {"name": "Over", "description": "LeBron James", "price": -110, "point": 24.5},
                {"name": "Under", "description": "LeBron James", "price": -110, "point": 24.5},
            ]
        }
        for book in ("hardrockbet", "hardrockbet_az", "hardrockbet_fl")
    })
    quotes = parse_event_odds(payload, NBA_ODDS)
    assert {q.book for q in quotes} == {"hardrockbet"}


def test_skips_unknown_market_keys():
    payload = _event_with({
        "draftkings": {
            # h2h is moneyline — not a player prop we track
            "h2h": [{"name": "Over", "description": "X", "price": -110, "point": 0.5}]
        }
    })
    assert parse_event_odds(payload, NBA_ODDS) == []


def test_skips_outcomes_missing_fields():
    payload = _event_with({
        "draftkings": {
            "player_points": [
                {"name": "Over", "description": None, "price": -110, "point": 24.5},
                {"name": "Over", "description": "Wemby", "price": None, "point": 24.5},
                {"name": "Over", "description": "Wemby", "price": -110, "point": None},
                {"name": "Push", "description": "Wemby", "price": -110, "point": 24.5},
            ]
        }
    })
    assert parse_event_odds(payload, NBA_ODDS) == []


def test_maps_market_keys_to_internal_stats():
    book = "draftkings"
    payload = _event_with({
        book: {
            "player_assists": [
                {"name": "Over", "description": "SGA", "price": -110, "point": 7.5},
                {"name": "Under", "description": "SGA", "price": -110, "point": 7.5},
            ],
            "player_threes": [
                {"name": "Over", "description": "SGA", "price": -110, "point": 2.5},
                {"name": "Under", "description": "SGA", "price": -110, "point": 2.5},
            ],
            "player_points_rebounds_assists": [
                {"name": "Over", "description": "SGA", "price": -110, "point": 39.5},
                {"name": "Under", "description": "SGA", "price": -110, "point": 39.5},
            ],
        }
    })
    quotes = parse_event_odds(payload, NBA_ODDS)
    tickers = {q.market_kalshi_ticker for q in quotes}
    assert "SYN-NBA-SGA-ASSISTS-7.5" in tickers
    assert "SYN-NBA-SGA-THREES-2.5" in tickers
    assert "SYN-NBA-SGA-PRA-39.5" in tickers
