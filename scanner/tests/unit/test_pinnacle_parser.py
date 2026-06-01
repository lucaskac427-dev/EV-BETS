"""Tests for the Pinnacle parser.

Mirrors the real arcadia API shape verified 2026-05-30: two separate list
endpoints (matchups + markets/straight) joined by matchupId. Player props are
matchups with type="special" and special.category="Player Props".
"""

from src.providers.pinnacle import (
    parse_pinnacle_description,
    parse_pinnacle_player_props,
)


def _prop_matchup(mid: int, desc: str) -> dict:
    return {
        "id": mid,
        "type": "special",
        "special": {"category": "Player Props", "description": desc},
    }


def _market(matchup_id: int, line: float, over_price: int, under_price: int) -> dict:
    return {
        "matchupId": matchup_id,
        "prices": [
            {"designation": "over", "price": over_price, "points": line},
            {"designation": "under", "price": under_price, "points": line},
        ],
    }


def test_description_regex_extracts_player_and_stat():
    # Old team-in-parens form
    assert parse_pinnacle_description("Nikola Jokic (DEN) Total Assists") == (
        "Nikola Jokic",
        "assists",
    )
    assert parse_pinnacle_description("Luka Doncic (DAL) Total Pts+Reb+Ast") == (
        "Luka Doncic",
        "pra",
    )
    # Current no-team form (Pinnacle changed format mid-2026)
    assert parse_pinnacle_description("De'Aaron Fox Total Rebounds") == (
        "De'Aaron Fox",
        "rebounds",
    )
    assert parse_pinnacle_description("De'Aaron Fox Total Threes Made") == (
        "De'Aaron Fox",
        "threes",
    )
    assert parse_pinnacle_description("Dylan Harper Total Pts & Rebs & Asts") == (
        "Dylan Harper",
        "pra",
    )


def test_description_regex_rejects_malformed():
    assert parse_pinnacle_description("not a player prop") == (None, None)
    # Stat phrase not in _STAT_MAP -> stat is None, so the pair is rejected.
    assert parse_pinnacle_description("Joel Embiid (PHI) Total Turnovers") == (
        None,
        None,
    )


def test_parses_over_under_quotes():
    matchups = [_prop_matchup(1001, "Nikola Jokic (DEN) Total Assists")]
    markets = [_market(1001, line=7.5, over_price=-118, under_price=-102)]

    quotes = parse_pinnacle_player_props(matchups, markets)

    assert len(quotes) == 2
    over = next(q for q in quotes if q.side == "over")
    under = next(q for q in quotes if q.side == "under")
    assert over.book == "pinnacle"
    assert over.market_kalshi_ticker == "SYN-NBA-NIKOLAJOKIC-ASSISTS-7.5"
    # -118 American -> decimal 1 + 100/118
    assert abs(float(over.decimal_odds) - (1 + 100 / 118)) < 1e-4
    assert abs(float(under.decimal_odds) - (1 + 100 / 102)) < 1e-4


def test_skips_non_player_prop_matchups():
    # type != "special" (regular game matchup)
    matchups = [
        {"id": 5555, "type": "matchup", "participants": [{"name": "LAL"}, {"name": "BOS"}]}
    ]
    markets = [_market(5555, line=220.5, over_price=-110, under_price=-110)]
    assert parse_pinnacle_player_props(matchups, markets) == []


def test_skips_non_player_prop_specials():
    # type=special but a different category (e.g., team total, futures)
    matchups = [
        {
            "id": 6666,
            "type": "special",
            "special": {
                "category": "Team Specials",
                "description": "Lakers Total Wins",
            },
        }
    ]
    markets = [_market(6666, line=50.5, over_price=-110, under_price=-110)]
    assert parse_pinnacle_player_props(matchups, markets) == []


def test_market_without_matching_matchup_is_skipped():
    matchups = [_prop_matchup(1001, "Nikola Jokic (DEN) Total Assists")]
    # market points at a matchup we never registered as a prop matchup
    markets = [_market(9999, line=7.5, over_price=-110, under_price=-110)]
    assert parse_pinnacle_player_props(matchups, markets) == []


def test_dedupes_double_fetched_markets():
    """Pinnacle's page sometimes fires the markets XHR twice on load. The
    parser must dedupe by (ticker, side) — first occurrence wins."""
    matchups = [_prop_matchup(1001, "Nikola Jokic (DEN) Total Assists")]
    market = _market(1001, line=7.5, over_price=-118, under_price=-102)
    quotes = parse_pinnacle_player_props(matchups, [market, market])
    assert len(quotes) == 2  # still just one over + one under


def test_empty_inputs():
    assert parse_pinnacle_player_props([], []) == []
    assert parse_pinnacle_player_props([_prop_matchup(1, "X (Y) Total Points")], []) == []
    assert parse_pinnacle_player_props([], [_market(1, 1.5, -110, -110)]) == []


def test_parses_participantid_format():
    """Current Pinnacle payloads put participantId on each price and the
    side comes from the matchup's participants list."""
    matchup = {
        "id": 1631512226,
        "type": "special",
        "special": {
            "category": "Player Props",
            "description": "Dylan Harper Total Pts & Rebs & Asts",
        },
        "participants": [
            {"id": 1631512227, "name": "Over"},
            {"id": 1631512228, "name": "Under"},
        ],
    }
    market = {
        "matchupId": 1631512226,
        "prices": [
            {"participantId": 1631512227, "points": 16.5, "price": -124},
            {"participantId": 1631512228, "points": 16.5, "price": -107},
        ],
    }
    quotes = parse_pinnacle_player_props([matchup], [market])
    assert len(quotes) == 2
    over = next(q for q in quotes if q.side == "over")
    under = next(q for q in quotes if q.side == "under")
    assert over.market_kalshi_ticker == "SYN-NBA-DYLANHARPER-PRA-16.5"
    assert under.market_kalshi_ticker == "SYN-NBA-DYLANHARPER-PRA-16.5"
