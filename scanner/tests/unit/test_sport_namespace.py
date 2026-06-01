"""Tests for sport-aware synth ticker + per-sport parsing."""

from src.providers._player_props import synthesize_ticker, _normalize_name
from src.providers.sport_config import SOCCER_ODDS_UCL, NBA_ODDS
from src.providers.the_odds_api import parse_event_odds


def test_synth_ticker_normalizes_unicode():
    """Accented spellings must collapse to the ASCII form so PrizePicks'
    'Vinícius Júnior' joins Pinnacle's 'Vinicius Junior'."""
    a = synthesize_ticker("SOCCER", "Vinícius Júnior", "shots", 2.5)
    b = synthesize_ticker("SOCCER", "Vinicius Junior", "shots", 2.5)
    assert a == b == "SYN-SOCCER-VINICIUSJUNIOR-SHOTS-2.5"


def test_synth_ticker_separates_sports():
    """Two different sports never produce the same ticker even for shared names."""
    nba = synthesize_ticker("NBA", "Jordan", "points", 24.5)
    soccer = synthesize_ticker("SOCCER", "Jordan", "shots", 24.5)
    assert nba != soccer
    assert nba.startswith("SYN-NBA-")
    assert soccer.startswith("SYN-SOCCER-")


def test_normalize_name_strips_punctuation_and_spaces():
    assert _normalize_name("N'Golo Kanté") == "NGOLOKANTE"
    assert _normalize_name("Müller") == "MULLER"


def test_odds_api_parser_uses_sport_tag_from_config():
    """Same payload through SOCCER config produces SOCCER-tagged tickers."""
    payload = {
        "id": "evt1",
        "bookmakers": [
            {
                "key": "fanduel",
                "markets": [
                    {
                        "key": "player_shots_on_target",
                        "outcomes": [
                            {"name": "Over", "description": "Bukayo Saka",
                             "price": -120, "point": 1.5},
                            {"name": "Under", "description": "Bukayo Saka",
                             "price": +100, "point": 1.5},
                        ],
                    }
                ],
            }
        ],
    }
    quotes = parse_event_odds(payload, SOCCER_ODDS_UCL)
    assert len(quotes) == 2
    tickers = {q.market_kalshi_ticker for q in quotes}
    assert tickers == {"SYN-SOCCER-BUKAYOSAKA-SHOTS_ON_TARGET-1.5"}


def test_odds_api_parser_skips_markets_not_in_sport_config():
    """player_rebounds isn't in the soccer config — should be skipped."""
    payload = {
        "id": "evt1",
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "player_rebounds",
                        "outcomes": [
                            {"name": "Over", "description": "X",
                             "price": -110, "point": 5.5}
                        ],
                    }
                ],
            }
        ],
    }
    assert parse_event_odds(payload, SOCCER_ODDS_UCL) == []
    # But same payload IS valid for NBA
    quotes = parse_event_odds(payload, NBA_ODDS)
    assert len(quotes) == 1  # over only — no under, parser still emits over
