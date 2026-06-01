"""Tests for the DraftKings Pick 6 pickcards parser."""

from src.providers.dk_pick6 import _pickgroup_ids, parse_pickcards


def _payload() -> dict:
    return {
        "pickSixMarketById": {
            "58": {"pickSixMarketId": 58, "name": "Points", "abbreviation": "PTS"},
            "60": {"pickSixMarketId": 60, "name": "Rebounds", "abbreviation": "REB"},
            "99": {"pickSixMarketId": 99, "name": "Double Doubles", "abbreviation": "DD"},
        },
        "entityInfoByDkId": {
            "800373": {"name": "J. McCain", "fullName": "Jared McCain"},
            "33258": {"name": "S. Gilgeous-Alexander", "fullName": "Shai Gilgeous-Alexander"},
        },
        "competitionById": {
            "6178110": {"compId": 6178110, "name": "SAS @ OKC",
                        "startTime": "2026-05-31T00:10:00.0000000+00:00"},
        },
        "pickCardByPickableId": {
            "1": {
                "pickableId": 1,
                "entities": [{"dkId": 800373, "compIds": [6178110]}],
                "activePickableMarkets": [
                    # active standard line -> kept
                    {"pickableMarketId": 111, "promoPickTypeId": 1, "pickSixMarketId": 58,
                     "isPaused": False, "targetValue": 12.5, "activeSelections": []},
                    # paused -> skipped
                    {"pickableMarketId": 112, "promoPickTypeId": 1, "pickSixMarketId": 58,
                     "isPaused": True, "targetValue": 5.5, "activeSelections": []},
                    # alt line, active -> kept (distinct line)
                    {"pickableMarketId": 113, "promoPickTypeId": 1, "pickSixMarketId": 58,
                     "isPaused": False, "targetValue": 17.5, "activeSelections": []},
                    # Gimme promo (promoPickTypeId 2) -> skipped
                    {"pickableMarketId": 114, "promoPickTypeId": 2, "pickSixMarketId": 58,
                     "isPaused": False, "targetValue": 9.5, "activeSelections": []},
                    # unmapped stat (Double Doubles) -> skipped
                    {"pickableMarketId": 115, "promoPickTypeId": 1, "pickSixMarketId": 99,
                     "isPaused": False, "targetValue": 0.5, "activeSelections": []},
                ],
            },
            "2": {
                "pickableId": 2,
                "entities": [{"dkId": 33258, "compIds": [6178110]}],
                "activePickableMarkets": [
                    {"pickableMarketId": 220, "promoPickTypeId": 1, "pickSixMarketId": 60,
                     "isPaused": False, "targetValue": 8.5, "activeSelections": []},
                ],
            },
        },
    }


def test_parses_standard_lines_and_skips_paused_promo_unmapped():
    lines = parse_pickcards(_payload(), "NBA")
    keyed = {(l.player_name, l.stat_type, l.line) for l in lines}
    assert ("Jared McCain", "points", 12.5) in keyed
    assert ("Jared McCain", "points", 17.5) in keyed
    assert ("Shai Gilgeous-Alexander", "rebounds", 8.5) in keyed
    # paused (5.5), Gimme promo (9.5), and unmapped Double Doubles (0.5) excluded
    assert all(l.line not in (5.5, 9.5, 0.5) for l in lines)
    assert len(lines) == 3


def test_uses_full_name_and_competition_start_and_source():
    line = next(l for l in parse_pickcards(_payload(), "NBA") if l.line == 12.5)
    assert line.player_name == "Jared McCain"  # fullName, not abbreviated
    assert line.stat_type == "points"
    assert line.odds_type == "standard"
    assert line.game_starts_at.year == 2026 and line.game_starts_at.month == 5
    assert line.external_id == "111"


def test_dedupes_same_player_stat_line():
    payload = _payload()
    # duplicate the 12.5 market under a different pickableMarketId
    payload["pickCardByPickableId"]["1"]["activePickableMarkets"].append(
        {"pickableMarketId": 999, "promoPickTypeId": 1, "pickSixMarketId": 58,
         "isPaused": False, "targetValue": 12.5, "activeSelections": []}
    )
    lines = [l for l in parse_pickcards(payload, "NBA")
             if l.player_name == "Jared McCain" and l.line == 12.5]
    assert len(lines) == 1


def test_pickgroup_id_resolution_by_sport():
    main = {"pickGroups": [
        {"pickGroupId": 148400, "sportId": 4, "leagues": [{"leagueAbbreviation": "NBA"}]},
        {"pickGroupId": 200, "sportId": 4, "leagues": [{"leagueAbbreviation": "WNBA"}]},
        {"pickGroupId": 300, "sportId": 12, "leagues": [{"leagueAbbreviation": "EPL"}]},
    ]}
    assert _pickgroup_ids(main, "NBA") == [148400]   # WNBA excluded
    assert _pickgroup_ids(main, "SOCCER") == [300]   # matched by sportId 12
