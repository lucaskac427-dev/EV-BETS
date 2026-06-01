"""Tests for the Kalshi market-sync ticker/title parser."""

from datetime import datetime, timezone

from src.kalshi.market_sync import parse_market


def _market(ticker: str, title: str, close: str = "2026-06-14T00:00:00Z") -> dict:
    return {"ticker": ticker, "title": title, "close_time": close}


def test_parses_points_market():
    p = parse_market(
        _market(
            "KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35",
            "Victor Wembanyama: 35+ points",
        )
    )
    assert p is not None
    assert p["sport"] == "nba"
    assert p["market_type"] == "player_prop"
    assert p["player_name"] == "Victor Wembanyama"
    assert p["stat_type"] == "points"
    assert p["line"] == 35.0
    assert p["game_id"] == "26MAY30SASOKC"
    assert p["game_starts_at"] == datetime(2026, 6, 14, tzinfo=timezone.utc)


def test_parses_other_stats():
    cases = [
        ("KXNBAAST-26MAY30SASOKC-SASVWEMBANYAMA1-8", "Victor Wembanyama: 8+ assists", "assists"),
        ("KXNBAREB-26MAY30SASOKC-SASVWEMBANYAMA1-16", "Victor Wembanyama: 16+ rebounds", "rebounds"),
        ("KXNBABLK-26MAY30SASOKC-OKCCHOLMGREN7-3", "Chet Holmgren: 3+ blocks", "blocks"),
        ("KXNBASTL-26MAY30SASOKC-OKCJWILLIAMS8-3", "Jalen Williams: 3+ steals", "steals"),
    ]
    for ticker, title, expected_stat in cases:
        p = parse_market(_market(ticker, title))
        assert p is not None, ticker
        assert p["stat_type"] == expected_stat


def test_skips_unknown_series():
    # Game-winner market, not a player prop
    p = parse_market(
        _market("KXNBAGAME-26MAY30SASOKC-SAS", "Game 7: San Antonio at Oklahoma City Winner?")
    )
    assert p is None


def test_skips_malformed_title():
    p = parse_market(_market("KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35", "no colon here"))
    assert p is None


def test_skips_missing_close_time():
    m = {"ticker": "KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35",
         "title": "Victor Wembanyama: 35+ points"}
    assert parse_market(m) is None
